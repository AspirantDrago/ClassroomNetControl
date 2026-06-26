from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

import httpx

RouterServiceStatus = Literal["starting", "ok", "warning", "error", "stale", "disabled"]


@dataclass(frozen=True, slots=True)
class RouterConnection:
    id: int
    name: str
    api_host: str
    api_port: int
    api_use_ssl: bool
    api_verify_tls: bool
    api_username: str
    api_password: str
    is_enabled: bool
    poll_enabled: bool
    sync_enabled: bool
    poll_interval_seconds: int

    @property
    def base_url(self) -> str:
        scheme = "https" if self.api_use_ssl else "http"
        return f"{scheme}://{self.api_host}:{self.api_port}/rest"


def parse_router_connection(data: dict[str, Any]) -> RouterConnection:
    return RouterConnection(
        id=int(data["id"]),
        name=str(data["name"]),
        api_host=str(data["api_host"]),
        api_port=int(data["api_port"]),
        api_use_ssl=bool(data["api_use_ssl"]),
        api_verify_tls=bool(data.get("api_verify_tls", False)),
        api_username=str(data["api_username"]),
        api_password=str(data["api_password"]),
        is_enabled=bool(data["is_enabled"]),
        poll_enabled=bool(data["poll_enabled"]),
        sync_enabled=bool(data["sync_enabled"]),
        poll_interval_seconds=int(data["poll_interval_seconds"]),
    )


def serialize_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


class InventoryClient:
    def __init__(self, base_url: str, timeout_seconds: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    async def get_active_routers(self) -> list[RouterConnection]:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(f"{self._base_url}/internal/routers/active")
            response.raise_for_status()

        data = response.json()
        if not isinstance(data, list):
            raise TypeError("Inventory active routers response is not a list")

        routers: list[RouterConnection] = []
        for item in data:
            if isinstance(item, dict):
                routers.append(parse_router_connection(item))

        return routers

    async def get_router_connection(self, router_id: int) -> RouterConnection:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.get(
                f"{self._base_url}/internal/routers/{router_id}/connection"
            )
            response.raise_for_status()

        data = response.json()
        if not isinstance(data, dict):
            raise TypeError("Inventory router connection response is not an object")

        return parse_router_connection(data)

    async def update_router_service_status(
        self,
        *,
        router_id: int,
        service_name: str,
        worker_id: str | None,
        status: RouterServiceStatus,
        is_running: bool,
        heartbeat_at: datetime | None = None,
        last_started_at: datetime | None = None,
        last_attempt_at: datetime | None = None,
        last_success_at: datetime | None = None,
        last_error_at: datetime | None = None,
        last_error: str | None = None,
        consecutive_failures: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "service_name": service_name,
            "worker_id": worker_id,
            "status": status,
            "is_running": is_running,
            "heartbeat_at": serialize_datetime(heartbeat_at),
            "last_started_at": serialize_datetime(last_started_at),
            "last_attempt_at": serialize_datetime(last_attempt_at),
            "last_success_at": serialize_datetime(last_success_at),
            "last_error_at": serialize_datetime(last_error_at),
            "last_error": last_error,
            "consecutive_failures": consecutive_failures,
            "details": details or {},
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.put(
                f"{self._base_url}/internal/routers/{router_id}/status/{service_name}",
                json=payload,
            )
            response.raise_for_status()
