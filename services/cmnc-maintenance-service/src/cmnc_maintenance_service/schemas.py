from datetime import datetime

from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: str
    status: str


class ContainerStatus(BaseModel):
    id: str
    name: str
    image: str
    state: str
    state_label: str
    health: str | None = None
    docker_status: str
    cpu_percent: float | None = None
    memory_usage_bytes: int | None = None
    memory_limit_bytes: int | None = None
    memory_percent: float | None = None
    started_at: datetime | None = None


class ContainersStatusResponse(BaseModel):
    containers: list[ContainerStatus]


class ContainerLogsResponse(BaseModel):
    container_id: str
    container_name: str | None = None
    tail: int
    logs: str


class DatabaseRestoreResponse(BaseModel):
    restored: bool
    filename: str
    size_bytes: int
    databases: list[str]
