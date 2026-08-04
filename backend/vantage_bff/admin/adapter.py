from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from vantage_bff.admin.models import (
    AdminListResult,
    AdminMutationResult,
    AdminQuota,
    AdminScope,
    IdentityCreate,
    IdentityKind,
    IdentityResource,
    IdentityUpdate,
    QuotaUpdate,
    RoleAssignmentCreate,
)
from vantage_bff.models import QuotaService


@dataclass(frozen=True, slots=True)
class AdminScopeResult:
    scope: AdminScope
    auth_context: dict[str, Any]
    expires_at: datetime | None = None


class AdminAdapter(Protocol):
    async def admin_scope(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        region: str,
    ) -> AdminScopeResult: ...

    async def admin_list(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        kind: IdentityKind | str,
        *,
        limit: int,
        cursor: str | None,
        name: str | None,
        filters: dict[str, str],
    ) -> AdminListResult: ...

    async def admin_get(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        kind: IdentityKind,
        resource_id: str,
    ) -> IdentityResource: ...

    async def admin_create(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        kind: IdentityKind,
        payload: IdentityCreate,
    ) -> AdminMutationResult: ...

    async def admin_update(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        kind: IdentityKind,
        resource_id: str,
        payload: IdentityUpdate,
    ) -> AdminMutationResult: ...

    async def admin_delete(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        kind: IdentityKind,
        resource_id: str,
    ) -> AdminMutationResult: ...

    async def admin_grant_role(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        payload: RoleAssignmentCreate,
    ) -> AdminMutationResult: ...

    async def admin_revoke_role(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        assignment_id: str,
    ) -> AdminMutationResult: ...

    async def admin_quotas(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        project_id: str,
        service: QuotaService,
        user_id: str | None,
    ) -> tuple[AdminQuota, ...]: ...

    async def admin_update_quotas(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        project_id: str,
        service: QuotaService,
        payload: QuotaUpdate,
    ) -> AdminMutationResult: ...

    async def admin_reset_quotas(
        self,
        auth_context: dict[str, Any],
        scope: AdminScope,
        project_id: str,
        service: QuotaService,
        user_id: str | None,
    ) -> AdminMutationResult: ...
