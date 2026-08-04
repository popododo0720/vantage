from __future__ import annotations

from typing import Any

import pytest
from vantage_bff.adapters.base import AdapterError
from vantage_bff.adapters.openstack_network import OpenStackNetworkServicesAdapter
from vantage_bff.network_models import ResourceKind


class ImmediateRunner:
    async def run(self, function: Any, /, *args: Any, **kwargs: Any) -> Any:
        return function(*args, **kwargs)


class Resource:
    def __init__(self, values: dict[str, Any]) -> None:
        self.values = values

    def to_dict(self) -> dict[str, Any]:
        return dict(self.values)


class NetworkProxy:
    def __init__(self) -> None:
        self.query: dict[str, Any] | None = None
        self.updated: tuple[str, dict[str, Any]] | None = None
        self.qos_updated: tuple[str, str, dict[str, Any]] | None = None

    def networks(self, **query: Any) -> Any:
        self.query = query
        yield Resource(
            {
                "id": "network-id",
                "name": "private",
                "project_id": "project-alpha",
                "status": "ACTIVE",
                "revision_number": 7,
                "shared": False,
                "binding_host_id": "compute-1",
                "provider_physical_network": "physnet1",
                "ovn_chassis": "internal-value",
            }
        )

    def update_port(self, resource_id: str, **attrs: Any) -> Resource:
        self.updated = (resource_id, attrs)
        return Resource(
            {
                "id": resource_id,
                "name": attrs.get("name"),
                "project_id": "project-alpha",
                "revision_number": 8,
            }
        )

    def update_qos_bandwidth_limit_rule(
        self, resource_id: str, policy_id: str, **attrs: Any
    ) -> Resource:
        self.qos_updated = (resource_id, policy_id, attrs)
        return Resource({"id": resource_id, "project_id": "project-alpha", **attrs})


class LoadBalancerProxy:
    def __init__(self) -> None:
        self.member_parent: str | None = None

    def members(self, parent_id: str, **query: Any) -> Any:
        del query
        self.member_parent = parent_id
        yield Resource(
            {
                "id": "member-id",
                "name": "member-1",
                "project_id": "project-alpha",
                "provisioning_status": "ACTIVE",
                "operating_status": "ONLINE",
            }
        )


class Connection:
    def __init__(self) -> None:
        self.network = NetworkProxy()
        self.load_balancer = LoadBalancerProxy()

    def has_service(self, service: str) -> bool:
        return service in {"network", "load-balancer"}


@pytest.mark.asyncio
async def test_sdk_list_uses_server_filters_and_removes_backend_internal_fields() -> None:
    connection = Connection()
    adapter = OpenStackNetworkServicesAdapter(ImmediateRunner(), lambda *_args: connection)

    result = await adapter.list_network_resources(
        {"scoped_token": "server-only"},
        "project-alpha",
        "RegionOne",
        ResourceKind.NETWORK,
        limit=11,
        marker="previous-id",
        parent_id=None,
        filters={"name": "private", "status": "ACTIVE"},
    )

    assert connection.network.query == {
        "name": "private",
        "status": "ACTIVE",
        "limit": 11,
        "marker": "previous-id",
    }
    item = result.items[0]
    assert item.attributes["shared"] is False
    assert "binding_host_id" not in item.attributes
    assert "provider_physical_network" not in item.attributes
    assert "ovn_chassis" not in item.attributes
    assert result.openstack_request_id and result.openstack_request_id.startswith("req-")


@pytest.mark.asyncio
async def test_sdk_update_preserves_neutron_revision_precondition() -> None:
    connection = Connection()
    adapter = OpenStackNetworkServicesAdapter(ImmediateRunner(), lambda *_args: connection)

    result = await adapter.update_network_resource(
        {"scoped_token": "server-only"},
        "project-alpha",
        "RegionOne",
        ResourceKind.PORT,
        "port-id",
        parent_id=None,
        attributes={"name": "renamed", "port_security_enabled": False},
        revision_number=12,
    )

    assert connection.network.updated == (
        "port-id",
        {"name": "renamed", "port_security_enabled": False, "if_revision": 12},
    )
    assert result.resource and result.resource.revision_number == 8


@pytest.mark.asyncio
async def test_sdk_nested_octavia_member_uses_explicit_pool_parent() -> None:
    connection = Connection()
    adapter = OpenStackNetworkServicesAdapter(ImmediateRunner(), lambda *_args: connection)

    result = await adapter.list_network_resources(
        {"scoped_token": "server-only"},
        "project-alpha",
        "RegionOne",
        ResourceKind.MEMBER,
        limit=10,
        marker=None,
        parent_id="pool-id",
        filters={},
    )

    assert connection.load_balancer.member_parent == "pool-id"
    assert result.items[0].provisioning_status == "ACTIVE"
    assert result.items[0].operating_status == "ONLINE"


@pytest.mark.asyncio
async def test_sdk_qos_update_routes_rule_type_and_policy_parent() -> None:
    connection = Connection()
    adapter = OpenStackNetworkServicesAdapter(ImmediateRunner(), lambda *_args: connection)

    await adapter.update_network_resource(
        {"scoped_token": "server-only"},
        "project-alpha",
        "RegionOne",
        ResourceKind.QOS_RULE,
        "rule-id",
        parent_id="bandwidth_limit:policy-id",
        attributes={"max_kbps": 1000},
        revision_number=None,
    )

    assert connection.network.qos_updated == (
        "rule-id",
        "policy-id",
        {"max_kbps": 1000},
    )


@pytest.mark.asyncio
async def test_sdk_preserves_policy_forbidden_without_admin_retry() -> None:
    def forbidden(*_args: Any) -> Connection:
        raise AdapterError(status_code=403, request_id="req-policy")

    adapter = OpenStackNetworkServicesAdapter(ImmediateRunner(), forbidden)

    with pytest.raises(AdapterError) as caught:
        await adapter.get_network_resource(
            {"scoped_token": "server-only"},
            "project-alpha",
            "RegionOne",
            ResourceKind.NETWORK,
            "network-id",
            parent_id=None,
        )

    assert caught.value.status_code == 403
    assert caught.value.request_id == "req-policy"
