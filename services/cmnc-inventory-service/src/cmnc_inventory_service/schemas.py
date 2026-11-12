from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class HealthResponse(BaseModel):
    service: str
    status: str


def normalize_callback_url(value):
    if value is None or not value.strip():
        return None
    from urllib.parse import urlsplit
    value = value.strip().rstrip("/")
    parsed = urlsplit(value)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Некорректный порт обратного подключения") from exc
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or any(char.isspace() for char in value)):
        raise ValueError("Укажите HTTP/HTTPS адрес CMNC без логина, пароля и параметров")
    return value


class RouterRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    api_host: str
    api_port: int
    api_use_ssl: bool
    api_verify_tls: bool
    veyon_callback_url: str | None = None
    api_username: str
    is_enabled: bool
    poll_enabled: bool
    sync_enabled: bool
    poll_interval_seconds: int
    created_at: datetime
    updated_at: datetime


class RouterConnectionRead(RouterRead):
    api_password: str


class RouterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    api_host: str = Field(min_length=1, max_length=255)
    api_port: int = Field(default=8728, ge=1, le=65535)
    api_use_ssl: bool = False
    api_verify_tls: bool = False
    api_username: str = Field(min_length=1, max_length=255)
    veyon_callback_url: str | None = Field(default=None, max_length=2048)
    _callback_url = field_validator("veyon_callback_url")(normalize_callback_url)
    api_password: str = Field(min_length=1, max_length=4096)
    is_enabled: bool = True
    poll_enabled: bool = True
    sync_enabled: bool = True
    poll_interval_seconds: int = Field(default=10, ge=1, le=3600)


class RouterUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    api_host: str | None = Field(default=None, min_length=1, max_length=255)
    api_port: int | None = Field(default=None, ge=1, le=65535)
    api_use_ssl: bool | None = None
    api_verify_tls: bool | None = None
    api_username: str | None = Field(default=None, min_length=1, max_length=255)
    veyon_callback_url: str | None = Field(default=None, max_length=2048)
    _callback_url = field_validator("veyon_callback_url")(normalize_callback_url)
    api_password: str | None = Field(default=None, min_length=1, max_length=4096)
    is_enabled: bool | None = None
    poll_enabled: bool | None = None
    sync_enabled: bool | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=1, le=3600)


RouterServiceName = Literal["mikrotik_poller", "policy_sync"]
RouterServiceStatusValue = Literal[
    "starting",
    "ok",
    "warning",
    "error",
    "stale",
    "disabled",
]


class RouterServiceStatusRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    router_id: int
    service_name: str
    worker_id: str | None
    status: str
    is_running: bool
    heartbeat_at: datetime | None
    last_started_at: datetime | None
    last_attempt_at: datetime | None
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    consecutive_failures: int
    details: dict[str, Any]
    updated_at: datetime


class RouterServiceStatusUpdate(BaseModel):
    service_name: RouterServiceName
    worker_id: str | None = Field(default=None, max_length=255)
    status: RouterServiceStatusValue
    is_running: bool = True
    heartbeat_at: datetime | None = None
    last_started_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int | None = Field(default=None, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class RouterStatusItem(BaseModel):
    router: RouterRead
    services: list[RouterServiceStatusRead]


class ObservedDeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    router_id: int
    mac_address: str
    active_ip: str | None
    hostname: str | None
    dynamic: bool | None
    active: bool
    raw: dict[str, Any]
    first_seen_at: datetime
    last_seen_at: datetime


class ObservedDevicesResponse(BaseModel):
    devices: list[ObservedDeviceRead]


class DeleteObservedDevicesRequest(BaseModel):
    ids: list[int] = Field(default_factory=list)


class DeleteObservedDevicesResponse(BaseModel):
    deleted_ids: list[int]
    deleted_count: int
