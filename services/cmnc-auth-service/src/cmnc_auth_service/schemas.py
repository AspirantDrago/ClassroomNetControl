from pydantic import BaseModel


class HealthResponse(BaseModel):
    service: str
    status: str


class AuthUserResponse(BaseModel):
    user_id: int
    login: str
    role: str
    allowed_classroom_ids: list[int]


class ValidateTokenRequest(BaseModel):
    token: str | None = None


class ValidateTokenResponse(BaseModel):
    valid: bool
    user: AuthUserResponse
