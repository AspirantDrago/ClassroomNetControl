import asyncio
import base64
import json
import re
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from cmnc_veyon_service.command_jobs import CommandJobs, CommandResult, StartCommandJob
from cmnc_veyon_service.main import Target


def setup(tmp_path, **options):
    captured = []
    async def operate(target, action, arguments):
        assert action == "command"
        encoded = arguments["applications"][0].split("-EncodedCommand ", 1)[1]
        script = base64.b64decode(encoded).decode("utf-16-le")
        captured.append((target.device_id, re.search(r"Bearer ([A-Za-z0-9_-]+)", script).group(1)))
    bridge = SimpleNamespace(store=SimpleNamespace(cipher=Fernet(Fernet.generate_key())), operate=operate)
    manager = CommandJobs(tmp_path, bridge, Target, **options)
    payload = StartCommandJob(owner="user:1", classroom_id=7, router_id=2, command="Write-Output 'secret-test-command'",
        callback_url="https://cmnc.example.test", skipped_count=1,
        targets=[{"device_id": n, "classroom_id": 7, "router_id": 2, "host": f"192.168.1.{n}", "name": f"PC-{n}"} for n in (10, 11)])
    return manager, payload, captured


def test_output_jobs_are_durable_private_and_one_use(tmp_path):
    async def run():
        manager, payload, captured = setup(tmp_path)
        job = manager.create(payload)
        await asyncio.gather(*list(manager.tasks))
        tokens = dict(captured)
        assert len(tokens) == 2 and tokens[10] != tokens[11]
        assert job["skipped_count"] == 1 and not job["finished"]
        assert all(r["stdout_truncated"] is False and r["stderr_truncated"] is False for r in job["results"])
        with manager.db() as db:
            encrypted = db.execute("SELECT command FROM command_jobs").fetchone()[0]
            assert isinstance(encrypted, bytes) and b"secret-test-command" not in encrypted
        assert not any(token in json.dumps(job) for token in tokens.values())
        with pytest.raises(HTTPException) as denied:
            manager.script(job["id"], 11, tokens[10])
        assert denied.value.status_code == 403
        script = manager.script(job["id"], 10, tokens[10])
        assert "__CALLBACK__" not in script and "__COMMAND__" not in script
        manager.result(job["id"], 10, tokens[10], CommandResult(stdout="Привет", stderr="Ошибка", exit_code=7, stdout_truncated=True))
        with pytest.raises(HTTPException):
            manager.result(job["id"], 10, tokens[10], CommandResult(stdout="overwrite", exit_code=0))
        restored = CommandJobs(tmp_path, manager.bridge, Target)
        result = restored.get(job["id"])
        assert result["results"][0]["stdout"] == "Привет"
        assert result["results"][0]["stderr"] == "Ошибка"
        assert result["results"][0]["exit_code"] == 7
        assert result["results"][0]["result_received"]
        assert result["results"][0]["stdout_truncated"] is True
        assert result["results"][0]["stderr_truncated"] is False
        assert not restored.tasks  # Restart must never relaunch remote commands.
        restored.result(job["id"], 11, tokens[11], CommandResult(exit_code=0))
        assert restored.get(job["id"])["finished"]
        await manager.close()
    asyncio.run(run())


def test_expiration_rejects_late_callbacks_and_cleans_up(tmp_path):
    async def run():
        manager, payload, captured = setup(tmp_path)
        job = manager.create(payload)
        await asyncio.gather(*list(manager.tasks))
        with manager.db() as db:
            db.execute("UPDATE command_jobs SET deadline=?", (time.time()-1,))
        result = manager.get(job["id"])
        assert result["finished"] and all(r["state"] == "timed_out" for r in result["results"])
        assert all(not r["result_received"] for r in result["results"])
        with pytest.raises(HTTPException) as late:
            manager.result(job["id"], 10, dict(captured)[10], CommandResult(exit_code=0))
        assert late.value.status_code == 410
        with manager.db() as db:
            db.execute("UPDATE command_jobs SET deadline=?", (time.time()-601,))
        with pytest.raises(HTTPException) as expired:
            manager.get(job["id"])
        assert expired.value.status_code == 404
    asyncio.run(run())


def test_transport_error_does_not_discard_an_authenticated_result(tmp_path):
    async def run():
        manager, payload, captured = setup(tmp_path)
        original = manager.bridge.operate
        async def failed(*args, **kwargs):
            await original(*args, **kwargs)
            raise HTTPException(503, "network failure")
        manager.bridge.operate = failed
        job = manager.create(payload)
        await asyncio.gather(*list(manager.tasks))
        assert manager.get(job["id"])["results"][0]["dispatch_error"]
        manager.result(job["id"], 10, dict(captured)[10], CommandResult(exit_code=0))
        result = manager.get(job["id"])["results"][0]
        assert result["state"] == "completed" and result["dispatch_error"] is None
    asyncio.run(run())


def test_dispatch_limits_concurrency_without_retrying(tmp_path):
    async def run():
        manager, payload, _ = setup(tmp_path, concurrency=2)
        payload.targets = [payload.targets[0].model_copy(update={"device_id": i, "host": f"192.168.1.{i}"}) for i in range(10, 20)]
        active = peak = 0
        calls = []
        async def operate(target, *args, **kwargs):
            nonlocal active, peak
            calls.append(target.device_id)
            active += 1; peak = max(peak, active)
            try: await asyncio.sleep(.01)
            finally: active -= 1
        manager.bridge.operate = operate
        manager.create(payload)
        await asyncio.gather(*list(manager.tasks))
        assert peak == 2 and len(calls) == len(set(calls)) == 10
    asyncio.run(run())


@pytest.mark.parametrize("seconds", [0, 4, 3601])
def test_invalid_collection_timeout_is_rejected(tmp_path, seconds):
    with pytest.raises(ValueError): setup(tmp_path, timeout_seconds=seconds)
