from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from vantage_bff.models import Project, User


class AdapterError(Exception):
    default_status_code = 503

    def __init__(
        self,
        *,
        status_code: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__()
        self.status_code = status_code or self.default_status_code
        self.request_id = request_id


class AuthenticationError(AdapterError):
    default_status_code = 401


class ScopeError(AdapterError):
    default_status_code = 409


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: User
    projects: tuple[Project, ...]
    regions: tuple[str, ...]
    auth_context: dict[str, Any]
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ScopeResult:
    project: Project
    region: str
    auth_context: dict[str, Any]
    expires_at: datetime | None = None


class OpenStackAdapter(Protocol):
    async def authenticate(self, username: str, password: str, domain: str) -> AuthResult: ...

    async def scope(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> ScopeResult: ...
