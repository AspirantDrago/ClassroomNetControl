from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


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
    is_service: bool


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
    wan_protected: bool
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


class BulkWanPolicyChangeResponse(BaseModel):
    classroom_id: int
    wan_allowed: bool
    affected_count: int
    changed_count: int
    queued_count: int
    device_ids: list[int]
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


class ClassroomCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    subnet_cidr: str = Field(min_length=1, max_length=64)
    vlan_id: int | None = None
    display_order: int = 0
    is_active: bool = True
    is_service: bool = False


class ClassroomUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    subnet_cidr: str | None = Field(default=None, min_length=1, max_length=64)
    vlan_id: int | None = None
    display_order: int | None = None
    is_active: bool | None = None
    is_service: bool | None = None


class DeviceCreate(BaseModel):
    classroom_id: int
    mac_address: str = Field(min_length=1, max_length=32)
    inventory_name: str = Field(min_length=1, max_length=255)
    hostname: str | None = None
    static_ip: str | None = None
    row_index: int | None = None
    column_index: int | None = None
    is_pinned: bool = True
    wan_allowed: bool = True
    wan_protected: bool = False


class DeviceUpdate(BaseModel):
    classroom_id: int | None = None
    mac_address: str | None = Field(default=None, min_length=1, max_length=32)
    inventory_name: str | None = Field(default=None, min_length=1, max_length=255)
    hostname: str | None = None
    static_ip: str | None = None
    row_index: int | None = None
    column_index: int | None = None
    is_pinned: bool | None = None
    wan_protected: bool | None = None


class DevicePinRequest(BaseModel):
    classroom_id: int
    inventory_name: str = Field(min_length=1, max_length=255)
    static_ip: str | None = None
    row_index: int | None = None
    column_index: int | None = None
    hostname: str | None = None