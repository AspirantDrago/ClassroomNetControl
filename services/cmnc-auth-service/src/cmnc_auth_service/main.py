import uvicorn
from fastapi import FastAPI

from cmnc_auth_service.schemas import (
    AuthUserResponse,
    HealthResponse,
    ValidateTokenRequest,
    ValidateTokenResponse,
)
from cmnc_auth_service.settings import settings

app = FastAPI(title=settings.service_name)


def get_stub_user() -> AuthUserResponse:
    return AuthUserResponse(
        user_id=settings.stub_user_id,
        login=settings.stub_login,
        role=settings.stub_role,
        allowed_classroom_ids=list(range(256)),
    )


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service=settings.service_name,
        status="ok",
    )


@app.get("/internal/auth/me", response_model=AuthUserResponse)
async def get_current_user() -> AuthUserResponse:
    return get_stub_user()


@app.post("/internal/auth/validate-token", response_model=ValidateTokenResponse)
async def validate_token(_: ValidateTokenRequest) -> ValidateTokenResponse:
    return ValidateTokenResponse(
        valid=True,
        user=get_stub_user(),
    )


def run() -> None:
    uvicorn.run(
        settings.service_name,
        host=settings.host,
        port=settings.port,
        reload=settings.reload,
        workers=1,
    )


if __name__ == "__main__":
    run()
