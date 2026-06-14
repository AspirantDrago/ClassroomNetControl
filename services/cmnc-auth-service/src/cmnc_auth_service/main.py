from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cmnc_auth_service.bootstrap import ensure_bootstrap_superadmin
from cmnc_auth_service.db import async_session_maker, get_session
from cmnc_auth_service.models import ClassroomAccess, Role, User, Workstation
from cmnc_auth_service.schemas import (
    HealthResponse,
    LoginRequest,
    PrincipalResponse,
    ResolvePrincipalRequest,
    ResolvePrincipalResponse,
    TokenResponse,
)
from cmnc_auth_service.security import (
    create_access_token,
    decode_access_token,
    verify_password,
)
from cmnc_auth_service.settings import settings
from cmnc_contracts.permissions import get_permissions_for_role


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with async_session_maker() as session:
        await ensure_bootstrap_superadmin(session)

    yield


app = FastAPI(
    title="cmnc-auth-service",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        service="cmnc-auth-service",
        status="ok",
    )


@app.post("/internal/auth/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    result = await session.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.username == payload.username)
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    if not verify_password(payload.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    user.last_login_at = datetime.now(timezone.utc)
    await session.commit()

    token = create_access_token(
        user_id=user.id,
        username=user.username,
        role_name=user.role.name,
    )

    return TokenResponse(access_token=token)


@app.post(
    "/internal/auth/resolve-principal",
    response_model=ResolvePrincipalResponse,
)
async def resolve_principal(
    payload: ResolvePrincipalRequest,
    session: AsyncSession = Depends(get_session),
) -> ResolvePrincipalResponse:
    if payload.bearer_token:
        principal = await resolve_user_by_token(
            token=payload.bearer_token,
            session=session,
        )

        if principal is not None:
            return ResolvePrincipalResponse(
                authenticated=True,
                principal=principal,
            )

    if payload.client_ip:
        principal = await resolve_workstation_by_ip(
            client_ip=payload.client_ip,
            session=session,
        )

        if principal is not None:
            return ResolvePrincipalResponse(
                authenticated=True,
                principal=principal,
            )

    return ResolvePrincipalResponse(
        authenticated=False,
        principal=None,
    )


async def resolve_user_by_token(
    token: str,
    session: AsyncSession,
) -> PrincipalResponse | None:
    try:
        token_payload = decode_access_token(token)
    except InvalidTokenError:
        return None

    user_id_raw = token_payload.get("sub")

    if not isinstance(user_id_raw, str) or not user_id_raw.isdigit():
        return None

    result = await session.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.id == int(user_id_raw))
    )
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        return None

    classroom_ids = await get_user_classroom_ids(
        user_id=user.id,
        role=user.role,
        session=session,
    )

    return PrincipalResponse(
        principal_type="user",
        id=user.id,
        role=user.role.name,
        display_name=user.display_name,
        classroom_ids=classroom_ids,
        permissions=get_permissions_for_role(user.role.name),
    )


async def resolve_workstation_by_ip(
    client_ip: str,
    session: AsyncSession,
) -> PrincipalResponse | None:
    result = await session.execute(
        select(Workstation)
        .options(selectinload(Workstation.role))
        .where(Workstation.ip_address == client_ip)
    )
    workstation = result.scalar_one_or_none()

    if workstation is None or not workstation.is_active:
        return None

    workstation.last_seen_at = datetime.now(timezone.utc)
    await session.commit()

    classroom_ids = await get_workstation_classroom_ids(
        workstation_id=workstation.id,
        session=session,
    )

    return PrincipalResponse(
        principal_type="workstation",
        id=workstation.id,
        role=workstation.role.name,
        display_name=workstation.name,
        classroom_ids=classroom_ids,
        permissions=get_permissions_for_role(workstation.role.name),
    )


async def get_user_classroom_ids(
    user_id: int,
    role: Role,
    session: AsyncSession,
) -> list[int]:
    if role.name in {"superadmin", "admin", "moderator"}:
        return []

    result = await session.execute(
        select(ClassroomAccess.classroom_id)
        .where(ClassroomAccess.user_id == user_id)
        .order_by(ClassroomAccess.classroom_id)
    )

    return list(result.scalars().all())


async def get_workstation_classroom_ids(
    workstation_id: int,
    session: AsyncSession,
) -> list[int]:
    result = await session.execute(
        select(ClassroomAccess.classroom_id)
        .where(ClassroomAccess.workstation_id == workstation_id)
        .order_by(ClassroomAccess.classroom_id)
    )

    return list(result.scalars().all())
