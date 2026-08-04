from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from vantage_bff.models import Project, Scope, SessionResponse, User


@dataclass(frozen=True, slots=True)
class SessionRecord:
    id: str
    csrf_token: str
    scope_namespace: str
    user: User
    projects: tuple[Project, ...]
    regions: tuple[str, ...]
    expires_at: datetime
    auth_context: dict[str, Any]
    active_scope: Scope | None = None
    locale: str = "en"

    def public(self) -> SessionResponse:
        return SessionResponse(
            user=self.user,
            active_scope=self.active_scope,
            expires_at=self.expires_at,
            regions=list(self.regions),
            locale=self.locale,
        )


class SessionStore(Protocol):
    async def create(self, record: SessionRecord) -> None: ...
    async def get(self, session_id: str) -> SessionRecord | None: ...
    async def delete(self, session_id: str) -> None: ...
    async def rotate(self, old_id: str, record: SessionRecord) -> bool: ...


class MemorySessionStore:
    def __init__(self) -> None:
        self._records: dict[str, SessionRecord] = {}
        self._lock = asyncio.Lock()

    async def create(self, record: SessionRecord) -> None:
        async with self._lock:
            self._records[record.id] = record

    async def get(self, session_id: str) -> SessionRecord | None:
        async with self._lock:
            record = self._records.get(session_id)
            if record and record.expires_at <= datetime.now(UTC):
                self._records.pop(session_id, None)
                return None
            return record

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._records.pop(session_id, None)

    async def rotate(self, old_id: str, record: SessionRecord) -> bool:
        async with self._lock:
            if self._records.pop(old_id, None) is None:
                return False
            self._records[record.id] = record
            return True


def new_session(
    *, user: User, projects: tuple[Project, ...], regions: tuple[str, ...],
    auth_context: dict[str, Any], ttl_seconds: int, upstream_expires_at: datetime | None = None
) -> SessionRecord:
    local_expiry = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    return SessionRecord(
        id=secrets.token_urlsafe(32),
        csrf_token=secrets.token_urlsafe(32),
        scope_namespace=new_scope_namespace(),
        user=user,
        projects=projects,
        regions=regions,
        expires_at=min(local_expiry, upstream_expires_at) if upstream_expires_at else local_expiry,
        auth_context=auth_context,
    )


def rotated_session(record: SessionRecord, **changes: Any) -> SessionRecord:
    return replace(
        record,
        id=secrets.token_urlsafe(32),
        csrf_token=secrets.token_urlsafe(32),
        **changes,
    )


def new_scope_namespace() -> str:
    return secrets.token_urlsafe(24)
