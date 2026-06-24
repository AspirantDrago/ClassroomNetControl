from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe


@dataclass(slots=True)
class CameraSession:
    id: str
    rtsp_url: str
    quality: str
    created_at: datetime
    expires_at: datetime


class CameraSessionStore:
    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._sessions: dict[str, CameraSession] = {}

    def create(self, rtsp_url: str, quality: str) -> CameraSession:
        now = datetime.now(timezone.utc)
        session = CameraSession(
            id=token_urlsafe(32),
            rtsp_url=rtsp_url,
            quality=quality,
            created_at=now,
            expires_at=now + timedelta(seconds=self._ttl_seconds),
        )
        self._sessions[session.id] = session
        return session

    def get(self, session_id: str) -> CameraSession | None:
        session = self._sessions.get(session_id)

        if session is None:
            return None

        if session.expires_at <= datetime.now(timezone.utc):
            self._sessions.pop(session_id, None)
            return None

        return session

    def delete(self, session_id: str) -> bool:
        return self._sessions.pop(session_id, None) is not None

    def delete_expired(self) -> int:
        now = datetime.now(timezone.utc)
        expired_ids = [
            session_id
            for session_id, session in self._sessions.items()
            if session.expires_at <= now
        ]

        for session_id in expired_ids:
            self._sessions.pop(session_id, None)

        return len(expired_ids)
