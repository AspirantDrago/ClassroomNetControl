"""Durable, bounded command-result collection; Veyon remains the launch transport."""
import asyncio
import base64
import hashlib
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator
from cmnc_contracts.veyon_actions import DeviceAction

OUTPUT_LIMIT = 65536


def callback_base(value: str) -> str:
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Некорректный порт Loopback") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(c.isspace() for c in value)):
        raise ValueError("Укажите HTTP/HTTPS адрес CMNC без логина, пароля и параметров")
    return value


class CommandTarget(BaseModel):
    device_id: int = Field(gt=0)
    classroom_id: int = Field(gt=0)
    router_id: int = Field(gt=0)
    host: str
    name: str = Field(max_length=255)


class StartCommandJob(BaseModel):
    owner: str = Field(min_length=1, max_length=200)
    classroom_id: int = Field(gt=0)
    router_id: int = Field(gt=0)
    command: SecretStr
    callback_url: str = Field(max_length=2048)
    targets: list[CommandTarget] = Field(max_length=512)
    skipped_count: int = Field(default=0, ge=0)
    _callback = field_validator("callback_url")(callback_base)

    @field_validator("command")
    @classmethod
    def command_not_empty(cls, value):
        if not value.get_secret_value().strip() or len(value.get_secret_value()) > 16000:
            raise ValueError("Введите команду длиной не более 16000 символов")
        return value


class CommandResult(BaseModel):
    stdout: str = Field(default="", max_length=OUTPUT_LIMIT)
    stderr: str = Field(default="", max_length=OUTPUT_LIMIT)
    exit_code: int | None = Field(default=None, ge=-2147483648, le=4294967295)
    timed_out: bool = False
    stdout_truncated: bool = False
    stderr_truncated: bool = False


def encoded(value, encoding="utf-8"):
    return base64.b64encode(value.encode(encoding)).decode("ascii")


def bootstrap(url: str, token: str):
    # Only this short launcher is passed through CreateProcess (32767-char limit).
    return ("$ErrorActionPreference='Stop'; "
        "[Net.ServicePointManager]::SecurityProtocol=[Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12; "
        f"$u=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{encoded(url)}')); "
        f"$h=@{{Authorization='Bearer {token}'}}; "
        "$r=Invoke-WebRequest -Uri $u -Headers $h -UseBasicParsing -TimeoutSec 10; "
        "& ([scriptblock]::Create($r.Content))")


def runner(command: str, url: str, token: str, runtime_seconds: float):
    template = Path(__file__).with_name("command_runner.ps1").read_text(encoding="utf-8")
    return (template.replace("__CALLBACK__", encoded(url)).replace("__TOKEN__", token)
        .replace("__COMMAND__", encoded(command, "utf-16-le"))
        .replace("__RUNTIME_MS__", str(max(1000, int(runtime_seconds * 1000)))))


class CommandJobs:
    def __init__(self, directory: Path, bridge, target_type, timeout_seconds=60, concurrency=30):
        if not 5 <= timeout_seconds <= 3600:
            raise ValueError("CMNC_VEYON_COMMAND_RESULT_TIMEOUT_SECONDS must be between 5 and 3600")
        self.bridge = bridge
        self.target_type = target_type
        self.timeout = timeout_seconds
        self.path = directory / "command-jobs.sqlite3"
        self.cipher = bridge.store.cipher
        descriptor = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
        os.close(descriptor)
        self.tasks: set[asyncio.Task] = set()
        self.capacity = asyncio.Semaphore(concurrency)
        with self.db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS command_jobs (
                    id TEXT PRIMARY KEY, owner TEXT NOT NULL, classroom_id INTEGER NOT NULL,
                    router_id INTEGER NOT NULL, command BLOB NOT NULL, callback_url TEXT NOT NULL,
                    created_at REAL NOT NULL, deadline REAL NOT NULL, skipped_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS command_results (
                    job_id TEXT NOT NULL REFERENCES command_jobs(id) ON DELETE CASCADE,
                    device_id INTEGER NOT NULL, name TEXT NOT NULL, host TEXT NOT NULL,
                    token_hash TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    dispatch_error TEXT, stdout TEXT NOT NULL DEFAULT '', stderr TEXT NOT NULL DEFAULT '',
                    exit_code INTEGER, stdout_truncated INTEGER NOT NULL DEFAULT 0,
                    stderr_truncated INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(job_id, device_id));
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def maintain(self, db):
        now = time.time()
        db.execute("DELETE FROM command_jobs WHERE deadline < ?", (now - 600,))
        db.execute("UPDATE command_results SET state='timed_out' WHERE state='pending' AND job_id IN "
                   "(SELECT id FROM command_jobs WHERE deadline <= ?)", (now,))

    def create(self, payload: StartCommandJob):
        now = time.time()
        job_id = secrets.token_urlsafe(24)
        deadline = now + self.timeout
        if len({d.device_id for d in payload.targets}) != len(payload.targets):
            raise HTTPException(422, "Повторяющиеся устройства")
        if any(d.router_id != payload.router_id or d.classroom_id != payload.classroom_id for d in payload.targets):
            raise HTTPException(422, "Устройства не принадлежат аудитории")
        # Validate addresses before creating a task. Targets are supplied by the gateway.
        for d in payload.targets:
            self.target_type(**d.model_dump(exclude={"name"}))
        tokens = {d.device_id: secrets.token_urlsafe(32) for d in payload.targets}
        with self.db() as db:
            self.maintain(db)
            if db.execute("SELECT count(*) FROM command_jobs WHERE deadline > ?", (now,)).fetchone()[0] >= 64:
                raise HTTPException(429, "Достигнут лимит активных заданий")
            db.execute("INSERT INTO command_jobs VALUES (?,?,?,?,?,?,?,?,?)", (
                job_id, payload.owner, payload.classroom_id, payload.router_id,
                self.cipher.encrypt(payload.command.get_secret_value().encode()), payload.callback_url,
                now, deadline, payload.skipped_count))
            db.executemany("INSERT INTO command_results(job_id,device_id,name,host,token_hash) VALUES (?,?,?,?,?)", [
                (job_id, d.device_id, d.name, d.host, hashlib.sha256(tokens[d.device_id].encode()).hexdigest()) for d in payload.targets])
        task = asyncio.create_task(self.dispatch(job_id, payload, tokens, deadline))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return self.get(job_id)

    async def dispatch(self, job_id, payload, tokens, deadline):
        async def send(device):
            try:
                async with asyncio.timeout(max(.01, deadline - time.time())):
                    async with self.capacity:
                        script_url = f"{payload.callback_url}/api/veyon/command-scripts/{job_id}/{device.device_id}"
                        command = bootstrap(script_url, tokens[device.device_id])
                        arguments = DeviceAction(action="command", text=command).feature_arguments()
                        target = self.target_type(**device.model_dump(exclude={"name"}))
                        await self.bridge.operate(target, "command", arguments=arguments)
            except Exception as exc:
                detail = (str(exc.detail) if isinstance(exc, HTTPException) else "Истекло время отправки"
                          if isinstance(exc, TimeoutError) else "Ошибка отправки: " + type(exc).__name__)
                with self.db() as db:
                    # A transport error does not prove that the remote process never started.
                    db.execute("UPDATE command_results SET dispatch_error=? WHERE job_id=? AND device_id=? AND state='pending'",
                               (detail[:1000], job_id, device.device_id))
        await asyncio.gather(*(send(d) for d in payload.targets))

    def get(self, job_id):
        with self.db() as db:
            self.maintain(db)
            job = db.execute("SELECT * FROM command_jobs WHERE id=?", (job_id,)).fetchone()
            rows = db.execute("SELECT device_id,name,host,state,dispatch_error,stdout,stderr,exit_code,stdout_truncated,stderr_truncated "
                              " ,token_hash='' AS result_received FROM command_results WHERE job_id=? ORDER BY device_id", (job_id,)).fetchall()
        if not job:
            raise HTTPException(404, "Задание не найдено или срок хранения истёк")
        return {"id": job_id, "owner": job["owner"], "classroom_id": job["classroom_id"],
                "created_at": job["created_at"], "deadline": job["deadline"], "skipped_count": job["skipped_count"],
                "finished": all(r["state"] != "pending" for r in rows), "results": [{**dict(r), "result_received": bool(r["result_received"])} for r in rows]}

    def authorized(self, db, job_id, device_id, token):
        job = db.execute("SELECT j.*,r.token_hash,r.state FROM command_jobs j JOIN command_results r ON j.id=r.job_id "
                         "WHERE j.id=? AND r.device_id=?", (job_id, device_id)).fetchone()
        if not job or not secrets.compare_digest(job["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
            raise HTTPException(403, "Недействительный токен результата")
        if job["deadline"] <= time.time() or job["state"] != "pending":
            raise HTTPException(410, "Сбор результата завершён")
        return job

    def script(self, job_id, device_id, token):
        with self.db() as db:
            job = self.authorized(db, job_id, device_id, token)
            command = self.cipher.decrypt(job["command"]).decode()
            url = f"{job['callback_url']}/api/veyon/command-results/{job_id}/{device_id}"
            return runner(command, url, token, job["deadline"] - time.time() - 5)

    def result(self, job_id, device_id, token, payload: CommandResult):
        with self.db() as db:
            self.authorized(db, job_id, device_id, token)
            update = db.execute("UPDATE command_results SET dispatch_error=NULL,state=?,stdout=?,stderr=?,exit_code=?,stdout_truncated=?,stderr_truncated=?,token_hash='' "
                       "WHERE job_id=? AND device_id=? AND state='pending' AND token_hash=?", (
                           "timed_out" if payload.timed_out else "completed", payload.stdout, payload.stderr, payload.exit_code,
                           payload.stdout_truncated, payload.stderr_truncated, job_id, device_id, hashlib.sha256(token.encode()).hexdigest()))
            if update.rowcount != 1:
                raise HTTPException(410, "Сбор результата завершён")
        return {"accepted": True}

    async def close(self):
        for task in list(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
