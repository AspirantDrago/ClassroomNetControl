from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from typing import Callable, Iterable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_classroom_service.db import get_session
from cmnc_classroom_service.models import (
    Classroom,
    Device,
    DeviceStatisticsEvent,
    DeviceStatisticsState,
    DeviceUserInterval,
)


DEFAULT_STATISTICS_RANGE_MINUTES = 24 * 60
ALLOWED_STATISTICS_RANGE_MINUTES = frozenset(
    {
        40,
        4 * 60,
        24 * 60,
        7 * 24 * 60,
    }
)

router = APIRouter()


class StatisticsSegment(BaseModel):
    start_at: datetime
    end_at: datetime
    state: str


class UserStatisticsSegment(StatisticsSegment):
    username: str | None = None


class DeviceStatisticsItem(BaseModel):
    device_id: int
    is_non_pc: bool = False
    name: str
    ip_address: str | None
    availability: list[StatisticsSegment]
    wan: list[StatisticsSegment]
    users: list[UserStatisticsSegment] = Field(default_factory=list)


class ClassroomStatisticsResponse(BaseModel):
    classroom_id: int
    start_at: datetime
    end_at: datetime
    devices: list[DeviceStatisticsItem]


def normalize_mac_address(value: str) -> str:
    return value.strip().upper()


def get_device_wan_state(device: Device) -> str:
    if device.wan_protected:
        return "protected"

    return "allowed" if device.wan_allowed else "blocked"


async def record_device_statistics_state(
    session: AsyncSession,
    device: Device,
    *,
    occurred_at: datetime,
    online: bool | None,
) -> bool:
    normalized_occurred_at = ensure_aware_utc(occurred_at)
    current = await session.get(DeviceStatisticsState, device.id)
    wan_state = get_device_wan_state(device)

    if current is not None and normalized_occurred_at < ensure_aware_utc(current.observed_at):
        return False

    next_online = online if online is not None else (current.online if current is not None else False)

    if current is None:
        current = DeviceStatisticsState(
            device_id=device.id,
            online=next_online,
            wan_state=wan_state,
            observed_at=normalized_occurred_at,
        )
        session.add(current)
        changed = True
    else:
        changed = current.online != next_online or current.wan_state != wan_state
        current.online = next_online
        current.wan_state = wan_state
        current.observed_at = normalized_occurred_at

    if changed:
        session.add(
            DeviceStatisticsEvent(
                device_id=device.id,
                is_non_pc=device.is_non_pc,
                occurred_at=normalized_occurred_at,
                online=next_online,
                wan_state=wan_state,
            )
        )

    return changed


@router.get(
    "/internal/classrooms/{classroom_id}/statistics",
    response_model=ClassroomStatisticsResponse,
)
async def get_classroom_statistics(
    classroom_id: int,
    range_minutes: int = Query(default=DEFAULT_STATISTICS_RANGE_MINUTES),
    session: AsyncSession = Depends(get_session),
) -> ClassroomStatisticsResponse:
    if range_minutes not in ALLOWED_STATISTICS_RANGE_MINUTES:
        allowed = ", ".join(str(value) for value in sorted(ALLOWED_STATISTICS_RANGE_MINUTES))
        raise HTTPException(
            status_code=422,
            detail=f"range_minutes must be one of: {allowed}",
        )

    classroom = await session.get(Classroom, classroom_id)

    if classroom is None or not classroom.is_active:
        raise HTTPException(status_code=404, detail="Classroom not found")

    end_at = datetime.now(timezone.utc)
    start_at = end_at - timedelta(minutes=range_minutes)

    result = await session.execute(
        select(Device)
        .where(Device.classroom_id == classroom_id)
        .where(Device.is_pinned.is_(True))
    )
    devices = sorted(result.scalars().all(), key=device_ip_sort_key)

    if not devices:
        return ClassroomStatisticsResponse(
            classroom_id=classroom_id,
            start_at=start_at,
            end_at=end_at,
            devices=[],
        )

    device_ids = [device.id for device in devices]

    before_result = await session.execute(
        select(DeviceStatisticsEvent)
        .where(DeviceStatisticsEvent.device_id.in_(device_ids))
        .where(DeviceStatisticsEvent.occurred_at < start_at)
        .order_by(
            DeviceStatisticsEvent.device_id,
            DeviceStatisticsEvent.occurred_at.desc(),
            DeviceStatisticsEvent.id.desc(),
        )
    )
    baseline_by_device: dict[int, DeviceStatisticsEvent] = {}

    for event in before_result.scalars().all():
        baseline_by_device.setdefault(event.device_id, event)

    range_result = await session.execute(
        select(DeviceStatisticsEvent)
        .where(DeviceStatisticsEvent.device_id.in_(device_ids))
        .where(DeviceStatisticsEvent.occurred_at >= start_at)
        .where(DeviceStatisticsEvent.occurred_at <= end_at)
        .order_by(
            DeviceStatisticsEvent.device_id,
            DeviceStatisticsEvent.occurred_at,
            DeviceStatisticsEvent.id,
        )
    )
    events_by_device: dict[int, list[DeviceStatisticsEvent]] = defaultdict(list)

    for event in range_result.scalars().all():
        events_by_device[event.device_id].append(event)

    user_intervals = (await session.execute(select(DeviceUserInterval)
        .where(DeviceUserInterval.device_id.in_(device_ids), DeviceUserInterval.end_at > start_at,
            DeviceUserInterval.start_at < end_at)
        .order_by(DeviceUserInterval.device_id, DeviceUserInterval.start_at, DeviceUserInterval.id))).scalars().all()
    users_by_device: dict[int, list[UserStatisticsSegment]] = defaultdict(list)
    for interval in user_intervals:
        users_by_device[interval.device_id].append(UserStatisticsSegment(
            start_at=max(start_at, ensure_aware_utc(interval.start_at)),
            end_at=min(end_at, ensure_aware_utc(interval.end_at)),
            state="user_present" if interval.username else "user_absent", username=interval.username))

    items: list[DeviceStatisticsItem] = []

    for device in devices:
        baseline = baseline_by_device.get(device.id)
        events = events_by_device.get(device.id, [])

        availability = build_segments(
            start_at=start_at,
            end_at=end_at,
            baseline=baseline,
            events=events,
            selector=lambda event: "online" if event.online else "offline",
        )
        wan = build_segments(
            start_at=start_at,
            end_at=end_at,
            baseline=baseline,
            events=events,
            selector=lambda event: event.wan_state,
        )

        items.append(
            DeviceStatisticsItem(
                device_id=device.id,
                is_non_pc=device.is_non_pc,
                name=device.inventory_name,
                ip_address=device.static_ip,
                availability=availability,
                wan=wan,
                users=[] if device.is_non_pc else users_by_device.get(device.id, []),
            )
        )

    return ClassroomStatisticsResponse(
        classroom_id=classroom_id,
        start_at=start_at,
        end_at=end_at,
        devices=items,
    )


def build_segments(
    *,
    start_at: datetime,
    end_at: datetime,
    baseline: DeviceStatisticsEvent | None,
    events: Iterable[DeviceStatisticsEvent],
    selector: Callable[[DeviceStatisticsEvent], str],
) -> list[StatisticsSegment]:
    segments: list[StatisticsSegment] = []
    current_state: str | None = selector(baseline) if baseline is not None else None
    cursor: datetime | None = start_at if baseline is not None else None

    for event in events:
        event_at = min(max(ensure_aware_utc(event.occurred_at), start_at), end_at)

        if current_state is not None and cursor is not None and event_at > cursor:
            append_segment(segments, cursor, event_at, current_state)

        current_state = selector(event)
        cursor = event_at

    if current_state is not None and cursor is not None and cursor < end_at:
        append_segment(segments, cursor, end_at, current_state)

    return segments


def append_segment(
    segments: list[StatisticsSegment],
    start_at: datetime,
    end_at: datetime,
    state: str,
) -> None:
    if segments and segments[-1].state == state and segments[-1].end_at == start_at:
        segments[-1].end_at = end_at
        return

    segments.append(
        StatisticsSegment(
            start_at=start_at,
            end_at=end_at,
            state=state,
        )
    )


def device_ip_sort_key(device: Device) -> tuple[int, int, str]:
    if device.static_ip:
        try:
            address = ip_address(device.static_ip)
            return address.version, int(address), device.inventory_name.casefold()
        except ValueError:
            pass

    return 99, device.id, device.inventory_name.casefold()


def ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)
