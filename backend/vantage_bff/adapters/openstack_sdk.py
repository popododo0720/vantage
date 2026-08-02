from __future__ import annotations

import asyncio
from typing import Any, cast

from vantage_bff.adapters.base import (
    AdapterError,
    AuthenticationError,
    AuthResult,
    ScopeError,
    ScopeResult,
)
from vantage_bff.models import Project, User


class OpenStackSdkAdapter:
    """OpenStack boundary; endpoint discovery and token scoping stay in openstacksdk."""

    def __init__(
        self,
        auth_url: str,
        interface: str,
        default_region: str,
        request_timeout_seconds: int,
    ) -> None:
        self.auth_url = auth_url
        self.interface = interface
        self.default_region = default_region
        self.request_timeout_seconds = request_timeout_seconds

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
                app_version="0.1.0",
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
                app_version="0.1.0",
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
