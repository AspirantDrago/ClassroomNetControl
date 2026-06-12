from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    service: str
    status: str


class ClassroomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subnet_cidr: str
    vlan_id: int | None
    display_order: int
    is_active: bool


class DeviceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    classroom_id: int
    mac_address: str
    inventory_name: str
    hostname: str | None
    static_ip: str | None
    row_index: int | None
    column_index: int | None
    is_pinned: bool
    wan_allowed: bool
    policy_generation: int
    sync_status: str
    sync_error: str | None


class ClassroomLayoutResponse(BaseModel):
    classroom: ClassroomRead
    devices: list[DeviceRead]


class WanPolicyChangeResponse(BaseModel):
    device_id: int
    wan_allowed: bool
    policy_generation: int
    sync_status: str


class DesiredBlocklistItem(BaseModel):
    device_id: int
    mac_address: str
    ip_address: str
    comment: str


class DesiredBlocklistResponse(BaseModel):
    router_id: int
    policy_generation: int
    address_list_name: str
    blocked: list[DesiredBlocklistItem]


class ErrorResponse(BaseModel):
    detail: str
