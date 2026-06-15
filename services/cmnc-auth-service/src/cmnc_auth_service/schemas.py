from datetime import datetime
from ipaddress import IPv4Address, IPv6Address

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    service: str
    status: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=255)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ResolvePrincipalRequest(BaseModel):
    bearer_token: str | None = None
    client_ip: str | None = None


class PrincipalResponse(BaseModel):
    principal_type: str
    id: int
    role: str
    display_name: str
    classroom_ids: list[int]
    permissions: list[str]


class ResolvePrincipalResponse(BaseModel):
    authenticated: bool
    principal: PrincipalResponse | None = None


class AccountUpdateRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1, max_length=255)


class RoleResponse(BaseModel):
    id: int
    name: str


class UserResponse(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    classroom_ids: list[int]
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None = None


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=255)
    display_name: str = Field(min_length=1, max_length=255)
    role: str = Field(min_length=1, max_length=32)
    is_active: bool = True
    classroom_ids: list[int] = Field(default_factory=list)


class UserUpdateRequest(BaseModel):
    username: str | None = Field(default=None, min_length=1, max_length=64)
    password: str | None = Field(default=None, min_length=1, max_length=255)
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: str | None = Field(default=None, min_length=1, max_length=32)
    is_active: bool | None = None


class PrincipalClassroomsUpdateRequest(BaseModel):
    classroom_ids: list[int] = Field(default_factory=list)


class WorkstationResponse(BaseModel):
    id: int
    name: str
    ip_address: IPv4Address | IPv6Address
    role: str
    is_active: bool
    classroom_ids: list[int]
    created_at: datetime
    updated_at: datetime
    last_seen_at: datetime | None = None


class WorkstationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    ip_address: IPv4Address | IPv6Address
    role: str = Field(default="workstation", min_length=1, max_length=32)
    is_active: bool = True
    classroom_ids: list[int] = Field(default_factory=list)


class WorkstationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    ip_address: IPv4Address | IPv6Address | None = None
    role: str | None = Field(default=None, min_length=1, max_length=32)
    is_active: bool | None = None
