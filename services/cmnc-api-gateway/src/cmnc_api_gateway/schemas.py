from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    service: str
    status: str


class AuthUserResponse(BaseModel):
    user_id: int
    login: str
    role: str
    allowed_classroom_ids: list[int]


class DashboardDevice(BaseModel):
    id: int
    classroom_id: int
    mac_address: str
    inventory_name: str
    hostname: str | None
    static_ip: str | None
    active_ip: str | None = None
    observed_hostname: str | None = None
    row_index: int | None
    column_index: int | None
    is_pinned: bool
    wan_allowed: bool
    policy_generation: int
    sync_status: str
    sync_error: str | None
    online: bool = False
    last_seen_at: datetime | None = None


class DynamicDevice(BaseModel):
    router_id: int
    mac_address: str
    active_ip: str | None
    hostname: str | None
    dynamic: bool | None
    active: bool
    last_seen_at: datetime | None
    raw: dict[str, Any]


class ClassroomDashboardResponse(BaseModel):
    classroom: dict[str, Any]
    devices: list[DashboardDevice]
    dynamic_devices: list[DynamicDevice]


class PinObservedDeviceRequest(BaseModel):
    mac_address: str = Field(min_length=1, max_length=32)
    inventory_name: str | None = Field(default=None, min_length=1, max_length=255)
    row_index: int | None = None
    column_index: int | None = None
    hostname: str | None = None
