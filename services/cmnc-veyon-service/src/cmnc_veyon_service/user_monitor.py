"""Server-side user sampling independent of browser viewers.

Bound authentication concurrency and close monitor-only connections so a large
inventory cannot exhaust the proxy's connection pool or displace screen viewers.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass

from fastapi import HTTPException
import httpx

logger = logging.getLogger("uvicorn.error.veyon.users")


@dataclass
class ScheduledTarget:
    row: dict
    due: float
    busy: bool = False
    failures: int = 0
    known: bool = False
    revision: int = 0


class UserMonitor:
    def __init__(self, bridge, target_type, client):
        self.bridge, self.target_type, self.client = bridge, target_type, client
        self.base_url = os.environ.get("CMNC_VEYON_CLASSROOM_SERVICE_URL", "http://cmnc-classroom-service:8002").rstrip("/")
        self.interval = int(os.environ.get("CMNC_VEYON_USER_POLL_INTERVAL_SECONDS", "30"))
        concurrency = int(os.environ.get("CMNC_VEYON_USER_POLL_CONCURRENCY", "2"))
        if not 5 <= self.interval <= 3600 or not 1 <= concurrency <= 8:
            raise ValueError("Veyon user polling requires interval 5..3600 seconds and concurrency 1..8")
        self.concurrency = concurrency
        self.capacity = asyncio.Semaphore(concurrency)
        self.targets: dict[int, ScheduledTarget] = {}
        self.observation_tasks: dict[int, asyncio.Task] = {}
        self.running_ids: set[int] = set()
        self.changed = asyncio.Condition()
        self.targets_refreshed_at = float("-inf")
        self.valid_seconds = max(90, self.interval * 3)

    async def observe(self, row):
        async with self.capacity:
            known, username = False, None
            if row.get("online"):
                try:
                    target = self.target_type(**{key: row[key] for key in ("device_id", "router_id", "classroom_id", "host")})
                    data = await self.bridge.read_user(target)
                    known, username = True, data["username"]
                except (HTTPException, ValueError):
                    # Authentication failure, offline target and missing key are
                    # unknown observations, never a logged-out user.
                    pass
            return {**{key: row[key] for key in ("device_id", "router_id", "classroom_id", "host")},
                "known": known, "username": username, "observed_at": datetime.now(timezone.utc).isoformat()}

    async def publish(self, observations):
        response = await self.client.post(self.base_url + "/internal/veyon/user-observations",
            json={"observations": observations, "valid_seconds": self.valid_seconds}, timeout=10)
        response.raise_for_status()

    async def poll_once(self):
        response = await self.client.get(self.base_url + "/internal/veyon/user-targets", timeout=10)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Invalid user target list")
        tasks = [asyncio.create_task(self.observe(row)) for row in rows]
        pending, published_at = [], 0.0
        try:
            for task in asyncio.as_completed(tasks):
                pending.append(await task)
                if len(pending) >= 20 or time.monotonic() - published_at >= 1:
                    await self.publish(pending)
                    pending = []
                    published_at = time.monotonic()
            if pending:
                await self.publish(pending)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def refresh_targets(self):
        response = await self.client.get(self.base_url + "/internal/veyon/user-targets", timeout=10)
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Invalid user target list")
        # Validate before changing the active schedule.
        incoming = {row["device_id"]: row for row in rows}
        now = time.monotonic()
        async with self.changed:
            for device_id in list(self.targets):
                if device_id not in incoming:
                    del self.targets[device_id]
                    if task := self.observation_tasks.get(device_id):
                        task.cancel()
            for device_id, row in incoming.items():
                entry = self.targets.get(device_id)
                if entry is None:
                    self.targets[device_id] = ScheduledTarget(row, now)
                elif entry.row != row:
                    entry.row = row
                    entry.revision += 1
                    if task := self.observation_tasks.get(device_id):
                        task.cancel()
                    entry.due, entry.failures, entry.known = now, 0, False
            self.targets_refreshed_at = now
            self.changed.notify_all()

    async def invalidate_keys(self, scope, scope_id):
        async with self.changed:
            for entry in self.targets.values():
                if entry.row.get(scope + "_id") == scope_id:
                    entry.due, entry.failures, entry.known = time.monotonic(), 0, False
                    entry.revision += 1
            self.changed.notify_all()

    async def refresh_loop(self):
        while True:
            try:
                await self.refresh_targets()
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                logger.warning("Veyon user target refresh failed; history freshness remains bounded")
            await asyncio.sleep(self.interval)

    async def take_target(self):
        async with self.changed:
            while True:
                now = time.monotonic()
                available = [entry for entry in self.targets.values() if not entry.busy and entry.row["device_id"] not in self.running_ids]
                due = [entry for entry in available if entry.due <= now]
                if due and now - self.targets_refreshed_at <= self.valid_seconds:
                    # Known working PCs are not put behind a backlog of failing
                    # or newly discovered infrastructure targets.
                    entry = min(due, key=lambda item: (not item.known, item.due, item.row["device_id"]))
                    entry.busy = True
                    self.running_ids.add(entry.row["device_id"])
                    return entry, dict(entry.row), entry.revision
                delay = min((entry.due - now for entry in available if entry.due > now), default=self.interval)
                try:
                    await asyncio.wait_for(self.changed.wait(), timeout=max(.01, delay))
                except TimeoutError:
                    pass

    async def worker(self):
        while True:
            entry, row, revision = await self.take_target()
            started = time.monotonic()
            succeeded = False
            try:
                task = asyncio.create_task(self.observe(row))
                self.observation_tasks[row["device_id"]] = task
                observation = await task
                # Removed/moved/offline targets cannot publish a late result.
                if self.targets.get(row["device_id"]) is entry and entry.revision == revision:
                    await self.publish([observation])
                    succeeded = observation["known"]
            except asyncio.CancelledError:
                # Target removal cancels only its observation, not the worker.
                if asyncio.current_task().cancelling():
                    raise
            except (httpx.HTTPError, HTTPException, ValueError, KeyError, TypeError):
                logger.warning("Veyon user observation failed device_id=%s", row["device_id"])
            finally:
                async with self.changed:
                    self.observation_tasks.pop(row["device_id"], None)
                    entry.busy = False
                    self.running_ids.discard(row["device_id"])
                    if entry.revision == revision:
                        entry.known = succeeded
                        entry.failures = 0 if succeeded or not row.get("online") else min(entry.failures + 1, 5)
                        delay = min(self.interval * 2 ** entry.failures, max(300, self.interval))
                        # Healthy targets follow their own start-to-start cadence.
                        # Failures back off from completion instead of busy retrying.
                        entry.due = max(started + self.interval, time.monotonic() + .01) if succeeded else time.monotonic() + delay
                    self.changed.notify_all()

    async def run(self):
        tasks = [asyncio.create_task(self.refresh_loop())]
        tasks.extend(asyncio.create_task(self.worker()) for _ in range(self.concurrency))
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
