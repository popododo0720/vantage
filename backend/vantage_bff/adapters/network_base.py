from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from vantage_bff.network_models import NetworkResource, ResourceKind


@dataclass(frozen=True, slots=True)
class NetworkCapabilitiesResult:
    neutron: bool
    octavia: bool


@dataclass(frozen=True, slots=True)
class NetworkListResult:
    items: tuple[NetworkResource, ...]
    has_next: bool
    openstack_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class NetworkMutationResult:
    resource: NetworkResource | None
    openstack_request_id: str | None = None


class NetworkServicesAdapter(Protocol):
    async def network_capabilities(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> NetworkCapabilitiesResult: ...

    async def list_network_resources(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        *,
        limit: int,
        marker: str | None,
        parent_id: str | None,
        filters: dict[str, str],
    ) -> NetworkListResult: ...

    async def get_network_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        *,
        parent_id: str | None,
    ) -> NetworkResource: ...

    async def create_network_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        *,
        parent_id: str | None,
        attributes: dict[str, Any],
    ) -> NetworkMutationResult: ...

    async def update_network_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        *,
        parent_id: str | None,
        attributes: dict[str, Any],
        revision_number: int | None,
    ) -> NetworkMutationResult: ...

    async def delete_network_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        *,
        parent_id: str | None,
        revision_number: int | None,
        cascade: bool,
    ) -> NetworkMutationResult: ...

    async def run_network_action(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        *,
        action: str,
        parameters: dict[str, Any],
        revision_number: int | None,
    ) -> NetworkMutationResult: ...
