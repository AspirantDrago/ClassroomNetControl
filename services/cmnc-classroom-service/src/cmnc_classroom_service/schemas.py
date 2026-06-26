from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    service: str
    status: str


class ClassroomRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    router_id: int
    name: str
    subnet_cidr: str
    vlan_id: int | None
    display_order: int
    is_active: bool
    is_service: bool


class ClassroomCameraRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    classroom_id: int
    name: str
    sort_order: int
    is_enabled: bool
    rtsp_main_stream: str | None
    rtsp_sub_stream: str | None
    default_quality: str


class ClassroomCameraCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    sort_order: int = 0
    is_enabled: bool = True
    rtsp_main_stream: str | None = Field(default=None, max_length=4096)
    rtsp_sub_stream: str | None = Field(default=None, max_length=4096)
    default_quality: str = Field(default="sub", pattern="^(main|sub)$")


class ClassroomCameraUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sort_order: int | None = None
    is_enabled: bool | None = None
    rtsp_main_stream: str | None = Field(default=None, max_length=4096)
    rtsp_sub_stream: str | None = Field(default=None, max_length=4096)
    default_quality: str | None = Field(default=None, pattern="^(main|sub)$")


class ClassroomCameraSourceResponse(BaseModel):
    camera_id: int
    classroom_id: int
    quality: str
    rtsp_url: str


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
    cameras: list[ClassroomCameraRead]


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
    router_id: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=255)
    subnet_cidr: str = Field(min_length=1, max_length=64)
    vlan_id: int | None = None
    display_order: int = 0
    is_active: bool = True
    is_service: bool = False


class ClassroomUpdate(BaseModel):
    router_id: int | None = Field(default=None, ge=1)
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
    wan_protected: bool = False
