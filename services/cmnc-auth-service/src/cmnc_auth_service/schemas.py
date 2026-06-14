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
