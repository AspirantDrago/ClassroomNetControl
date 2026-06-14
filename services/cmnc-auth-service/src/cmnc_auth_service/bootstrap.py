from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_auth_service.models import Role, User
from cmnc_auth_service.security import hash_password
from cmnc_auth_service.settings import settings


ROLE_SUPERADMIN = "superadmin"


async def ensure_bootstrap_superadmin(session: AsyncSession) -> None:
    users_count_result = await session.execute(
        select(func.count(User.id)),
    )
    users_count = int(users_count_result.scalar_one())

    if users_count > 0:
        return

    if settings.bootstrap_superadmin_password is None:
        raise RuntimeError(
            "No users found and CMNC_AUTH_BOOTSTRAP_SUPERADMIN_PASSWORD is not set"
        )

    role_result = await session.execute(
        select(Role).where(Role.name == ROLE_SUPERADMIN),
    )
    role = role_result.scalar_one_or_none()

    if role is None:
        raise RuntimeError("Role superadmin was not found")

    user = User(
        username=settings.bootstrap_superadmin_username,
        password_hash=hash_password(settings.bootstrap_superadmin_password),
        display_name=settings.bootstrap_superadmin_display_name,
        role_id=role.id,
        is_active=True,
    )

    session.add(user)
    await session.commit()
