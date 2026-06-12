from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    service: str
    status: str


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
