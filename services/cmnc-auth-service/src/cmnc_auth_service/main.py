from contextlib import asynccontextmanager
from datetime import datetime, timezone
from ipaddress import IPv4Address, IPv6Address
from typing import Iterable

from fastapi import Depends, FastAPI, HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cmnc_auth_service.bootstrap import ensure_bootstrap_superadmin
from cmnc_auth_service.db import async_session_maker, get_session
from cmnc_auth_service.models import ClassroomAccess, Role, User, Workstation
from cmnc_auth_service.schemas import (
    HealthResponse,
    LoginRequest,
    PrincipalClassroomsUpdateRequest,
    PrincipalResponse,
    ResolvePrincipalRequest,
    ResolvePrincipalResponse,
    RoleResponse,
    TokenResponse,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
    WorkstationCreateRequest,
    WorkstationResponse,
    WorkstationUpdateRequest,
)
from cmnc_auth_service.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
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


@app.get("/internal/admin/roles", response_model=list[RoleResponse])
async def list_roles(
    session: AsyncSession = Depends(get_session),
) -> list[RoleResponse]:
    result = await session.execute(select(Role).order_by(Role.name))
    return [RoleResponse(id=role.id, name=role.name) for role in result.scalars().all()]


@app.get("/internal/admin/users", response_model=list[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_session),
) -> list[UserResponse]:
    result = await session.execute(
        select(User)
        .options(selectinload(User.role))
        .order_by(User.username)
    )
    users = list(result.scalars().all())

    return [await build_user_response(user, session) for user in users]


@app.get("/internal/admin/users/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user = await load_user_or_404(user_id, session)
    return await build_user_response(user, session)


@app.post("/internal/admin/users", response_model=UserResponse)
async def create_user(
    payload: UserCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    role = await load_role_or_404(payload.role, session)

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role_id=role.id,
        is_active=payload.is_active,
    )

    session.add(user)

    try:
        await session.flush()
        await replace_user_classroom_access(user.id, payload.classroom_ids, session)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="User with this username already exists or classroom access is duplicated",
        ) from exc

    user = await load_user_or_404(user.id, session)
    return await build_user_response(user, session)


@app.patch("/internal/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    payload: UserUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user = await load_user_or_404(user_id, session)

    if payload.username is not None:
        user.username = payload.username

    if payload.password is not None:
        user.password_hash = hash_password(payload.password)

    if payload.display_name is not None:
        user.display_name = payload.display_name

    if payload.role is not None:
        role = await load_role_or_404(payload.role, session)
        user.role_id = role.id

    if payload.is_active is not None:
        user.is_active = payload.is_active

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="User with this username already exists",
        ) from exc

    user = await load_user_or_404(user_id, session)
    return await build_user_response(user, session)


@app.post("/internal/admin/users/{user_id}/classrooms", response_model=UserResponse)
async def update_user_classrooms(
    user_id: int,
    payload: PrincipalClassroomsUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> UserResponse:
    user = await load_user_or_404(user_id, session)

    try:
        await replace_user_classroom_access(user.id, payload.classroom_ids, session)
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Classroom access is duplicated",
        ) from exc

    user = await load_user_or_404(user_id, session)
    return await build_user_response(user, session)


@app.get("/internal/admin/workstations", response_model=list[WorkstationResponse])
async def list_workstations(
    session: AsyncSession = Depends(get_session),
) -> list[WorkstationResponse]:
    result = await session.execute(
        select(Workstation)
        .options(selectinload(Workstation.role))
        .order_by(Workstation.name)
    )
    workstations = list(result.scalars().all())

    return [await build_workstation_response(workstation, session) for workstation in workstations]


@app.get("/internal/admin/workstations/{workstation_id}", response_model=WorkstationResponse)
async def get_workstation(
    workstation_id: int,
    session: AsyncSession = Depends(get_session),
) -> WorkstationResponse:
    workstation = await load_workstation_or_404(workstation_id, session)
    return await build_workstation_response(workstation, session)


@app.post("/internal/admin/workstations", response_model=WorkstationResponse)
async def create_workstation(
    payload: WorkstationCreateRequest,
    session: AsyncSession = Depends(get_session),
) -> WorkstationResponse:
    role = await load_role_or_404(payload.role, session)

    workstation = Workstation(
        name=payload.name,
        ip_address=payload.ip_address,
        role_id=role.id,
        is_active=payload.is_active,
    )

    session.add(workstation)

    try:
        await session.flush()
        await replace_workstation_classroom_access(
            workstation.id,
            payload.classroom_ids,
            session,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Workstation with this IP address already exists or classroom access is duplicated",
        ) from exc

    workstation = await load_workstation_or_404(workstation.id, session)
    return await build_workstation_response(workstation, session)


@app.patch("/internal/admin/workstations/{workstation_id}", response_model=WorkstationResponse)
async def update_workstation(
    workstation_id: int,
    payload: WorkstationUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> WorkstationResponse:
    workstation = await load_workstation_or_404(workstation_id, session)

    if payload.name is not None:
        workstation.name = payload.name

    if payload.ip_address is not None:
        workstation.ip_address = payload.ip_address

    if payload.role is not None:
        role = await load_role_or_404(payload.role, session)
        workstation.role_id = role.id

    if payload.is_active is not None:
        workstation.is_active = payload.is_active

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Workstation with this IP address already exists",
        ) from exc

    workstation = await load_workstation_or_404(workstation_id, session)
    return await build_workstation_response(workstation, session)


@app.post(
    "/internal/admin/workstations/{workstation_id}/classrooms",
    response_model=WorkstationResponse,
)
async def update_workstation_classrooms(
    workstation_id: int,
    payload: PrincipalClassroomsUpdateRequest,
    session: AsyncSession = Depends(get_session),
) -> WorkstationResponse:
    workstation = await load_workstation_or_404(workstation_id, session)

    try:
        await replace_workstation_classroom_access(
            workstation.id,
            payload.classroom_ids,
            session,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=409,
            detail="Classroom access is duplicated",
        ) from exc

    workstation = await load_workstation_or_404(workstation_id, session)
    return await build_workstation_response(workstation, session)


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


async def load_role_or_404(
    role_name: str,
    session: AsyncSession,
) -> Role:
    result = await session.execute(select(Role).where(Role.name == role_name))
    role = result.scalar_one_or_none()

    if role is None:
        raise HTTPException(status_code=404, detail="Role not found")

    return role


async def load_user_or_404(
    user_id: int,
    session: AsyncSession,
) -> User:
    result = await session.execute(
        select(User)
        .options(selectinload(User.role))
        .where(User.id == user_id)
    )
    user = result.scalar_one_or_none()

    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    return user


async def load_workstation_or_404(
    workstation_id: int,
    session: AsyncSession,
) -> Workstation:
    result = await session.execute(
        select(Workstation)
        .options(selectinload(Workstation.role))
        .where(Workstation.id == workstation_id)
    )
    workstation = result.scalar_one_or_none()

    if workstation is None:
        raise HTTPException(status_code=404, detail="Workstation not found")

    return workstation


async def replace_user_classroom_access(
    user_id: int,
    classroom_ids: Iterable[int],
    session: AsyncSession,
) -> None:
    unique_classroom_ids = sorted(set(classroom_ids))

    await session.execute(
        delete(ClassroomAccess).where(ClassroomAccess.user_id == user_id)
    )

    for classroom_id in unique_classroom_ids:
        session.add(
            ClassroomAccess(
                user_id=user_id,
                classroom_id=classroom_id,
            )
        )


async def replace_workstation_classroom_access(
    workstation_id: int,
    classroom_ids: Iterable[int],
    session: AsyncSession,
) -> None:
    unique_classroom_ids = sorted(set(classroom_ids))

    await session.execute(
        delete(ClassroomAccess).where(ClassroomAccess.workstation_id == workstation_id)
    )

    for classroom_id in unique_classroom_ids:
        session.add(
            ClassroomAccess(
                workstation_id=workstation_id,
                classroom_id=classroom_id,
            )
        )


async def build_user_response(
    user: User,
    session: AsyncSession,
) -> UserResponse:
    classroom_ids = await get_user_classroom_ids(
        user_id=user.id,
        role=user.role,
        session=session,
    )

    return UserResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role.name,
        is_active=user.is_active,
        classroom_ids=classroom_ids,
        created_at=user.created_at,
        updated_at=user.updated_at,
        last_login_at=user.last_login_at,
    )


async def build_workstation_response(
    workstation: Workstation,
    session: AsyncSession,
) -> WorkstationResponse:
    classroom_ids = await get_workstation_classroom_ids(
        workstation_id=workstation.id,
        session=session,
    )

    return WorkstationResponse(
        id=workstation.id,
        name=workstation.name,
        ip_address=workstation.ip_address,
        role=workstation.role.name,
        is_active=workstation.is_active,
        classroom_ids=classroom_ids,
        created_at=workstation.created_at,
        updated_at=workstation.updated_at,
        last_seen_at=workstation.last_seen_at,
    )
