from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_classroom_service.models import DeviceStatisticsEvent, DeviceStatisticsState
from cmnc_classroom_service.schemas import DeviceStateTiming


async def get_device_state_times(
    session: AsyncSession,
    device_ids: list[int],
) -> dict[int, DeviceStateTiming]:
    if not device_ids:
        return {}

    # Events contain both states. A WAN change must not reset online duration,
    # and an online change must not reset WAN duration.
    event = DeviceStatisticsEvent
    ordering = [event.occurred_at, event.id]
    history = select(
        event.device_id,
        event.occurred_at,
        event.online,
        event.wan_state,
        func.lag(event.online).over(
            partition_by=event.device_id, order_by=ordering,
        ).label("previous_online"),
        func.lag(event.wan_state).over(
            partition_by=event.device_id, order_by=ordering,
        ).label("previous_wan_state"),
    ).where(event.device_id.in_(device_ids)).subquery()

    transitions = select(
        history.c.device_id,
        func.max(case((
            history.c.online.is_distinct_from(history.c.previous_online),
            history.c.occurred_at,
        ))).label("online_state_since"),
        func.max(case((
            history.c.wan_state.is_distinct_from(history.c.previous_wan_state),
            history.c.occurred_at,
        ))).label("wan_state_since"),
    ).group_by(history.c.device_id).subquery()

    state = DeviceStatisticsState
    result = await session.execute(
        select(
            state.device_id, state.online, state.wan_state,
            transitions.c.online_state_since, transitions.c.wan_state_since,
        ).outerjoin(transitions, transitions.c.device_id == state.device_id)
        .where(state.device_id.in_(device_ids))
    )
    return {
        row.device_id: DeviceStateTiming(
            online=row.online,
            wan_state=row.wan_state,
            online_state_since=row.online_state_since,
            wan_state_since=row.wan_state_since,
        )
        for row in result
    }
