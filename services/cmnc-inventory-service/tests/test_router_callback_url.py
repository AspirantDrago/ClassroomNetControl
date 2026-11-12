import asyncio
import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from alembic.migration import MigrationContext
from alembic.operations import Operations
from cmnc_inventory_service.models import Router
from cmnc_inventory_service.schemas import RouterCreate, RouterUpdate
from cmnc_inventory_service.main import create_router, update_router


@pytest.mark.parametrize("url,expected", [(None, None), ("", None), ("  ", None),
    (" https://cmnc.example.local/ ", "https://cmnc.example.local"),
    ("http://192.168.10.11:8081", "http://192.168.10.11:8081"),
    ("https://host/prefix/", "https://host/prefix")])
def test_callback_url_normalization(url, expected):
    assert RouterUpdate(veyon_callback_url=url).veyon_callback_url == expected


@pytest.mark.parametrize("url", ["ftp://host", "host", "https://user:pass@host", "http://host:99999",
    "http://host?token=secret", "https://host#fragment", "https://bad host"])
def test_invalid_callback_url_is_rejected(url):
    with pytest.raises(ValidationError): RouterUpdate(veyon_callback_url=url)


def test_router_callback_persists_and_can_be_cleared(tmp_path):
    async def run():
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Router.__table__.create)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                first = await create_router(RouterCreate(name="One", api_host="192.168.1.1", api_username="test",
                    api_password="test-only", veyon_callback_url="https://cmnc.one/"), session)
                second = await create_router(RouterCreate(name="Two", api_host="192.168.2.1", api_username="test",
                    api_password="test-only"), session)
                assert first.veyon_callback_url == "https://cmnc.one" and second.veyon_callback_url is None
                assert (await update_router(first.id, RouterUpdate(name="Renamed"), session)).veyon_callback_url == "https://cmnc.one"
                assert (await update_router(second.id, RouterUpdate(veyon_callback_url="https://cmnc.two"), session)).veyon_callback_url == "https://cmnc.two"
                assert (await update_router(first.id, RouterUpdate(veyon_callback_url=None), session)).veyon_callback_url is None
        finally: await engine.dispose()
    asyncio.run(run())


def test_callback_migration_preserves_router_data():
    path = Path(__file__).parents[1]/"migrations/versions/20261113_0006_add_veyon_callback_url.py"
    spec = importlib.util.spec_from_file_location("callback_migration", path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE routers (id INTEGER PRIMARY KEY)"))
        conn.execute(text("INSERT INTO routers VALUES (1)"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert conn.execute(text("SELECT veyon_callback_url FROM routers")).scalar() is None
            conn.execute(text("UPDATE routers SET veyon_callback_url='https://cmnc.local'"))
            migration.downgrade()
        assert conn.execute(text("SELECT id FROM routers")).scalar() == 1
    engine.dispose()
