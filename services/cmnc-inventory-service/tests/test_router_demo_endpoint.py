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
from cmnc_contracts.demo_endpoint import DemoEndpoint


@pytest.mark.parametrize('host,expected', [(None, None), (' ', None), (' 192.168.10.11 ', '192.168.10.11'),
    ('CMNC.EXAMPLE.LOCAL.', 'cmnc.example.local'), ('2001:db8::1', '2001:db8::1')])
def test_host_normalization(host, expected):
    assert RouterUpdate(veyon_demo_host=host).veyon_demo_host == expected


@pytest.mark.parametrize('host', ['http://cmnc.local', 'cmnc.local:11400', 'cmnc.local/path', 'user@host',
    'localhost', '0.0.0.0', '127.0.0.1', '224.0.0.1', 'bad host', '999.10.1.1', '-host.local'])
def test_bad_host_rejected(host):
    with pytest.raises(ValidationError): RouterUpdate(veyon_demo_host=host)
    with pytest.raises(ValidationError): DemoEndpoint(relay_host=host, relay_port=11400)


@pytest.mark.parametrize('port', [None, True, 0, -1, 65536, '11400', 11400.5])
def test_bad_port_rejected(port):
    with pytest.raises(ValidationError): RouterUpdate(veyon_demo_port=port)


def test_endpoint_persists_independently_and_updates_do_not_reset_port():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as conn: await conn.run_sync(Router.__table__.create)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                def create(name, **extra):
                    return RouterCreate(name=name, api_host='192.168.1.1', api_username='test', api_password='test-only', **extra)
                a = await create_router(create('One', veyon_demo_host='192.168.10.11', veyon_demo_port=21400), session)
                b = await create_router(create('Two'), session)
                assert b.veyon_demo_host is None and b.veyon_demo_port == 11400
                updated = await update_router(a.id, RouterUpdate(name='Renamed'), session)
                assert updated.veyon_demo_host == a.veyon_demo_host and updated.veyon_demo_port == 21400
                await update_router(b.id, RouterUpdate(veyon_demo_host='branch.local', veyon_demo_port=31400), session)
                cleared = await update_router(a.id, RouterUpdate(veyon_demo_host=None), session)
                assert cleared.veyon_demo_host is None and cleared.veyon_demo_port == 21400
                assert (await session.get(Router, b.id)).veyon_demo_host == 'branch.local'
        finally: await engine.dispose()
    asyncio.run(run())


def test_demo_endpoint_migration_preserves_routers():
    path = Path(__file__).parents[1]/'migrations/versions/20261117_0007_add_veyon_demo_endpoint.py'
    spec = importlib.util.spec_from_file_location('demo_endpoint_migration', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE routers (id INTEGER PRIMARY KEY)'))
        conn.execute(text('INSERT INTO routers VALUES (1)'))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
            assert conn.execute(text('SELECT veyon_demo_host, veyon_demo_port FROM routers')).one() == (None, 11400)
            migration.downgrade()
        assert conn.execute(text('SELECT id FROM routers')).scalar() == 1
    engine.dispose()
