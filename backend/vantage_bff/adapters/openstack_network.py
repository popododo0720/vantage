from __future__ import annotations

from collections.abc import Callable, Iterable
from itertools import islice
from typing import Any, Protocol, cast
from uuid import uuid4

from vantage_bff.adapters.base import AdapterError, AdapterTimeoutError
from vantage_bff.adapters.network_base import (
    NetworkCapabilitiesResult,
    NetworkListResult,
    NetworkMutationResult,
)
from vantage_bff.network_contracts import RESOURCE_SPECS
from vantage_bff.network_models import NetworkResource, ResourceKind


class ThreadRunner(Protocol):
    async def run(self, function: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Any: ...


_LIST_METHODS: dict[ResourceKind, str] = {
    ResourceKind.NETWORK: "networks",
    ResourceKind.SUBNET: "subnets",
    ResourceKind.PORT: "ports",
    ResourceKind.ROUTER: "routers",
    ResourceKind.FLOATING_IP: "ips",
    ResourceKind.SECURITY_GROUP: "security_groups",
    ResourceKind.SECURITY_GROUP_RULE: "security_group_rules",
    ResourceKind.QOS_POLICY: "qos_policies",
    ResourceKind.RBAC_POLICY: "rbac_policies",
    ResourceKind.LOAD_BALANCER: "load_balancers",
    ResourceKind.LISTENER: "listeners",
    ResourceKind.POOL: "pools",
    ResourceKind.HEALTH_MONITOR: "health_monitors",
    ResourceKind.L7_POLICY: "l7_policies",
}

_SDK_NAMES: dict[ResourceKind, str] = {
    ResourceKind.NETWORK: "network",
    ResourceKind.SUBNET: "subnet",
    ResourceKind.PORT: "port",
    ResourceKind.ROUTER: "router",
    ResourceKind.FLOATING_IP: "ip",
    ResourceKind.SECURITY_GROUP: "security_group",
    ResourceKind.SECURITY_GROUP_RULE: "security_group_rule",
    ResourceKind.QOS_POLICY: "qos_policy",
    ResourceKind.RBAC_POLICY: "rbac_policy",
    ResourceKind.LOAD_BALANCER: "load_balancer",
    ResourceKind.LISTENER: "listener",
    ResourceKind.POOL: "pool",
    ResourceKind.HEALTH_MONITOR: "health_monitor",
    ResourceKind.L7_POLICY: "l7_policy",
}

_QOS_RULE_METHODS = {
    "bandwidth_limit": "qos_bandwidth_limit_rule",
    "dscp_marking": "qos_dscp_marking_rule",
    "minimum_bandwidth": "qos_minimum_bandwidth_rule",
    "minimum_packet_rate": "qos_minimum_packet_rate_rule",
    "packet_rate_limit": "qos_packet_rate_limit_rule",
}

_HIDDEN_PROJECT_FIELDS = {
    "location",
    "binding_host_id",
    "binding_profile",
    "host_id",
    "profile",
    "provider_network_type",
    "provider_physical_network",
    "provider_segmentation_id",
}


class OpenStackNetworkServicesAdapter:
    """openstacksdk-backed Neutron and catalog-gated Octavia boundary."""

    def __init__(self, runner: ThreadRunner, connection_factory: Callable[..., Any]) -> None:
        self._runner = runner
        self._connection_factory = connection_factory

    async def network_capabilities(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> NetworkCapabilitiesResult:
        return cast(
            NetworkCapabilitiesResult,
            await self._runner.run(self._capabilities, auth_context, project_id, region),
        )

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
        return cast(
            NetworkListResult,
            await self._runner.run(
                self._list,
                auth_context,
                project_id,
                region,
                kind,
                limit,
                marker,
                parent_id,
                filters,
            ),
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
        return cast(
            NetworkResource,
            await self._runner.run(
                self._get, auth_context, project_id, region, kind, resource_id, parent_id
            ),
        )

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
        return cast(
            NetworkMutationResult,
            await self._runner.run(
                self._create, auth_context, project_id, region, kind, parent_id, attributes
            ),
        )

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
        return cast(
            NetworkMutationResult,
            await self._runner.run(
                self._update,
                auth_context,
                project_id,
                region,
                kind,
                resource_id,
                parent_id,
                attributes,
                revision_number,
            ),
        )

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
        return cast(
            NetworkMutationResult,
            await self._runner.run(
                self._delete,
                auth_context,
                project_id,
                region,
                kind,
                resource_id,
                parent_id,
                revision_number,
                cascade,
            ),
        )

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
        return cast(
            NetworkMutationResult,
            await self._runner.run(
                self._action,
                auth_context,
                project_id,
                region,
                kind,
                resource_id,
                action,
                parameters,
                revision_number,
            ),
        )

    def _connection(
        self, auth_context: dict[str, Any], project_id: str, region: str, request_id: str
    ) -> Any:
        return self._connection_factory(auth_context, project_id, region, request_id)

    def _capabilities(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> NetworkCapabilitiesResult:
        request_id = _request_id()
        try:
            connection = self._connection(auth_context, project_id, region, request_id)
            return NetworkCapabilitiesResult(
                neutron=bool(connection.has_service("network")),
                octavia=bool(connection.has_service("load-balancer")),
            )
        except Exception as exc:
            raise _failure(exc, request_id) from exc

    def _proxy(self, connection: Any, kind: ResourceKind) -> Any:
        service = RESOURCE_SPECS[kind].service
        if not connection.has_service(service):
            raise AdapterError(status_code=404)
        return (
            cast(Any, connection.network)
            if service == "network"
            else cast(Any, connection.load_balancer)
        )

    def _list(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        limit: int,
        marker: str | None,
        parent_id: str | None,
        filters: dict[str, str],
    ) -> NetworkListResult:
        request_id = _request_id()
        try:
            connection = self._connection(auth_context, project_id, region, request_id)
            proxy = self._proxy(connection, kind)
            query: dict[str, Any] = {**filters, "limit": limit}
            if marker is not None:
                query["marker"] = marker
            resources = self._list_call(proxy, kind, parent_id, query)
            items = tuple(
                _normalize_resource(item, kind, request_id) for item in islice(resources, limit)
            )
            return NetworkListResult(
                items=items,
                has_next=len(items) == limit,
                openstack_request_id=request_id,
            )
        except Exception as exc:
            raise _failure(exc, request_id) from exc

    def _list_call(
        self, proxy: Any, kind: ResourceKind, parent_id: str | None, query: dict[str, Any]
    ) -> Iterable[Any]:
        if kind is ResourceKind.MEMBER:
            return cast(Iterable[Any], proxy.members(_required_parent(parent_id), **query))
        if kind is ResourceKind.L7_RULE:
            return cast(Iterable[Any], proxy.l7_rules(_required_parent(parent_id), **query))
        if kind is ResourceKind.QOS_RULE:
            rule_type = query.pop("rule_type", None)
            method = _qos_method(rule_type, plural=True)
            return cast(Iterable[Any], getattr(proxy, method)(_required_parent(parent_id), **query))
        return cast(Iterable[Any], getattr(proxy, _LIST_METHODS[kind])(**query))

    def _get(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        parent_id: str | None,
    ) -> NetworkResource:
        request_id = _request_id()
        try:
            connection = self._connection(auth_context, project_id, region, request_id)
            proxy = self._proxy(connection, kind)
            resource = self._get_call(proxy, kind, resource_id, parent_id)
            return _normalize_resource(resource, kind, request_id)
        except Exception as exc:
            raise _failure(exc, request_id) from exc

    def _get_call(
        self, proxy: Any, kind: ResourceKind, resource_id: str, parent_id: str | None
    ) -> Any:
        if kind is ResourceKind.MEMBER:
            return proxy.get_member(resource_id, _required_parent(parent_id))
        if kind is ResourceKind.L7_RULE:
            return proxy.get_l7_rule(resource_id, _required_parent(parent_id))
        if kind is ResourceKind.QOS_RULE:
            rule_type, policy_id = _split_qos_parent(parent_id)
            return getattr(proxy, _qos_method(rule_type, operation="get"))(resource_id, policy_id)
        return getattr(proxy, f"get_{_SDK_NAMES[kind]}")(resource_id)

    def _create(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        parent_id: str | None,
        attributes: dict[str, Any],
    ) -> NetworkMutationResult:
        request_id = _request_id()
        try:
            connection = self._connection(auth_context, project_id, region, request_id)
            proxy = self._proxy(connection, kind)
            attrs = dict(attributes)
            if kind is ResourceKind.MEMBER:
                resource = proxy.create_member(_required_parent(parent_id), **attrs)
            elif kind is ResourceKind.L7_RULE:
                resource = proxy.create_l7_rule(_required_parent(parent_id), **attrs)
            elif kind is ResourceKind.QOS_RULE:
                rule_type = str(attrs.pop("rule_type"))
                resource = getattr(proxy, _qos_method(rule_type, operation="create"))(
                    _required_parent(parent_id), **attrs
                )
            else:
                resource = getattr(proxy, f"create_{_SDK_NAMES[kind]}")(**attrs)
            return NetworkMutationResult(
                _normalize_resource(resource, kind, request_id), request_id
            )
        except Exception as exc:
            raise _failure(exc, request_id) from exc

    def _update(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        parent_id: str | None,
        attributes: dict[str, Any],
        revision_number: int | None,
    ) -> NetworkMutationResult:
        request_id = _request_id()
        try:
            connection = self._connection(auth_context, project_id, region, request_id)
            proxy = self._proxy(connection, kind)
            attrs = dict(attributes)
            if kind is ResourceKind.MEMBER:
                resource = proxy.update_member(resource_id, _required_parent(parent_id), **attrs)
            elif kind is ResourceKind.L7_RULE:
                resource = proxy.update_l7_rule(resource_id, _required_parent(parent_id), **attrs)
            elif kind is ResourceKind.QOS_RULE:
                rule_type, policy_id = _split_qos_parent(parent_id)
                resource = getattr(proxy, _qos_method(rule_type, operation="update"))(
                    resource_id, policy_id, **attrs
                )
            else:
                method = getattr(proxy, f"update_{_SDK_NAMES[kind]}")
                if revision_number is not None and RESOURCE_SPECS[kind].service == "network":
                    attrs["if_revision"] = revision_number
                resource = method(resource_id, **attrs)
            return NetworkMutationResult(
                _normalize_resource(resource, kind, request_id), request_id
            )
        except Exception as exc:
            raise _failure(exc, request_id) from exc

    def _delete(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        parent_id: str | None,
        revision_number: int | None,
        cascade: bool,
    ) -> NetworkMutationResult:
        request_id = _request_id()
        try:
            connection = self._connection(auth_context, project_id, region, request_id)
            proxy = self._proxy(connection, kind)
            if kind is ResourceKind.MEMBER:
                proxy.delete_member(resource_id, _required_parent(parent_id), ignore_missing=False)
            elif kind is ResourceKind.L7_RULE:
                proxy.delete_l7_rule(resource_id, _required_parent(parent_id), ignore_missing=False)
            elif kind is ResourceKind.QOS_RULE:
                rule_type, policy_id = _split_qos_parent(parent_id)
                getattr(proxy, _qos_method(rule_type, operation="delete"))(
                    resource_id, policy_id, ignore_missing=False
                )
            else:
                method = getattr(proxy, f"delete_{_SDK_NAMES[kind]}")
                kwargs: dict[str, Any] = {"ignore_missing": False}
                if revision_number is not None and RESOURCE_SPECS[kind].service == "network":
                    kwargs["if_revision"] = revision_number
                if kind is ResourceKind.LOAD_BALANCER:
                    kwargs["cascade"] = cascade
                method(resource_id, **kwargs)
            return NetworkMutationResult(None, request_id)
        except Exception as exc:
            raise _failure(exc, request_id) from exc

    def _action(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: ResourceKind,
        resource_id: str,
        action: str,
        parameters: dict[str, Any],
        revision_number: int | None,
    ) -> NetworkMutationResult:
        request_id = _request_id()
        try:
            connection = self._connection(auth_context, project_id, region, request_id)
            network = cast(Any, connection.network)
            if kind is ResourceKind.ROUTER and action in {"add_interface", "remove_interface"}:
                method = (
                    network.add_interface_to_router
                    if action == "add_interface"
                    else network.remove_interface_from_router
                )
                method(
                    resource_id, subnet=parameters.get("subnet_id"), port=parameters.get("port_id")
                )
            elif kind is ResourceKind.ROUTER and action in {"set_gateway", "clear_gateway"}:
                gateway = (
                    parameters.get("external_gateway_info") if action == "set_gateway" else None
                )
                network.update_router(
                    resource_id, external_gateway_info=gateway, if_revision=revision_number
                )
            elif kind is ResourceKind.FLOATING_IP and action in {"associate", "disassociate"}:
                attrs = (
                    {
                        "port_id": parameters.get("port_id"),
                        "fixed_ip_address": parameters.get("fixed_ip_address"),
                    }
                    if action == "associate"
                    else {"port_id": None}
                )
                network.update_ip(resource_id, if_revision=revision_number, **attrs)
            elif kind is ResourceKind.PORT and action in {"add_fixed_ip", "remove_fixed_ip"}:
                port = network.get_port(resource_id)
                fixed_ips = list(getattr(port, "fixed_ips", []) or [])
                value = parameters.get("fixed_ip")
                if action == "add_fixed_ip" and value not in fixed_ips:
                    fixed_ips.append(value)
                if action == "remove_fixed_ip" and value in fixed_ips:
                    fixed_ips.remove(value)
                network.update_port(resource_id, fixed_ips=fixed_ips, if_revision=revision_number)
            elif kind is ResourceKind.PORT and action in {"attach_instance", "detach_instance"}:
                server_id = _required_string(parameters, "server_id")
                compute = cast(Any, connection.compute)
                if action == "attach_instance":
                    compute.create_server_interface(server_id, port_id=resource_id)
                else:
                    compute.delete_server_interface(resource_id, server_id)
            elif kind is ResourceKind.LOAD_BALANCER and action == "failover":
                cast(Any, connection.load_balancer).failover_load_balancer(resource_id)
            else:
                raise AdapterError(status_code=400, request_id=request_id)
            return NetworkMutationResult(None, request_id)
        except Exception as exc:
            raise _failure(exc, request_id) from exc


def _normalize_resource(resource: Any, kind: ResourceKind, request_id: str) -> NetworkResource:
    raw = resource.to_dict() if hasattr(resource, "to_dict") else dict(resource)
    attributes = {
        str(key): value
        for key, value in raw.items()
        if key not in _HIDDEN_PROJECT_FIELDS
        and not str(key).startswith("ovn_")
        and "chassis" not in str(key)
    }
    for key in (
        "id",
        "name",
        "project_id",
        "tenant_id",
        "status",
        "provisioning_status",
        "operating_status",
        "revision_number",
        "created_at",
        "updated_at",
    ):
        attributes.pop(key, None)
    return NetworkResource(
        id=str(raw.get("id")),
        resource_type=kind,
        name=_optional_string(raw.get("name")),
        project_id=_optional_string(raw.get("project_id") or raw.get("tenant_id")),
        status=_optional_string(raw.get("status")),
        provisioning_status=_optional_string(raw.get("provisioning_status")),
        operating_status=_optional_string(raw.get("operating_status")),
        revision_number=_optional_int(raw.get("revision_number")),
        created_at=raw.get("created_at"),
        updated_at=raw.get("updated_at"),
        attributes=attributes,
        openstack_request_id=request_id,
    )


def _qos_method(rule_type: object, *, operation: str | None = None, plural: bool = False) -> str:
    base = _QOS_RULE_METHODS.get(str(rule_type))
    if base is None:
        raise AdapterError(status_code=400)
    if plural:
        return base + "s"
    if operation is None:
        raise ValueError("QoS rule operation is required")
    return f"{operation}_{base}"


def _split_qos_parent(parent_id: str | None) -> tuple[str, str]:
    value = _required_parent(parent_id)
    try:
        rule_type, policy_id = value.split(":", 1)
    except ValueError as exc:
        raise AdapterError(status_code=400) from exc
    _qos_method(rule_type, plural=True)
    return rule_type, policy_id


def _required_parent(parent_id: str | None) -> str:
    if not parent_id:
        raise AdapterError(status_code=400)
    return parent_id


def _required_string(values: dict[str, Any], name: str) -> str:
    value = values.get(name)
    if not isinstance(value, str) or not value:
        raise AdapterError(status_code=400)
    return value


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _request_id() -> str:
    return f"req-{uuid4()}"


def _failure(exc: Exception, request_id: str) -> AdapterError:
    if isinstance(exc, AdapterError):
        return exc
    try:
        from openstack import exceptions

        if isinstance(exc, exceptions.ResourceTimeout):
            return AdapterTimeoutError(request_id=request_id)
        if isinstance(exc, exceptions.HttpException):
            return AdapterError(
                status_code=int(getattr(exc, "status_code", 503) or 503),
                request_id=getattr(exc, "request_id", None) or request_id,
            )
    except ImportError:
        pass
    return AdapterError(status_code=503, request_id=request_id)
