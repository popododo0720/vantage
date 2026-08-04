from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from vantage_bff.adapters.base import AdapterError
from vantage_bff.adapters.network_base import (
    NetworkCapabilitiesResult,
    NetworkListResult,
    NetworkMutationResult,
)
from vantage_bff.network_contracts import RESOURCE_SPECS
from vantage_bff.network_models import NetworkResource, ResourceKind

_NAMESPACE = UUID("78509615-0ee6-4a19-942c-490302408bf1")


class FakeNetworkServicesAdapter:
    """Mutable, deterministic Neutron/Octavia substitute for local development."""

    def __init__(self) -> None:
        self._resources: dict[tuple[str, str, ResourceKind], dict[str, NetworkResource]] = {}
        self._lock = asyncio.Lock()

    async def network_capabilities(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> NetworkCapabilitiesResult:
        self._require_scope(auth_context, project_id, region)
        return NetworkCapabilitiesResult(neutron=True, octavia=True)

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
    ) -> NetworkListResult:
        self._require_scope(auth_context, project_id, region)
        parent_id = self._parent(kind, parent_id)
        async with self._lock:
            resources = list(self._bucket(project_id, region, kind).values())
        if parent_id is not None:
            resources = [
                item for item in resources if item.attributes.get("parent_id") == parent_id
            ]
        for key, value in filters.items():
            folded = value.casefold()
            resources = [
                item
                for item in resources
                if folded
                in str(getattr(item, key, None) or item.attributes.get(key, "")).casefold()
            ]
        resources.sort(key=lambda item: item.id)
        start = self._marker_index(resources, marker)
        visible = resources[start : start + limit]
        return NetworkListResult(
            items=tuple(visible),
            has_next=start + limit < len(resources),
            openstack_request_id=self._request_id(),
        )

    async def get_network_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        *,
        parent_id: str | None,
    ) -> NetworkResource:
        self._require_scope(auth_context, project_id, region)
        parent_id = self._parent(kind, parent_id)
        item = self._bucket(project_id, region, kind).get(resource_id)
        if item is None or (
            parent_id is not None and item.attributes.get("parent_id") != parent_id
        ):
            raise AdapterError(status_code=404, request_id=self._request_id())
        return item.model_copy(update={"openstack_request_id": self._request_id()})

    async def create_network_resource(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        *,
        parent_id: str | None,
        attributes: dict[str, Any],
    ) -> NetworkMutationResult:
        self._require_scope(auth_context, project_id, region)
        resource_id = str(uuid4())
        request_id = self._request_id()
        item = self._new_resource(
            project_id,
            kind,
            resource_id,
            attributes,
            parent_id=parent_id,
            request_id=request_id,
        )
        async with self._lock:
            self._bucket(project_id, region, kind)[resource_id] = item
        return NetworkMutationResult(item, request_id)

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
    ) -> NetworkMutationResult:
        parent_id = self._parent(kind, parent_id)
        current = await self.get_network_resource(
            auth_context, project_id, region, kind, resource_id, parent_id=parent_id
        )
        if revision_number is not None and current.revision_number != revision_number:
            raise AdapterError(status_code=409, request_id=self._request_id())
        request_id = self._request_id()
        merged = {**current.attributes, **attributes}
        updated = self._new_resource(
            project_id,
            kind,
            resource_id,
            merged,
            parent_id=parent_id or self._string(current.attributes.get("parent_id")),
            request_id=request_id,
            revision=(current.revision_number or 0) + 1,
            created_at=current.created_at,
        )
        async with self._lock:
            self._bucket(project_id, region, kind)[resource_id] = updated
        return NetworkMutationResult(updated, request_id)

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
    ) -> NetworkMutationResult:
        parent_id = self._parent(kind, parent_id)
        current = await self.get_network_resource(
            auth_context, project_id, region, kind, resource_id, parent_id=parent_id
        )
        if revision_number is not None and current.revision_number != revision_number:
            raise AdapterError(status_code=409, request_id=self._request_id())
        dependencies = current.attributes.get("dependencies", [])
        if dependencies and not cascade:
            raise AdapterError(status_code=409, request_id=self._request_id())
        async with self._lock:
            self._bucket(project_id, region, kind).pop(resource_id, None)
        return NetworkMutationResult(None, self._request_id())

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
    ) -> NetworkMutationResult:
        current = await self.get_network_resource(
            auth_context, project_id, region, kind, resource_id, parent_id=None
        )
        if action not in RESOURCE_SPECS[kind].actions:
            raise AdapterError(status_code=400, request_id=self._request_id())
        attributes = dict(current.attributes)
        if action in {"associate", "attach_instance", "add_interface", "set_gateway"}:
            attributes.update(parameters)
        elif action == "disassociate":
            attributes.update({"port_id": None, "fixed_ip_address": None})
        elif action in {"detach_instance", "remove_interface", "clear_gateway"}:
            attributes["last_action"] = action
        elif action in {"add_fixed_ip", "remove_fixed_ip"}:
            fixed_ips = list(attributes.get("fixed_ips", []))
            value = parameters.get("fixed_ip")
            if action == "add_fixed_ip" and value not in fixed_ips:
                fixed_ips.append(value)
            if action == "remove_fixed_ip" and value in fixed_ips:
                fixed_ips.remove(value)
            attributes["fixed_ips"] = fixed_ips
        elif action == "failover":
            attributes["last_failover_at"] = datetime.now(UTC).isoformat()
        return await self.update_network_resource(
            auth_context,
            project_id,
            region,
            kind,
            resource_id,
            parent_id=None,
            attributes=attributes,
            revision_number=revision_number,
        )

    def _bucket(
        self, project_id: str, region: str, kind: ResourceKind
    ) -> dict[str, NetworkResource]:
        key = (project_id, region, kind)
        if key not in self._resources:
            self._resources[key] = self._seed(project_id, kind)
        return self._resources[key]

    def _seed(self, project_id: str, kind: ResourceKind) -> dict[str, NetworkResource]:
        result: dict[str, NetworkResource] = {}
        count = 31 if kind in {ResourceKind.NETWORK, ResourceKind.PORT} else 3
        for index in range(count):
            resource_id = str(uuid5(_NAMESPACE, f"{project_id}:{kind.value}:{index}"))
            attributes: dict[str, Any] = {
                "description": f"Fake {kind.value.replace('_', ' ')} {index + 1}",
                "admin_state_up": True,
            }
            if RESOURCE_SPECS[kind].parent_required:
                attributes["parent_id"] = str(
                    uuid5(_NAMESPACE, f"{project_id}:{kind.value}:parent")
                )
            if kind is ResourceKind.NETWORK:
                attributes.update(
                    {
                        "is_shared": index == 0,
                        "is_router_external": index == 0,
                        "mtu": 1500,
                    }
                )
            if kind is ResourceKind.PORT:
                attributes.update(
                    {
                        "network_id": str(uuid5(_NAMESPACE, f"{project_id}:network:0")),
                        "mac_address": f"fa:16:3e:00:00:{index:02x}",
                        "fixed_ips": [{"ip_address": f"10.0.0.{index + 10}"}],
                        "port_security_enabled": True,
                        "allowed_address_pairs": [],
                    }
                )
            item = self._new_resource(project_id, kind, resource_id, attributes, parent_id=None)
            result[resource_id] = item
        return result

    def _new_resource(
        self,
        project_id: str,
        kind: ResourceKind,
        resource_id: str,
        attributes: dict[str, Any],
        *,
        parent_id: str | None,
        request_id: str | None = None,
        revision: int = 0,
        created_at: datetime | None = None,
    ) -> NetworkResource:
        values = dict(attributes)
        if parent_id is not None:
            values["parent_id"] = parent_id
        now = datetime.now(UTC)
        provisioning = "ACTIVE" if RESOURCE_SPECS[kind].service == "load-balancer" else None
        operating = "ONLINE" if RESOURCE_SPECS[kind].service == "load-balancer" else None
        return NetworkResource(
            id=resource_id,
            resource_type=kind,
            name=self._string(values.get("name")) or f"{kind.value}-{resource_id[:8]}",
            project_id=project_id,
            status=self._string(values.get("status")) or "ACTIVE",
            provisioning_status=provisioning,
            operating_status=operating,
            revision_number=revision,
            created_at=created_at or now,
            updated_at=now,
            attributes=values,
            openstack_request_id=request_id,
        )

    def _marker_index(self, resources: Iterable[NetworkResource], marker: str | None) -> int:
        if marker is None:
            return 0
        for index, item in enumerate(resources):
            if item.id == marker:
                return index + 1
        raise AdapterError(status_code=400, request_id=self._request_id())

    def _require_scope(self, auth_context: dict[str, Any], project_id: str, region: str) -> None:
        if auth_context.get("project_id") != project_id or auth_context.get("region") != region:
            raise AdapterError(status_code=401, request_id=self._request_id())

    @staticmethod
    def _string(value: object) -> str | None:
        return value if isinstance(value, str) else None

    @staticmethod
    def _parent(kind: ResourceKind, parent_id: str | None) -> str | None:
        if kind is ResourceKind.QOS_RULE and parent_id and ":" in parent_id:
            return parent_id.split(":", 1)[1]
        return parent_id

    @staticmethod
    def _request_id() -> str:
        return f"req-{uuid4()}"
