import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from cmnc_classroom_service.db import Base
from cmnc_classroom_service.device_state_timing import get_device_state_times
from cmnc_classroom_service.models import DeviceStatisticsEvent, DeviceStatisticsState


def test_independent_state_start_times():
    async def run():
        engine = create_async_engine('sqlite+aiosqlite:///:memory:')
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            start = datetime(2026, 11, 1, tzinfo=timezone.utc)
            async with AsyncSession(engine) as session:
                for device_id, history in {
                    1: [(0, True, 'allowed'), (2, True, 'blocked'), (3, True, 'allowed'), (4, False, 'allowed'), (5, False, 'allowed')],
                    2: [(0, False, 'blocked'), (1, False, 'allowed'), (2, True, 'allowed'), (2, False, 'allowed')],
                    3: [(0, False, 'blocked')],
                }.items():
                    for hours, online, wan in history:
                        session.add(DeviceStatisticsEvent(device_id=device_id, occurred_at=start+timedelta(hours=hours), online=online, wan_state=wan))
                    last = history[-1]
                    session.add(DeviceStatisticsState(device_id=device_id, online=last[1], wan_state=last[2], observed_at=start+timedelta(hours=last[0])))
                # Existing state without recorded history must not invent a start time.
                session.add(DeviceStatisticsState(device_id=4, online=True, wan_state='protected', observed_at=start))
                await session.commit()
                result = await get_device_state_times(session, [1, 2, 3, 4, 5])
                assert result[1].online_state_since.replace(tzinfo=timezone.utc) == start+timedelta(hours=4)
                assert result[1].wan_state_since.replace(tzinfo=timezone.utc) == start+timedelta(hours=3)
                assert result[2].online_state_since.replace(tzinfo=timezone.utc) == start+timedelta(hours=2)
                assert result[2].wan_state_since.replace(tzinfo=timezone.utc) == start+timedelta(hours=1)
                assert result[3].online_state_since.replace(tzinfo=timezone.utc) == start
                assert result[3].wan_state_since.replace(tzinfo=timezone.utc) == start
                assert result[4].online_state_since is None
                assert result[4].wan_state_since is None
                assert 5 not in result
                assert await get_device_state_times(session, []) == {}
        finally:
            await engine.dispose()
    asyncio.run(run())
