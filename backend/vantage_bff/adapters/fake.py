from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from vantage_bff.adapters.base import (
    AuthenticationError,
    AuthResult,
    ScopeError,
    ScopeResult,
    normalized_quota,
)
from vantage_bff.models import Project, Quota, QuotaService, QuotaUnit, User


class FakeOpenStackAdapter:
    """Deterministic development adapter. It never contains production credentials."""

    _projects = (
        Project(id="project-alpha", name="Alpha", domain_id="default", enabled=True),
        Project(id="project-beta", name="Beta", domain_id="default", enabled=True),
    )

    async def authenticate(self, username: str, password: str, domain: str) -> AuthResult:
        if password != "vantage":
            raise AuthenticationError
        visible = self._projects if username != "limited" else self._projects[:1]
        return AuthResult(
            user=User(id=f"user-{username}", name=username, domain_id=domain),
            projects=visible,
            regions=("RegionOne", "RegionTwo"),
            auth_context={
                "unscoped_token": secrets.token_urlsafe(32),
                "catalog": {"identity": "fake://keystone"},
            },
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def scope(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> ScopeResult:
        projects = {project.id: project for project in self._projects}
        if project_id not in projects or region not in {"RegionOne", "RegionTwo"}:
            raise ScopeError
        return ScopeResult(
            project=projects[project_id],
            region=region,
            auth_context={
                **auth_context,
                "scoped_token": secrets.token_urlsafe(32),
                "project_id": project_id,
                "region": region,
            },
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        )

    async def quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]:
        del auth_context, region
        multiplier = 1 if project_id == "project-alpha" else 2
        raw = {
            QuotaService.COMPUTE: (
                ("instances", 7 * multiplier, 0, 20, QuotaUnit.COUNT),
                ("cores", 18 * multiplier, 2, 40, QuotaUnit.COUNT),
                ("ram_mib", 49152 * multiplier, 0, 98304, QuotaUnit.MIB),
            ),
            QuotaService.NETWORK: (
                ("floating_ips", 3 * multiplier, 0, 10, QuotaUnit.COUNT),
            ),
            QuotaService.STORAGE: (
                ("volumes", 8 * multiplier, 0, 20, QuotaUnit.COUNT),
                ("gigabytes", 460 * multiplier, 40, 1000, QuotaUnit.GIB),
                ("snapshots", 4 * multiplier, 0, 20, QuotaUnit.COUNT),
                ("backups", multiplier, 0, 10, QuotaUnit.COUNT),
                ("backup_gigabytes", 80 * multiplier, 0, 500, QuotaUnit.GIB),
            ),
        }
        return tuple(
            normalized_quota(
                service=service,
                resource=resource,
                used=used,
                reserved=reserved,
                limit=limit,
                unit=unit,
            )
            for resource, used, reserved, limit, unit in raw[service]
        )
