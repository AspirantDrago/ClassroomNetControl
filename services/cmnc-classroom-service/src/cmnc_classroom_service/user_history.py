"""Persist only observed user intervals; never extrapolate over collection gaps."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_classroom_service.db import get_session
from cmnc_classroom_service.models import Classroom, Device, DeviceStatisticsState, DeviceUserState, DeviceUserInterval

router = APIRouter()


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class UserObservation(BaseModel):
    device_id: int = Field(gt=0)
    classroom_id: int = Field(gt=0)
    router_id: int = Field(gt=0)
    host: str
    known: bool
    username: str | None = Field(default=None, max_length=256)
    observed_at: datetime


class UserObservations(BaseModel):
    observations: list[UserObservation] = Field(max_length=1000)
    valid_seconds: int = Field(default=90, ge=15, le=10800)


async def record_user(session: AsyncSession, observation: UserObservation, valid_seconds: int):
    at = utc(observation.observed_at)
    if at > datetime.now(timezone.utc) + timedelta(seconds=5):
        return
    # Serialize updates and verify the target still belongs to this classroom.
    row = (await session.execute(select(Device, Classroom).join(Classroom, Device.classroom_id == Classroom.id)
        .where(Device.id == observation.device_id).with_for_update(of=Device))).first()
    if row is None:
        return
    device, classroom = row
    if not device.is_pinned or not classroom.is_active or device.classroom_id != observation.classroom_id or classroom.router_id != observation.router_id or device.static_ip != observation.host:
        return
    state = await session.get(DeviceUserState, device.id)
    if state is not None and at <= utc(state.observed_at):
        return
    online = await session.get(DeviceStatisticsState, device.id)
    known = observation.known and online is not None and online.online and utc(online.observed_at) >= at - timedelta(seconds=90)
    username = observation.username.strip() or None if known and observation.username is not None else None
    previous = (await session.execute(select(DeviceUserInterval).where(DeviceUserInterval.device_id == device.id)
        .order_by(DeviceUserInterval.start_at.desc(), DeviceUserInterval.id.desc()).limit(1))).scalar_one_or_none()
    continuous = state is not None and state.known and state.valid_until is not None and utc(state.valid_until) >= at
    if previous is not None and (not known or not continuous or previous.username != username):
        previous.end_at = min(utc(previous.end_at), at)
    expires = at + timedelta(seconds=valid_seconds) if known else None
    if known:
        if continuous and previous is not None and previous.username == username:
            previous.end_at = expires
        else:
            session.add(DeviceUserInterval(device_id=device.id, start_at=at, end_at=expires, username=username))
    if state is None:
        state = DeviceUserState(device_id=device.id)
        session.add(state)
    state.known, state.username, state.observed_at, state.valid_until = known, username, at, expires


async def current_users(session: AsyncSession, device_ids: list[int]) -> dict:
    if not device_ids:
        return {}
    states = (await session.execute(select(DeviceUserState).where(DeviceUserState.device_id.in_(device_ids)))).scalars()
    now = datetime.now(timezone.utc)
    return {state.device_id: {"current_user_known": bool(state.known and state.valid_until and utc(state.valid_until) > now),
        "current_user": state.username if state.known and state.valid_until and utc(state.valid_until) > now else None}
        for state in states}


@router.get("/internal/veyon/user-targets")
async def user_targets(session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Device, Classroom, DeviceStatisticsState)
        .join(Classroom, Device.classroom_id == Classroom.id)
        .outerjoin(DeviceStatisticsState, DeviceStatisticsState.device_id == Device.id)
        .where(Device.is_pinned.is_(True), Classroom.is_active.is_(True))
        .order_by(Device.id))).all()
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=90)
    return [{"device_id": device.id, "classroom_id": classroom.id, "router_id": classroom.router_id,
        "host": device.static_ip, "online": bool(state and state.online and utc(state.observed_at) >= cutoff)}
        for device, classroom, state in rows if device.static_ip]


@router.post("/internal/veyon/user-observations")
async def user_observations(payload: UserObservations, session: AsyncSession = Depends(get_session)):
    # Stable lock order prevents deadlocks between overlapping batches.
    for observation in sorted(payload.observations, key=lambda item: (item.device_id, utc(item.observed_at))):
        await record_user(session, observation, payload.valid_seconds)
    await session.commit()
    return {"ok": True}
