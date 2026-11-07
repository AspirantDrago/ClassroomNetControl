import asyncio
import pytest
from types import SimpleNamespace
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from cmnc_classroom_service import api
from cmnc_classroom_service.db import Base
from cmnc_classroom_service.models import Classroom, Device
from cmnc_classroom_service.schemas import DeviceCreate, DeviceUpdate


@pytest.mark.parametrize("field", ["veyon_bulk_protected", "wol_protected"])
def test_bulk_protection_defaults_and_persistence(field):
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            async with AsyncSession(engine, expire_on_commit=False) as session:
                session.add(Classroom(id=1, name='Room', subnet_cidr='192.168.1.0/24'))
                await session.commit()
                created = await api.create_device(DeviceCreate(classroom_id=1, mac_address='00:11:22:33:44:55', inventory_name='PC'), session)
                assert getattr(created, field) is False
                request = SimpleNamespace()
                updated = await api.update_device(created.id, DeviceUpdate(**{field: True}), request, session)
                assert getattr(updated, field) is True
                updated = await api.update_device(created.id, DeviceUpdate(inventory_name='Renamed'), request, session)
                assert getattr(updated, field) is True
                assert getattr(await session.get(Device, created.id), field) is True
                updated = await api.update_device(created.id, DeviceUpdate(**{field: False}), request, session)
                assert getattr(updated, field) is False
        finally:
            await engine.dispose()
    asyncio.run(run())


@pytest.mark.parametrize("filename,field", [
    ("20261108_0009_add_veyon_bulk_protection.py", "veyon_bulk_protected"),
    ("20261108_0010_add_wol_protection.py", "wol_protected"),
])
def test_bulk_protection_migration_preserves_existing_devices(filename, field):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = Path(__file__).parents[1] / 'migrations/versions' / filename
    spec = importlib.util.spec_from_file_location('bulk_protection_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///:memory:')
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE devices (id INTEGER PRIMARY KEY)'))
        connection.execute(text('INSERT INTO devices (id) VALUES (1)'))
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
            assert connection.execute(text(f'SELECT {field} FROM devices WHERE id=1')).scalar() == 0
            connection.execute(text('INSERT INTO devices (id) VALUES (2)'))
            assert connection.execute(text(f'SELECT {field} FROM devices WHERE id=2')).scalar() == 0
            migration.downgrade()
        assert connection.execute(text('SELECT count(*) FROM devices')).scalar() == 2
    engine.dispose()
