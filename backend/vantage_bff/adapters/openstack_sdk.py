from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, cast

from vantage_bff.adapters.base import (
    AdapterError,
    AuthenticationError,
    AuthResult,
    ScopeError,
    ScopeResult,
    normalized_quota,
)
from vantage_bff.models import Project, Quota, QuotaService, QuotaUnit, User

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


class OpenStackSdkAdapter:
    """OpenStack boundary; endpoint discovery and token scoping stay in openstacksdk."""

    def __init__(
        self,
        auth_url: str,
        interface: str,
        default_region: str,
        request_timeout_seconds: int,
        quota_timeout_seconds: float | None = None,
    ) -> None:
        self.auth_url = auth_url
        self.interface = interface
        self.default_region = default_region
        self.request_timeout_seconds = request_timeout_seconds
        self.quota_timeout_seconds = quota_timeout_seconds or float(request_timeout_seconds)

    async def authenticate(self, username: str, password: str, domain: str) -> AuthResult:
        return await asyncio.to_thread(self._authenticate, username, password, domain)

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
                app_version="0.2.0",
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
        return await asyncio.to_thread(self._scope, auth_context, project_id, region)

    async def quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]:
        return await asyncio.to_thread(
            self._quotas, auth_context, project_id, region, service
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
                app_version="0.2.0",
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
                app_version="0.2.0",
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
    request_id = getattr(exc, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get("x-openstack-request-id")
        if isinstance(value, str) and value:
            return value
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
