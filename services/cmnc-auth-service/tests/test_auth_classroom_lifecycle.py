import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from cmnc_auth_service import classroom_lifecycle as lifecycle
from cmnc_auth_service import main
from cmnc_auth_service.models import ClassroomAccess, ClassroomDeletionGuard


@asynccontextmanager
async def database(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # The two tables needed here have no PostgreSQL-specific types.
        await conn.run_sync(lambda c: ClassroomAccess.__table__.create(c))
        await conn.run_sync(lambda c: ClassroomDeletionGuard.__table__.create(c))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(lifecycle, "async_session_maker", factory)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.mark.parametrize("principal", ["user", "workstation"])
def test_existing_assignments_block_delete(monkeypatch, principal):
    async def run():
        async with database(monkeypatch) as factory:
            async with factory() as session:
                session.add(ClassroomAccess(classroom_id=7, **{principal+"_id": 1}))
                await session.commit()
                request = AsyncMock()
                monkeypatch.setattr(lifecycle, "classroom_request", request)
                with pytest.raises(HTTPException) as exc:
                    await lifecycle.delete_classroom(7, session)
                assert exc.value.status_code == 409
                request.assert_not_awaited()
                assert await session.get(ClassroomDeletionGuard, 7) is None
    asyncio.run(run())


@pytest.mark.parametrize("status", [200, 404, 409, 422, 503, 500])
def test_reservation_survives_success_and_ambiguous_failure(monkeypatch, status):
    async def run():
        async with database(monkeypatch) as factory:
            request = AsyncMock(return_value={"deleted": True})
            if status != 200:
                request.side_effect = HTTPException(status, "Аудитория не найдена" if status == 404 else "Rejected")
            monkeypatch.setattr(lifecycle, "classroom_request", request)
            async with factory() as session:
                if status in (200, 404):
                    assert await lifecycle.delete_classroom(7, session) == {"deleted": True}
                else:
                    with pytest.raises(HTTPException):
                        await lifecycle.delete_classroom(7, session)
                guard = await session.get(ClassroomDeletionGuard, 7)
                assert (guard is not None) == (status not in (409, 422))
                if guard:
                    await lifecycle.verify_deletion(7, lifecycle.DeletionToken(token=guard.token), session)
                    with pytest.raises(HTTPException):
                        await lifecycle.verify_deletion(7, lifecycle.DeletionToken(token="stale"), session)
    asyncio.run(run())


@pytest.mark.parametrize("principal", ["user", "workstation"])
def test_deleted_classroom_cannot_be_assigned_and_failure_preserves_old_grants(monkeypatch, principal):
    async def run():
        async with database(monkeypatch) as factory:
            async with factory() as session:
                session.add(ClassroomAccess(classroom_id=8, **{principal+"_id": 1}))
                session.add(ClassroomDeletionGuard(classroom_id=7, token="old"))
                await session.commit()
                replace = main.replace_user_classroom_access if principal == "user" else main.replace_workstation_classroom_access
                with pytest.raises(HTTPException):
                    await replace(1, [7], session)
                assert (await session.execute(select(ClassroomAccess.classroom_id))).scalar_one() == 8
                await replace(1, [8, 8, 9], session)
                await session.commit()
                assert list((await session.execute(select(ClassroomAccess.classroom_id).order_by(ClassroomAccess.classroom_id))).scalars()) == [8, 9]
    asyncio.run(run())


def test_retry_invalidates_old_token_and_activation_clears_reservation(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory:
            await lifecycle.reserve(7, "old")
            monkeypatch.setattr(lifecycle, "classroom_request", AsyncMock(return_value={"deleted": True}))
            async with factory() as session:
                await lifecycle.delete_classroom(7, session)
                guard = await session.get(ClassroomDeletionGuard, 7)
                assert guard.token != "old"
                with pytest.raises(HTTPException):
                    await lifecycle.verify_deletion(7, lifecycle.DeletionToken(token="old"), session)
                await session.rollback()
                monkeypatch.setattr(lifecycle, "classroom_request", AsyncMock(return_value={"is_active": True}))
                assert await lifecycle.activate_classroom(7, {}, session) == {"is_active": True}
                await session.rollback()
                assert await session.get(ClassroomDeletionGuard, 7) is None
    asyncio.run(run())


def test_failed_activation_keeps_guard(monkeypatch):
    async def run():
        async with database(monkeypatch) as factory:
            await lifecycle.reserve(7, "old")
            monkeypatch.setattr(lifecycle, "classroom_request", AsyncMock(side_effect=HTTPException(404, "Missing")))
            async with factory() as session:
                with pytest.raises(HTTPException):
                    await lifecycle.activate_classroom(7, {}, session)
                assert (await session.get(ClassroomDeletionGuard, 7)).token == "old"
    asyncio.run(run())


def test_migration_preserves_existing_assignments():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text
    path = Path(__file__).parents[1] / "migrations/versions/20261113_0004_classroom_deletion_guards.py"
    spec = importlib.util.spec_from_file_location("deletion_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE classroom_access (id INTEGER PRIMARY KEY, classroom_id INTEGER)"))
            connection.execute(text("INSERT INTO classroom_access VALUES (1, 7)"))
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                assert connection.execute(text("SELECT count(*) FROM classroom_deletion_guards")).scalar() == 0
                migration.downgrade()
            assert connection.execute(text("SELECT classroom_id FROM classroom_access")).scalar() == 7
    finally:
        engine.dispose()
