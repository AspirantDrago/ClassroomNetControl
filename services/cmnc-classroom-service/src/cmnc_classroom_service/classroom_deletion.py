"""Fail closed unless the authorization service reserved this exact attempt."""
import asyncio
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener
from fastapi import HTTPException
from cmnc_classroom_service.settings import settings


async def verify_deletion_token(classroom_id: int, token: str):
    def verify():
        request = Request(settings.auth_service_url.rstrip("/") +
            f"/internal/classroom-deletion-guards/{classroom_id}/verify",
            data=json.dumps({"token": token}).encode(), method="POST",
            headers={"Content-Type": "application/json"})
        try:
            with build_opener(ProxyHandler({})).open(request, timeout=3) as response:
                if json.load(response).get("valid") is not True:
                    raise HTTPException(409, "Разрешение на удаление аудитории устарело")
        except HTTPError as exc:
            raise HTTPException(409 if exc.code == 409 else 503,
                "Не удалось проверить разрешение на удаление аудитории") from exc
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            raise HTTPException(503, "Сервис авторизации недоступен, удаление отменено") from exc
    await asyncio.to_thread(verify)
