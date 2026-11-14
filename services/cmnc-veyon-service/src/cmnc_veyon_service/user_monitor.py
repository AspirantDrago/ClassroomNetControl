"""Server-side user sampling independent of browser viewers.

Bound authentication concurrency and close monitor-only connections so a large
inventory cannot exhaust the proxy's connection pool or displace screen viewers.
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

from fastapi import HTTPException
import httpx

logger = logging.getLogger("uvicorn.error.veyon.users")


class UserMonitor:
    def __init__(self, bridge, target_type, client):
        self.bridge, self.target_type, self.client = bridge, target_type, client
        self.base_url = os.environ.get("CMNC_VEYON_CLASSROOM_SERVICE_URL", "http://cmnc-classroom-service:8002").rstrip("/")
        self.interval = int(os.environ.get("CMNC_VEYON_USER_POLL_INTERVAL_SECONDS", "30"))
        concurrency = int(os.environ.get("CMNC_VEYON_USER_POLL_CONCURRENCY", "2"))
        if not 5 <= self.interval <= 3600 or not 1 <= concurrency <= 8:
            raise ValueError("Veyon user polling requires interval 5..3600 seconds and concurrency 1..8")
        self.capacity = asyncio.Semaphore(concurrency)
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

    async def run(self):
        while True:
            try:
                await self.poll_once()
            except (httpx.HTTPError, HTTPException, ValueError, KeyError, TypeError):
                logger.warning("Veyon user history poll failed; unobserved intervals remain unknown")
            await asyncio.sleep(self.interval)
