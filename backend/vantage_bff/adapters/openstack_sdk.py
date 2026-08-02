from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any, ParamSpec, TypeVar, cast
from uuid import UUID, uuid4

from vantage_bff.adapters.base import (
    AdapterError,
    AdapterTimeoutError,
    AuthenticationError,
    AuthResult,
    InstanceListResult,
    ScopeError,
    ScopeResult,
    normalized_quota,
)
from vantage_bff.models import (
    Instance,
    InstanceDetail,
    InstanceSort,
    InstanceVolume,
    Project,
    Quota,
    QuotaService,
    QuotaUnit,
    SortDirection,
    User,
)

_QUOTA_SPECS: dict[QuotaService, tuple[tuple[str, tuple[str, ...], QuotaUnit], ...]] = {
    QuotaService.COMPUTE: (
        ("instances", ("instances",), QuotaUnit.COUNT),
        ("cores", ("cores",), QuotaUnit.COUNT),
        ("ram_mib", ("ram", "ram_mib"), QuotaUnit.MIB),
    ),
    QuotaService.NETWORK: (
        ("floating_ips", ("floating_ips", "floatingip"), QuotaUnit.COUNT),
    ),
    QuotaService.STORAGE: (
        ("volumes", ("volumes",), QuotaUnit.COUNT),
        ("gigabytes", ("gigabytes",), QuotaUnit.GIB),
        ("snapshots", ("snapshots",), QuotaUnit.COUNT),
        ("backups", ("backups",), QuotaUnit.COUNT),
        ("backup_gigabytes", ("backup_gigabytes",), QuotaUnit.GIB),
    ),
}

_APP_VERSION = "0.3.0"
_P = ParamSpec("_P")
_T = TypeVar("_T")


class _BoundedToThreadRunner:
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("SDK thread capacity must be positive")
        self._capacity = asyncio.Semaphore(capacity)
        self._running: set[asyncio.Task[Any]] = set()

    async def run(
        self,
        function: Callable[_P, _T],
        /,
        *args: _P.args,
        **kwargs: _P.kwargs,
    ) -> _T:
        await self._capacity.acquire()
        try:
            task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        except BaseException:
            self._capacity.release()
            raise
        self._running.add(task)
        task.add_done_callback(self._completed)
        # Once admitted, the worker task owns capacity until to_thread returns.
        return await asyncio.shield(task)

    def _completed(self, task: asyncio.Task[Any]) -> None:
        self._running.discard(task)
        self._capacity.release()
        if not task.cancelled():
            task.exception()


class OpenStackSdkAdapter:
    """OpenStack boundary; endpoint discovery and token scoping stay in openstacksdk."""

    def __init__(
        self,
        auth_url: str,
        interface: str,
        default_region: str,
        request_timeout_seconds: int,
        quota_timeout_seconds: float | None = None,
        instance_timeout_seconds: float | None = None,
        thread_capacity: int = 8,
    ) -> None:
        self.auth_url = auth_url
        self.interface = interface
        self.default_region = default_region
        self.request_timeout_seconds = request_timeout_seconds
        self.quota_timeout_seconds = quota_timeout_seconds or float(request_timeout_seconds)
        self.instance_timeout_seconds = instance_timeout_seconds or float(request_timeout_seconds)
        self._sdk_threads = _BoundedToThreadRunner(thread_capacity)

    async def authenticate(self, username: str, password: str, domain: str) -> AuthResult:
        return await self._sdk_threads.run(self._authenticate, username, password, domain)

    def _authenticate(self, username: str, password: str, domain: str) -> AuthResult:
        try:
            from openstack.connection import Connection

            connection = Connection(
                auth_url=self.auth_url,
                username=username,
                password=password,
                user_domain_name=domain,
                interface=self.interface,
                api_timeout=self.request_timeout_seconds,
                app_name="vantage",
                app_version=_APP_VERSION,
            )
            token = connection.authorize()
            user_id = connection.current_user_id
            if not user_id:
                raise AuthenticationError
            identity = cast(Any, connection.identity)
            projects = tuple(
                Project(
                    id=project.id,
                    name=project.name,
                    domain_id=getattr(project, "domain_id", None),
                    enabled=getattr(project, "is_enabled", None),
                )
                for project in identity.user_projects(user_id)
            )
            auth_plugin = connection.session.auth
            if auth_plugin is None:
                raise AuthenticationError
            access = cast(Any, auth_plugin).get_access(connection.session)
            catalog = access.service_catalog.catalog
            regions = sorted(
                {
                    endpoint.get("region_id") or endpoint.get("region")
                    for service in catalog
                    for endpoint in service.get("endpoints", [])
                    if endpoint.get("region_id") or endpoint.get("region")
                }
            ) or [self.default_region]
            return AuthResult(
                user=User(id=user_id, name=username, domain_id=access.user_domain_id),
                projects=projects,
                regions=tuple(regions),
                auth_context={"unscoped_token": token},
                expires_at=access.expires,
            )
        except Exception as exc:
            raise _authentication_failure(exc) from exc

    async def scope(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> ScopeResult:
        return await self._sdk_threads.run(self._scope, auth_context, project_id, region)

    async def quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]:
        return await self._sdk_threads.run(
            self._quotas, auth_context, project_id, region, service
        )

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
    ) -> InstanceListResult:
        return await self._sdk_threads.run(
            self._list_instances,
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
            name=name,
            status=status,
            image_id=image_id,
            sort=sort,
            direction=direction,
        )

    async def get_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
    ) -> InstanceDetail:
        return await self._sdk_threads.run(
            self._get_instance,
            auth_context,
            project_id,
            region,
            instance_id,
        )

    def _scope(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> ScopeResult:
        try:
            from openstack.connection import Connection

            connection = Connection(
                auth_url=self.auth_url,
                auth_type="v3token",
                token=auth_context["unscoped_token"],
                project_id=project_id,
                region_name=region,
                interface=self.interface,
                api_timeout=self.request_timeout_seconds,
                app_name="vantage",
                app_version=_APP_VERSION,
            )
            scoped_token = connection.authorize()
            auth_plugin = connection.session.auth
            if auth_plugin is None:
                raise ScopeError
            access = cast(Any, auth_plugin).get_access(connection.session)
            identity = cast(Any, connection.identity)
            project_resource = identity.get_project(project_id)
            project = Project(
                id=project_resource.id,
                name=project_resource.name,
                domain_id=getattr(project_resource, "domain_id", None),
                enabled=getattr(project_resource, "is_enabled", None),
            )
            return ScopeResult(
                project=project,
                region=region,
                auth_context={
                    **auth_context,
                    "scoped_token": scoped_token,
                    "catalog": access.service_catalog.catalog,
                    "project_id": project_id,
                    "region": region,
                },
                expires_at=access.expires,
            )
        except Exception as exc:
            raise _scope_failure(exc) from exc

    def _quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]:
        try:
            from openstack.connection import Connection

            token = auth_context.get("scoped_token")
            if not isinstance(token, str) or not token:
                raise AdapterError(status_code=401)
            connection = Connection(
                auth_url=self.auth_url,
                auth_type="v3token",
                token=token,
                project_id=project_id,
                region_name=region,
                interface=self.interface,
                api_timeout=self.quota_timeout_seconds,
                app_name="vantage",
                app_version=_APP_VERSION,
            )
            if service is QuotaService.COMPUTE:
                resource = cast(Any, connection.compute).get_quota_set(
                    project_id, usage=True
                )
            elif service is QuotaService.NETWORK:
                resource = cast(Any, connection.network).get_quota(
                    project_id, details=True
                )
            else:
                resource = cast(Any, connection.block_storage).get_quota_set(
                    project_id, usage=True
                )
            return _normalize_quota_resource(service, resource)
        except Exception as exc:
            raise _quota_failure(exc) from exc

    def _list_instances(
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
    ) -> InstanceListResult:
        correlation_id = _global_request_id()
        try:
            from openstack import exceptions
            from openstack.compute.v2.server import Server

            connection = self._project_connection(
                auth_context,
                project_id,
                region,
                correlation_id,
            )
            query: dict[str, Any] = {
                "limit": limit,
                "sort_key": {
                    InstanceSort.CREATED_AT: "created_at",
                    InstanceSort.NAME: "display_name",
                    InstanceSort.STATUS: "vm_state",
                }[sort],
                "sort_dir": direction.value,
            }
            if marker is not None:
                query["marker"] = marker
            if name is not None:
                query["name"] = name
            if status is not None:
                query["status"] = status
            if image_id is not None:
                query["image"] = image_id
            session = cast(Any, connection.compute)
            base_path = "/servers/detail"
            microversion = Server._get_microversion(session)
            api_filters = Server._query_mapping._validate(
                query,
                base_path=base_path,
                allow_unknown_params=True,
            )
            query_params = Server._query_mapping._transpose(api_filters, Server)
            response = session.get(
                base_path,
                headers={"Accept": "application/json"},
                params=query_params,
                microversion=microversion,
            )
            exceptions.raise_from_response(response)
            data = response.json()
            if not isinstance(data, Mapping):
                raise ValueError("Nova server list response must be an object")
            resources = data.get("servers")
            if not isinstance(resources, list):
                raise ValueError("Nova server list response must contain servers")
            return InstanceListResult(
                items=tuple(_normalize_instance(resource) for resource in resources),
                has_next=_has_next_server_link(response, data),
                openstack_request_id=correlation_id,
            )
        except Exception as exc:
            raise _instance_failure(exc) from exc

    def _get_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
    ) -> InstanceDetail:
        correlation_id = _global_request_id()
        try:
            from openstack.compute.v2.server import Server

            connection = self._project_connection(
                auth_context,
                project_id,
                region,
                correlation_id,
            )
            resource = Server.existing(id=instance_id).fetch(cast(Any, connection.compute))
            return _normalize_instance_detail(resource, correlation_id)
        except Exception as exc:
            raise _instance_failure(exc) from exc

    def _project_connection(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        correlation_id: str,
    ) -> Any:
        from openstack.connection import Connection

        token = auth_context.get("scoped_token")
        if (
            not isinstance(token, str)
            or not token
            or auth_context.get("project_id") != project_id
            or auth_context.get("region") != region
        ):
            raise AdapterError(status_code=401)
        return Connection(
            auth_url=self.auth_url,
            auth_type="v3token",
            token=token,
            project_id=project_id,
            region_name=region,
            interface=self.interface,
            api_timeout=self.instance_timeout_seconds,
            app_name="vantage",
            app_version=_APP_VERSION,
            global_request_id=correlation_id,
        )


def _has_next_server_link(response: Any, data: Mapping[str, Any]) -> bool:
    body_links = data.get("servers_links")
    if isinstance(body_links, list):
        for link in body_links:
            if (
                isinstance(link, Mapping)
                and link.get("rel") == "next"
                and isinstance(link.get("href"), str)
                and link["href"]
            ):
                return True

    response_links = getattr(response, "links", None)
    if not isinstance(response_links, Mapping):
        return False
    next_link = response_links.get("next")
    if isinstance(next_link, str):
        return bool(next_link)
    if not isinstance(next_link, Mapping):
        return False
    return any(
        isinstance(next_link.get(key), str) and bool(next_link[key])
        for key in ("url", "uri", "href")
    )


def _global_request_id() -> str:
    return f"req-{uuid4()}"


def _source_mapping(value: Any) -> Mapping[str, Any]:
    body = getattr(value, "_body", None)
    attributes = getattr(body, "attributes", None)
    if isinstance(attributes, Mapping):
        return attributes
    if isinstance(value, Mapping):
        return value
    attributes = getattr(value, "__dict__", None)
    return attributes if isinstance(attributes, Mapping) else {}


def _source_value(value: Any, *names: str) -> tuple[bool, Any]:
    source = _source_mapping(value)
    for name in names:
        if name in source:
            return True, source[name]
    return False, None


def _required_text(value: Any, *names: str) -> str:
    present, raw = _source_value(value, *names)
    if not present or not isinstance(raw, str) or not raw:
        raise ValueError(f"Missing required instance field: {names[0]}")
    return raw


def _optional_text(value: Any, *names: str) -> str | None:
    present, raw = _source_value(value, *names)
    return raw if present and isinstance(raw, str) else None


def _reference(value: Any, *names: str) -> str | None:
    present, raw = _source_value(value, *names)
    if not present or raw is None:
        return None
    if isinstance(raw, str):
        return raw or None
    values = _source_mapping(raw)
    for key in ("original_name", "name", "id"):
        candidate = values.get(key)
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _created_at(value: Any) -> datetime | None:
    present, raw = _source_value(value, "created", "created_at")
    if not present or raw is None:
        return None
    if isinstance(raw, datetime):
        return raw.replace(tzinfo=UTC) if raw.tzinfo is None else raw
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _addresses(value: Any) -> list[str] | None:
    present, raw = _source_value(value, "addresses")
    if not present or raw is None:
        return None
    if not isinstance(raw, Mapping):
        return None
    addresses: list[str] = []
    for network, network_addresses in raw.items():
        if not isinstance(network, str) or not isinstance(network_addresses, list):
            continue
        for address in network_addresses:
            values = _source_mapping(address)
            ip_address = values.get("addr")
            if isinstance(ip_address, str) and ip_address:
                addresses.append(f"{network}: {ip_address}")
    return addresses


def _volumes(value: Any) -> list[InstanceVolume] | None:
    present, raw = _source_value(
        value,
        "os-extended-volumes:volumes_attached",
        "attached_volumes",
        "volumes",
    )
    if not present or raw is None:
        return None
    if not isinstance(raw, list):
        return None
    volumes: list[InstanceVolume] = []
    for attachment in raw:
        values = _source_mapping(attachment)
        volume_id = values.get("id", values.get("volume_id"))
        if not isinstance(volume_id, str) or not volume_id:
            continue
        device = values.get("device")
        volumes.append(
            InstanceVolume(
                id=volume_id,
                device=device if isinstance(device, str) else None,
            )
        )
    return volumes


def _normalize_instance(resource: Any) -> Instance:
    return Instance(
        id=UUID(_required_text(resource, "id")),
        status=_required_text(resource, "status"),
        name=_optional_text(resource, "name"),
        created_at=_created_at(resource),
        flavor=_reference(resource, "flavor", "flavor_id", "flavorRef"),
        image=_reference(resource, "image", "image_id", "imageRef"),
        addresses=_addresses(resource),
    )


def _normalize_instance_detail(resource: Any, request_id: str) -> InstanceDetail:
    instance = _normalize_instance(resource)
    return InstanceDetail(
        **instance.model_dump(),
        volumes=_volumes(resource),
        openstack_request_id=request_id,
    )


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        result = to_dict()
        if isinstance(result, Mapping):
            return result
    attributes = getattr(value, "__dict__", None)
    return attributes if isinstance(attributes, Mapping) else {}


def _resource_value(resource: Any, aliases: tuple[str, ...]) -> Any:
    values = _as_mapping(resource)
    for alias in aliases:
        if alias in values:
            return values[alias]
        value = getattr(resource, alias, None)
        if value is not None:
            return value
    return None


def _number(value: Any, names: tuple[str, ...]) -> int | float | None:
    values = _as_mapping(value)
    for name in names:
        candidate = values.get(name, getattr(value, name, None))
        if isinstance(candidate, bool) or candidate is None:
            continue
        if isinstance(candidate, (int, float)):
            return candidate
        if isinstance(candidate, str):
            try:
                return float(candidate) if "." in candidate else int(candidate)
            except ValueError:
                continue
    return None


def _normalize_quota_resource(
    service: QuotaService, resource: Any
) -> tuple[Quota, ...]:
    quotas: list[Quota] = []
    for name, aliases, unit in _QUOTA_SPECS[service]:
        raw = _resource_value(resource, aliases)
        if raw is None:
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            limit: int | float | None = raw
            used: int | float | None = 0
            reserved: int | float | None = 0
        else:
            limit = _number(raw, ("limit",))
            used = _number(raw, ("in_use", "used"))
            reserved = _number(raw, ("reserved",))
        quotas.append(
            normalized_quota(
                service=service,
                resource=name,
                used=used,
                reserved=reserved,
                limit=limit,
                unit=unit,
            )
        )
    return tuple(quotas)


def _status_code(exc: Exception) -> int | None:
    for attribute in ("status_code", "http_status"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int) and value > 0:
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) and value > 0 else None


def _request_id(exc: Exception) -> str | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get("x-openstack-request-id")
        if isinstance(value, str) and value:
            return value
    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    return None


def _authentication_failure(exc: Exception) -> AdapterError:
    status = _status_code(exc)
    request_id = _request_id(exc)
    if status == 401 or isinstance(exc, AuthenticationError):
        return AuthenticationError(request_id=request_id)
    if status in {403, 429}:
        return AdapterError(status_code=status, request_id=request_id)
    return AdapterError(status_code=503, request_id=request_id)


def _scope_failure(exc: Exception) -> ScopeError:
    status = _status_code(exc)
    request_id = _request_id(exc)
    if isinstance(exc, ScopeError):
        return ScopeError(status_code=exc.status_code, request_id=exc.request_id)
    if status not in {401, 403, 404, 409, 429}:
        status = 503
    return ScopeError(status_code=status, request_id=request_id)


def _quota_failure(exc: Exception) -> AdapterError:
    if isinstance(exc, AdapterError):
        return AdapterError(status_code=exc.status_code, request_id=exc.request_id)
    status = _status_code(exc)
    if status not in {401, 403, 404, 429}:
        status = 503
    return AdapterError(status_code=status, request_id=_request_id(exc))


def _instance_failure(exc: Exception) -> AdapterError:
    if isinstance(exc, AdapterTimeoutError):
        return AdapterTimeoutError(request_id=exc.request_id)
    if isinstance(exc, AdapterError):
        if exc.status_code == 504:
            return AdapterTimeoutError(request_id=exc.request_id)
        return AdapterError(status_code=exc.status_code, request_id=exc.request_id)
    request_id = _request_id(exc)
    timeout_names = {"ConnectTimeout", "ReadTimeout", "RequestTimeout", "Timeout"}
    if isinstance(exc, TimeoutError) or exc.__class__.__name__ in timeout_names:
        return AdapterTimeoutError(request_id=request_id)
    status = _status_code(exc)
    if status == 504:
        return AdapterTimeoutError(request_id=request_id)
    if status not in {400, 401, 403, 404, 409, 429}:
        status = 503
    return AdapterError(status_code=status, request_id=request_id)
