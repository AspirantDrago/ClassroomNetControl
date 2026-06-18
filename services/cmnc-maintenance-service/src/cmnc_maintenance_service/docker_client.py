import asyncio
from datetime import datetime
from typing import Any

import httpx

from cmnc_maintenance_service.schemas import ContainerStatus


class DockerClient:
    def __init__(
        self,
        socket_path: str,
        timeout_seconds: float,
        container_name_prefix: str,
    ) -> None:
        self._socket_path = socket_path
        self._timeout_seconds = timeout_seconds
        self._container_name_prefix = container_name_prefix

    async def get_containers_status(self) -> list[ContainerStatus]:
        async with httpx.AsyncClient(
            base_url="http://docker",
            transport=httpx.AsyncHTTPTransport(uds=self._socket_path),
            timeout=self._timeout_seconds,
        ) as client:
            containers = await self._request_json(
                client=client,
                method="GET",
                path="/containers/json",
                params={"all": "true"},
            )

            if not isinstance(containers, list):
                raise TypeError("Docker containers response is not a list")

            tasks = []

            for item in containers:
                if not isinstance(item, dict):
                    continue

                container_id = str(item.get("Id") or "")
                if not container_id:
                    continue

                name = self._get_container_name(item)
                if not self._should_include_container(name):
                    continue

                tasks.append(
                    self._build_container_status(
                        client=client,
                        container_id=container_id,
                        container_name=name,
                        container_item=item,
                    )
                )

            statuses = await asyncio.gather(*tasks)

        result = [status for status in statuses if status is not None]
        result.sort(key=lambda container: container.name)
        return result

    async def _build_container_status(
        self,
        client: httpx.AsyncClient,
        container_id: str,
        container_name: str,
        container_item: dict[str, Any],
    ) -> ContainerStatus | None:
        try:
            inspect_task = self._safe_inspect_container(client, container_id)
            stats_task = self._safe_get_container_stats(client, container_id, container_item)
            inspect_data, stats_data = await asyncio.gather(inspect_task, stats_task)

            state = str(container_item.get("State") or "unknown")
            docker_status = str(container_item.get("Status") or "")
            image = str(container_item.get("Image") or "")
            health = self._extract_health(inspect_data, docker_status)
            started_at = self._extract_started_at(inspect_data)
            cpu_percent = self._calculate_cpu_percent(stats_data)
            memory_usage_bytes, memory_limit_bytes, memory_percent = self._calculate_memory(stats_data)

            return ContainerStatus(
                id=container_id[:12],
                name=container_name,
                image=image,
                state=state,
                state_label=self._state_label(state, health),
                health=health,
                docker_status=docker_status,
                cpu_percent=cpu_percent,
                memory_usage_bytes=memory_usage_bytes,
                memory_limit_bytes=memory_limit_bytes,
                memory_percent=memory_percent,
                started_at=started_at,
            )
        except Exception:
            return None

    async def _safe_inspect_container(
        self,
        client: httpx.AsyncClient,
        container_id: str,
    ) -> dict[str, Any] | None:
        try:
            data = await self._request_json(
                client=client,
                method="GET",
                path=f"/containers/{container_id}/json",
            )
        except (httpx.HTTPError, TypeError):
            return None

        return data if isinstance(data, dict) else None

    async def _safe_get_container_stats(
        self,
        client: httpx.AsyncClient,
        container_id: str,
        container_item: dict[str, Any],
    ) -> dict[str, Any] | None:
        if container_item.get("State") != "running":
            return None

        try:
            data = await self._request_json(
                client=client,
                method="GET",
                path=f"/containers/{container_id}/stats",
                params={"stream": "false"},
            )
        except (httpx.HTTPError, TypeError):
            return None

        return data if isinstance(data, dict) else None

    def _get_container_name(self, item: dict[str, Any]) -> str:
        names = item.get("Names")

        if isinstance(names, list) and names:
            return str(names[0]).lstrip("/")

        return str(item.get("Id") or "")[:12]

    def _should_include_container(self, name: str) -> bool:
        if not self._container_name_prefix:
            return True

        return name.startswith(self._container_name_prefix)

    def _extract_health(
        self,
        inspect_data: dict[str, Any] | None,
        docker_status: str,
    ) -> str | None:
        if inspect_data is not None:
            state = inspect_data.get("State")
            if isinstance(state, dict):
                health = state.get("Health")
                if isinstance(health, dict):
                    health_status = health.get("Status")
                    if health_status is not None:
                        return str(health_status)

        lowered_status = docker_status.lower()
        if "(healthy)" in lowered_status:
            return "healthy"
        if "(unhealthy)" in lowered_status:
            return "unhealthy"
        if "(health: starting)" in lowered_status:
            return "starting"

        return None

    def _extract_started_at(
        self,
        inspect_data: dict[str, Any] | None,
    ) -> datetime | None:
        if inspect_data is None:
            return None

        state = inspect_data.get("State")
        if not isinstance(state, dict):
            return None

        started_at = state.get("StartedAt")
        if not isinstance(started_at, str) or started_at.startswith("0001-"):
            return None

        try:
            return datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            return None

    def _state_label(self, state: str, health: str | None) -> str:
        if state == "running" and health == "starting":
            return "запускается"

        if state == "running":
            return "запущен"

        if state in {"created", "restarting"}:
            return "запускается"

        if state in {"exited", "dead", "removing"}:
            return "остановлен"

        if state == "paused":
            return "приостановлен"

        return state

    def _calculate_cpu_percent(self, stats: dict[str, Any] | None) -> float | None:
        if stats is None:
            return None

        cpu_stats = stats.get("cpu_stats")
        precpu_stats = stats.get("precpu_stats")

        if not isinstance(cpu_stats, dict) or not isinstance(precpu_stats, dict):
            return None

        cpu_usage = cpu_stats.get("cpu_usage")
        precpu_usage = precpu_stats.get("cpu_usage")

        if not isinstance(cpu_usage, dict) or not isinstance(precpu_usage, dict):
            return None

        total_usage = self._as_float(cpu_usage.get("total_usage"))
        previous_total_usage = self._as_float(precpu_usage.get("total_usage"))
        system_usage = self._as_float(cpu_stats.get("system_cpu_usage"))
        previous_system_usage = self._as_float(precpu_stats.get("system_cpu_usage"))

        if (
            total_usage is None
            or previous_total_usage is None
            or system_usage is None
            or previous_system_usage is None
        ):
            return None

        cpu_delta = total_usage - previous_total_usage
        system_delta = system_usage - previous_system_usage

        if cpu_delta <= 0 or system_delta <= 0:
            return 0.0

        online_cpus = self._as_float(cpu_stats.get("online_cpus"))

        if online_cpus is None:
            per_cpu_usage = cpu_usage.get("percpu_usage")
            if isinstance(per_cpu_usage, list) and per_cpu_usage:
                online_cpus = float(len(per_cpu_usage))
            else:
                online_cpus = 1.0

        return round((cpu_delta / system_delta) * online_cpus * 100.0, 2)

    def _calculate_memory(
        self,
        stats: dict[str, Any] | None,
    ) -> tuple[int | None, int | None, float | None]:
        if stats is None:
            return None, None, None

        memory_stats = stats.get("memory_stats")
        if not isinstance(memory_stats, dict):
            return None, None, None

        usage = self._as_int(memory_stats.get("usage"))
        limit = self._as_int(memory_stats.get("limit"))

        nested_stats = memory_stats.get("stats")
        if isinstance(nested_stats, dict):
            cache = self._as_int(nested_stats.get("cache"))
            if usage is not None and cache is not None and usage >= cache:
                usage -= cache

        percent = None
        if usage is not None and limit is not None and limit > 0:
            percent = round((usage / limit) * 100.0, 2)

        return usage, limit, percent

    def _as_float(self, value: Any) -> float | None:
        if isinstance(value, int | float):
            return float(value)

        return None

    def _as_int(self, value: Any) -> int | None:
        if isinstance(value, int):
            return value

        return None


    async def get_container_logs(
        self,
        container_id: str,
        tail: int,
    ) -> tuple[str | None, str]:
        async with httpx.AsyncClient(
            base_url="http://docker",
            transport=httpx.AsyncHTTPTransport(uds=self._socket_path),
            timeout=self._timeout_seconds,
        ) as client:
            inspect_data = await self._safe_inspect_container(client, container_id)
            container_name = None

            if inspect_data is not None:
                raw_name = inspect_data.get("Name")
                if isinstance(raw_name, str):
                    container_name = raw_name.lstrip("/")

            logs_bytes = await self._request_bytes(
                client=client,
                method="GET",
                path=f"/containers/{container_id}/logs",
                params={
                    "stdout": "true",
                    "stderr": "true",
                    "timestamps": "true",
                    "tail": str(tail),
                },
            )

        return container_name, self._decode_docker_logs(logs_bytes)

    def _decode_docker_logs(self, data: bytes) -> str:
        if not data:
            return ""

        frames: list[bytes] = []
        offset = 0
        parsed_any_frame = False

        while offset + 8 <= len(data):
            stream_type = data[offset]
            header_padding = data[offset + 1:offset + 4]
            frame_size = int.from_bytes(data[offset + 4:offset + 8], byteorder="big")

            if stream_type not in {0, 1, 2} or header_padding != b"\x00\x00\x00":
                break

            frame_start = offset + 8
            frame_end = frame_start + frame_size

            if frame_end > len(data):
                break

            frames.append(data[frame_start:frame_end])
            parsed_any_frame = True
            offset = frame_end

        if parsed_any_frame and offset == len(data):
            return b"".join(frames).decode("utf-8", errors="replace")

        # TTY-enabled containers return raw logs without Docker's 8-byte stream headers.
        return data.decode("utf-8", errors="replace")

    def _normalize_log_text(self, text: str) -> str:
        return text.replace("\r\n", "\n").replace("\r", "\n")

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        response = await client.request(
            method=method,
            url=path,
            params=params,
        )

        response.raise_for_status()
        if response.content:
            return response.json()

        return None


    async def _request_bytes(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> bytes:
        response = await client.request(
            method=method,
            url=path,
            params=params,
        )

        response.raise_for_status()
        return response.content
