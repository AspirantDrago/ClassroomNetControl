"""Coordinate deletion across the classroom and authorization databases.

Access writers share a transaction lock. A separately committed reservation
survives a lost HTTP response or process crash; retries replace its token.
"""
import asyncio
import json
import secrets
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from cmnc_auth_service.db import async_session_maker, get_session
from cmnc_auth_service.models import ClassroomAccess, ClassroomDeletionGuard
from cmnc_auth_service.settings import settings

router = APIRouter()


async def lock_access(session: AsyncSession):
    if session.get_bind().dialect.name == "postgresql":
        await session.execute(text("LOCK TABLE classroom_access IN SHARE ROW EXCLUSIVE MODE"))


async def check_assignments(session: AsyncSession, classroom_ids: list[int]):
    await lock_access(session)
    if classroom_ids and (await session.execute(select(ClassroomDeletionGuard.classroom_id).where(
        ClassroomDeletionGuard.classroom_id.in_(classroom_ids)).limit(1))).first():
        raise HTTPException(409, "Аудитория удалена или зарезервирована для удаления. Обновите список аудиторий.")


async def classroom_request(method: str, path: str, payload: dict):
    def send():
        request = Request(settings.classroom_service_url.rstrip("/") + path,
            data=json.dumps(payload).encode(), method=method,
            headers={"Content-Type": "application/json"})
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=7) as response:
                return json.load(response)
        except HTTPError as exc:
            try:
                detail = json.load(exc).get("detail", "Ошибка сервиса аудиторий")
            except (ValueError, AttributeError):
                detail = "Ошибка сервиса аудиторий"
            raise HTTPException(exc.code, detail) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise HTTPException(503, "Не удалось подтвердить операцию. Повторите запрос.") from exc
    return await asyncio.to_thread(send)


async def reserve(classroom_id: int, token: str):
    async with async_session_maker() as session:
        guard = await session.get(ClassroomDeletionGuard, classroom_id)
        if guard is None:
            session.add(ClassroomDeletionGuard(classroom_id=classroom_id, token=token))
        else:
            guard.token = token
        await session.commit()


async def unreserve(classroom_id: int, token: str | None = None):
    async with async_session_maker() as session:
        query = delete(ClassroomDeletionGuard).where(ClassroomDeletionGuard.classroom_id == classroom_id)
        if token is not None:
            query = query.where(ClassroomDeletionGuard.token == token)
        await session.execute(query)
        await session.commit()


class DeletionToken(BaseModel):
    token: str


@router.post("/internal/classroom-deletion-guards/{classroom_id}/verify")
async def verify_deletion(classroom_id: int, payload: DeletionToken, session: AsyncSession = Depends(get_session)):
    guard = await session.get(ClassroomDeletionGuard, classroom_id)
    if guard is None or not secrets.compare_digest(guard.token, payload.token):
        raise HTTPException(409, "Разрешение на удаление аудитории устарело")
    return {"valid": True}


@router.delete("/internal/admin/classrooms/{classroom_id}")
async def delete_classroom(classroom_id: int, session: AsyncSession = Depends(get_session)):
    await lock_access(session)
    try:
        references = (await session.execute(select(ClassroomAccess.id).where(
            ClassroomAccess.classroom_id == classroom_id).limit(1))).first()
        if references:
            raise HTTPException(409, "Нельзя удалить аудиторию: она назначена пользователям или рабочим станциям. Сначала удалите назначения доступа.")
        token = secrets.token_hex(32)
        await reserve(classroom_id, token)
        try:
            result = await classroom_request("DELETE", f"/internal/classrooms/{classroom_id}", {"token": token})
        except HTTPException as exc:
            if exc.status_code == 404 and exc.detail == "Аудитория не найдена":
                result = {"deleted": True}
            else:
                # Known rejections did not delete anything. Ambiguous failures
                # retain the durable guard until retry or successful activation.
                if exc.status_code in (409, 422):
                    await unreserve(classroom_id, token)
                raise
        await session.commit()
        return result
    except BaseException:
        await session.rollback()
        raise


@router.patch("/internal/admin/classrooms/{classroom_id}/activate")
async def activate_classroom(classroom_id: int, payload: dict, session: AsyncSession = Depends(get_session)):
    await lock_access(session)
    try:
        result = await classroom_request("PATCH", f"/internal/classrooms/{classroom_id}", {**payload, "is_active": True})
        await unreserve(classroom_id)
        await session.commit()
        return result
    except BaseException:
        await session.rollback()
        raise
