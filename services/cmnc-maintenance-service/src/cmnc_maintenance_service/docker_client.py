import asyncio
import io
import json
import tarfile
from datetime import datetime, timezone
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
        async with self._create_client() as client:
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

    async def get_container_logs(
        self,
        container_id: str,
        tail: int,
    ) -> tuple[str | None, str]:
        async with self._create_client() as client:
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

    async def export_postgres_databases_backup(
        self,
        container_name: str,
        databases: list[str],
        user: str,
    ) -> bytes:
        if not databases:
            raise ValueError("Database list is empty")

        backup_files: dict[str, bytes] = {}

        for database in databases:
            self._validate_database_name(database)

            stdout, stderr, exit_code = await self._exec(
                container=container_name,
                cmd=["pg_dump", "-U", user, "-d", database, "-Fc"],
            )

            if exit_code != 0:
                raise RuntimeError(self._format_exec_error(f"pg_dump failed for {database}", stderr, exit_code))

            if not stdout:
                raise RuntimeError(f"pg_dump returned empty backup for {database}")

            backup_files[f"databases/{database}.backup"] = stdout

        manifest = {
            "format": "cmnc-postgres-backup",
            "version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "databases": [
                {
                    "name": database,
                    "file": f"databases/{database}.backup",
                }
                for database in databases
            ],
        }

        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tar:
            manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
            self._add_bytes_to_tar(tar, "manifest.json", manifest_bytes)

            for filename, content in backup_files.items():
                self._add_bytes_to_tar(tar, filename, content)

        return stream.getvalue()

    async def restore_postgres_databases_backup(
        self,
        container_name: str,
        databases: list[str],
        user: str,
        restore_dir: str,
        backup_archive_bytes: bytes,
    ) -> list[str]:
        if not backup_archive_bytes:
            raise ValueError("Backup archive is empty")

        if not databases:
            raise ValueError("Database list is empty")

        for database in databases:
            self._validate_database_name(database)

        backup_files = self._extract_database_backups_from_tar(backup_archive_bytes, databases)
        restored_databases: list[str] = []

        for database in databases:
            backup_bytes = backup_files.get(database)
            if not backup_bytes:
                raise ValueError(f"Backup archive does not contain database: {database}")

            restore_path = f"{restore_dir.rstrip('/')}/cmnc_restore_{database}.backup"
            archive_path, archive_bytes = self._build_tar_archive(
                restore_path=restore_path,
                backup_bytes=backup_bytes,
            )

            async with self._create_client(timeout_seconds=300.0) as client:
                await self._put_archive(
                    client=client,
                    container=container_name,
                    path=archive_path,
                    archive_bytes=archive_bytes,
                )

            try:
                stdout, stderr, exit_code = await self._exec(
                    container=container_name,
                    cmd=[
                        "pg_restore",
                        "-U",
                        user,
                        "-d",
                        database,
                        "--clean",
                        "--if-exists",
                        restore_path,
                    ],
                )

                if exit_code != 0:
                    combined_stderr = stderr or stdout
                    raise RuntimeError(
                        self._format_exec_error(
                            f"pg_restore failed for {database}",
                            combined_stderr,
                            exit_code,
                        )
                    )

                restored_databases.append(database)
            finally:
                await self._exec(
                    container=container_name,
                    cmd=["rm", "-f", restore_path],
                    raise_on_create_error=False,
                )

        return restored_databases

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

    async def _exec(
        self,
        container: str,
        cmd: list[str],
        raise_on_create_error: bool = True,
        timeout_seconds: float = 300.0,
    ) -> tuple[bytes, bytes, int | None]:
        async with self._create_client(timeout_seconds=timeout_seconds) as client:
            try:
                create_data = await self._request_json(
                    client=client,
                    method="POST",
                    path=f"/containers/{container}/exec",
                    json={
                        "AttachStdin": False,
                        "AttachStdout": True,
                        "AttachStderr": True,
                        "Tty": False,
                        "Cmd": cmd,
                    },
                )
            except Exception:
                if raise_on_create_error:
                    raise

                return b"", b"", None

            if not isinstance(create_data, dict) or not create_data.get("Id"):
                raise RuntimeError("Docker exec create response does not contain Id")

            exec_id = str(create_data["Id"])
            raw_output = await self._request_bytes(
                client=client,
                method="POST",
                path=f"/exec/{exec_id}/start",
                json={"Detach": False, "Tty": False},
            )
            inspect_data = await self._request_json(
                client=client,
                method="GET",
                path=f"/exec/{exec_id}/json",
            )

        exit_code = None
        if isinstance(inspect_data, dict):
            raw_exit_code = inspect_data.get("ExitCode")
            if isinstance(raw_exit_code, int):
                exit_code = raw_exit_code

        stdout, stderr = self._split_docker_stream(raw_output)
        return stdout, stderr, exit_code

    async def _put_archive(
        self,
        client: httpx.AsyncClient,
        container: str,
        path: str,
        archive_bytes: bytes,
    ) -> None:
        response = await client.put(
            url=f"/containers/{container}/archive",
            params={"path": path},
            content=archive_bytes,
            headers={"Content-Type": "application/x-tar"},
        )
        response.raise_for_status()

    def _extract_database_backups_from_tar(
        self,
        archive_bytes: bytes,
        allowed_databases: list[str],
    ) -> dict[str, bytes]:
        allowed = set(allowed_databases)
        result: dict[str, bytes] = {}

        try:
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:*") as tar:
                members = {member.name: member for member in tar.getmembers() if member.isfile()}

                manifest_member = members.get("manifest.json")
                if manifest_member is not None:
                    manifest_file = tar.extractfile(manifest_member)
                    if manifest_file is None:
                        raise ValueError("Backup manifest is unreadable")

                    manifest = json.loads(manifest_file.read().decode("utf-8"))
                    manifest_databases = manifest.get("databases")
                    if not isinstance(manifest_databases, list):
                        raise ValueError("Backup manifest does not contain databases list")

                    for item in manifest_databases:
                        if not isinstance(item, dict):
                            continue

                        name = item.get("name")
                        filename = item.get("file")

                        if not isinstance(name, str) or not isinstance(filename, str):
                            continue

                        if name not in allowed:
                            continue

                        self._validate_database_name(name)
                        self._validate_backup_member_name(filename)

                        member = members.get(filename)
                        if member is None:
                            raise ValueError(f"Backup file is missing from archive: {filename}")

                        extracted = tar.extractfile(member)
                        if extracted is None:
                            raise ValueError(f"Backup file is unreadable: {filename}")

                        result[name] = extracted.read()
                else:
                    for database in allowed_databases:
                        for filename in (f"databases/{database}.backup", f"{database}.backup"):
                            member = members.get(filename)
                            if member is None:
                                continue

                            extracted = tar.extractfile(member)
                            if extracted is None:
                                raise ValueError(f"Backup file is unreadable: {filename}")

                            result[database] = extracted.read()
                            break
        except tarfile.TarError as exc:
            raise ValueError(f"Invalid backup archive: {exc}") from exc

        return result

    def _add_bytes_to_tar(
        self,
        tar: tarfile.TarFile,
        filename: str,
        content: bytes,
    ) -> None:
        info = tarfile.TarInfo(name=filename)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))

    def _validate_database_name(self, database: str) -> None:
        if not database.replace("_", "").isalnum():
            raise ValueError(f"Invalid database name: {database}")

    def _validate_backup_member_name(self, filename: str) -> None:
        if filename.startswith("/") or ".." in filename.split("/"):
            raise ValueError(f"Invalid backup filename: {filename}")

    def _build_tar_archive(
        self,
        restore_path: str,
        backup_bytes: bytes,
    ) -> tuple[str, bytes]:
        normalized_path = restore_path.replace("\\", "/")
        archive_dir, _, filename = normalized_path.rpartition("/")

        if not archive_dir:
            archive_dir = "/"

        if not filename:
            raise ValueError("Restore path must contain filename")

        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w") as tar:
            info = tarfile.TarInfo(name=filename)
            info.size = len(backup_bytes)
            tar.addfile(info, io.BytesIO(backup_bytes))

        return archive_dir, stream.getvalue()

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

    def _decode_docker_logs(self, data: bytes) -> str:
        stdout, stderr = self._split_docker_stream(data)

        if stdout or stderr:
            return (stdout + stderr).decode("utf-8", errors="replace")

        return ""

    def _split_docker_stream(self, data: bytes) -> tuple[bytes, bytes]:
        if not data:
            return b"", b""

        stdout_frames: list[bytes] = []
        stderr_frames: list[bytes] = []
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

            frame = data[frame_start:frame_end]
            if stream_type == 2:
                stderr_frames.append(frame)
            else:
                stdout_frames.append(frame)

            parsed_any_frame = True
            offset = frame_end

        if parsed_any_frame and offset == len(data):
            return b"".join(stdout_frames), b"".join(stderr_frames)

        return data, b""

    def _format_exec_error(self, message: str, stderr: bytes, exit_code: int | None) -> str:
        decoded = stderr.decode("utf-8", errors="replace").strip()
        if decoded:
            return f"{message}: exit_code={exit_code}; {decoded}"

        return f"{message}: exit_code={exit_code}"

    def _as_float(self, value: Any) -> float | None:
        if isinstance(value, int | float):
            return float(value)

        return None

    def _as_int(self, value: Any) -> int | None:
        if isinstance(value, int):
            return value

        return None

    def _create_client(self, timeout_seconds: float | None = None) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url="http://docker",
            transport=httpx.AsyncHTTPTransport(uds=self._socket_path),
            timeout=timeout_seconds if timeout_seconds is not None else self._timeout_seconds,
        )

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        response = await client.request(
            method=method,
            url=path,
            params=params,
            json=json,
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
        json: dict[str, Any] | None = None,
    ) -> bytes:
        response = await client.request(
            method=method,
            url=path,
            params=params,
            json=json,
        )

        response.raise_for_status()
        return response.content
