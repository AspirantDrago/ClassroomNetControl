import asyncio
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from cmnc_classroom_service import api
from cmnc_classroom_service.db import Base
from cmnc_classroom_service.models import Classroom, Device
from cmnc_classroom_service.schemas import DeviceCreate, DeviceUpdate


def test_bulk_protection_defaults_and_persistence():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                session.add(Classroom(id=1, name='Room', subnet_cidr='192.168.1.0/24'))
                await session.commit()
                created = await api.create_device(DeviceCreate(classroom_id=1, mac_address='00:11:22:33:44:55', inventory_name='PC'), session)
                assert created.veyon_bulk_protected is False
                request = SimpleNamespace()
                updated = await api.update_device(created.id, DeviceUpdate(veyon_bulk_protected=True), request, session)
                assert updated.veyon_bulk_protected is True
                updated = await api.update_device(created.id, DeviceUpdate(inventory_name='Renamed'), request, session)
                assert updated.veyon_bulk_protected is True
                assert (await session.get(Device, created.id)).veyon_bulk_protected is True
                updated = await api.update_device(created.id, DeviceUpdate(veyon_bulk_protected=False), request, session)
                assert updated.veyon_bulk_protected is False
        finally:
            await engine.dispose()
    asyncio.run(run())


def test_bulk_protection_migration_preserves_existing_devices():
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / 'migrations/versions/20261108_0009_add_veyon_bulk_protection.py'
    spec = importlib.util.spec_from_file_location('bulk_protection_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE devices (id INTEGER PRIMARY KEY)'))
        connection.execute(text('INSERT INTO devices (id) VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text('SELECT veyon_bulk_protected FROM devices WHERE id=1')).scalar() == 0
            connection.execute(text('INSERT INTO devices (id) VALUES (2)'))
            assert connection.execute(text('SELECT veyon_bulk_protected FROM devices WHERE id=2')).scalar() == 0
            migration.downgrade()
        assert connection.execute(text('SELECT count(*) FROM devices')).scalar() == 2
    engine.dispose()
