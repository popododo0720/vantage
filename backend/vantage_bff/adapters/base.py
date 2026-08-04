from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, cast

from vantage_bff.admin.models import AdminScope
from vantage_bff.models import (
    Flavor,
    Image,
    ImageVisibility,
    Instance,
    InstanceDetail,
    InstanceSort,
    KeyPair,
    Network,
    Project,
    Quota,
    QuotaResource,
    QuotaService,
    QuotaState,
    QuotaUnit,
    SecurityGroup,
    SortDirection,
    User,
)


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


class AdapterTimeoutError(AdapterError):
    default_status_code = 504


@dataclass(frozen=True, slots=True)
class AuthResult:
    user: User
    projects: tuple[Project, ...]
    regions: tuple[str, ...]
    auth_context: dict[str, Any]
    admin_scopes: tuple[AdminScope, ...] = ()
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ScopeResult:
    project: Project
    region: str
    auth_context: dict[str, Any]
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class InstanceListResult:
    items: tuple[Instance, ...]
    has_next: bool = False
    openstack_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProvisioningListResult:
    items: tuple[Image | Flavor | KeyPair | Network | SecurityGroup, ...]
    has_next: bool = False
    openstack_request_id: str | None = None


def quota_state(used: int, reserved: int, limit: int | None) -> QuotaState:
    if limit is None or limit <= 0:
        return QuotaState.UNKNOWN
    pressure = (used + reserved) / limit
    if pressure >= 0.85:
        return QuotaState.HIGH
    if pressure >= 0.70:
        return QuotaState.WATCH
    return QuotaState.NORMAL


def normalized_quota(
    *,
    service: QuotaService,
    resource: str,
    used: int | float | None,
    reserved: int | float | None,
    limit: int | float | None,
    unit: QuotaUnit,
) -> Quota:
    normalized_used = max(0, int(used or 0))
    normalized_reserved = max(0, int(reserved or 0))
    normalized_limit = None if limit is None or int(limit) < 0 else int(limit)
    return Quota(
        service=service,
        resource=cast(QuotaResource, resource),
        used=normalized_used,
        reserved=normalized_reserved,
        limit=normalized_limit,
        unit=unit,
        state=quota_state(normalized_used, normalized_reserved, normalized_limit),
    )


class OpenStackAdapter(Protocol):
    async def authenticate(self, username: str, password: str, domain: str) -> AuthResult: ...

    async def scope(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> ScopeResult: ...

    async def quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]: ...

    async def list_instances(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
        image_id: str | None,
        sort: InstanceSort,
        direction: SortDirection,
    ) -> InstanceListResult: ...

    async def get_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
    ) -> InstanceDetail: ...

    async def list_images(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        visibility: ImageVisibility | None,
    ) -> ProvisioningListResult: ...

    async def list_flavors(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult: ...

    async def list_keypairs(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
    ) -> ProvisioningListResult: ...

    async def list_networks(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
    ) -> ProvisioningListResult: ...

    async def list_security_groups(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
    ) -> ProvisioningListResult: ...
