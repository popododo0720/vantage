from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, cast
from urllib.parse import parse_qsl, urlparse

from vantage_bff.adapters.base import AdapterError
from vantage_bff.admin.adapter import AdminScopeResult
from vantage_bff.admin.models import (
    AdminListResult,
    AdminMutationResult,
    AdminQuota,
    AdminScope,
    AdminScopeType,
    IdentityCreate,
    IdentityKind,
    IdentityResource,
    IdentityUpdate,
    QuotaUpdate,
    RoleAssignment,
    RoleAssignmentCreate,
)
from vantage_bff.models import QuotaService


def discover_scopes(
    *,
    auth_url: str,
    token: str,
    domain_id: str | None,
    region: str,
    interface: str,
    timeout: float,
    app_version: str,
) -> tuple[tuple[AdminScope, ...], dict[str, str], list[datetime]]:
    candidates = [AdminScope(type=AdminScopeType.SYSTEM, id="all", name="System")]
    if domain_id:
        candidates.append(AdminScope(type=AdminScopeType.DOMAIN, id=domain_id, name=domain_id))
    scopes: list[AdminScope] = []
    tokens: dict[str, str] = {}
    expiries: list[datetime] = []
    base_context: dict[str, Any] = {"unscoped_token": token, "admin_tokens": {}}
    for candidate in candidates:
        try:
            result = establish_scope(
                auth_url=auth_url,
                interface=interface,
                timeout=timeout,
                app_version=app_version,
                auth_context=base_context,
                scope=candidate,
                region=region,
            )
        except AdapterError:
            continue
        scopes.append(result.scope)
        scoped_token = result.auth_context["admin_tokens"][scope_key(result.scope)]
        tokens[scope_key(result.scope)] = cast(str, scoped_token)
        if result.expires_at:
            expiries.append(result.expires_at)
    return tuple(scopes), tokens, expiries


def establish_scope(
    *,
    auth_url: str,
    interface: str,
    timeout: float,
    app_version: str,
    auth_context: dict[str, Any],
    scope: AdminScope,
    region: str,
) -> AdminScopeResult:
    from openstack.connection import Connection

    try:
        kwargs: dict[str, Any] = {}
        if scope.type is AdminScopeType.SYSTEM:
            kwargs["system_scope"] = scope.id
        elif scope.type is AdminScopeType.DOMAIN:
            kwargs["domain_id"] = scope.id
        else:
            kwargs["project_id"] = scope.id
        connection = Connection(
            auth_url=auth_url,
            auth_type="v3token",
            token=auth_context["unscoped_token"],
            region_name=region,
            interface=interface,
            api_timeout=timeout,
            app_name="vantage",
            app_version=app_version,
            **kwargs,
        )
        token = connection.authorize()
        auth_plugin = connection.session.auth
        if auth_plugin is None:
            raise AdapterError(status_code=401)
        access = cast(Any, auth_plugin).get_access(connection.session)
        resolved = scope
        identity = cast(Any, connection.identity)
        if scope.type is AdminScopeType.DOMAIN:
            resource = identity.get_domain(scope.id)
            resolved = scope.model_copy(update={"name": resource.name})
        elif scope.type is AdminScopeType.PROJECT:
            resource = identity.get_project(scope.id)
            resolved = scope.model_copy(update={"name": resource.name})
        tokens = auth_context.get("admin_tokens")
        token_map = dict(tokens) if isinstance(tokens, dict) else {}
        token_map[scope_key(resolved)] = token
        return AdminScopeResult(
            scope=resolved,
            auth_context={
                **auth_context,
                "admin_tokens": token_map,
                "active_admin_scope": scope_key(resolved),
                "admin_region": region,
                "catalog": access.service_catalog.catalog,
            },
            expires_at=access.expires,
        )
    except Exception as exc:
        raise translate_error(exc) from exc


def connection_for(
    *,
    auth_url: str,
    interface: str,
    timeout: float,
    app_version: str,
    auth_context: dict[str, Any],
    scope: AdminScope,
    global_request_id: str,
) -> Any:
    from openstack.connection import Connection

    tokens = auth_context.get("admin_tokens")
    token = tokens.get(scope_key(scope)) if isinstance(tokens, dict) else None
    if not isinstance(token, str) or not token:
        raise AdapterError(status_code=401)
    kwargs: dict[str, Any] = {}
    if scope.type is AdminScopeType.SYSTEM:
        kwargs["system_scope"] = scope.id
    elif scope.type is AdminScopeType.DOMAIN:
        kwargs["domain_id"] = scope.id
    else:
        kwargs["project_id"] = scope.id
    return Connection(
        auth_url=auth_url,
        auth_type="v3token",
        token=token,
        region_name=auth_context.get("admin_region"),
        interface=interface,
        api_timeout=timeout,
        app_name="vantage",
        app_version=app_version,
        global_request_id=global_request_id,
        **kwargs,
    )


def list_resources(
    connection: Any,
    kind: IdentityKind | str,
    *,
    limit: int,
    cursor: str | None,
    name: str | None,
    filters: dict[str, str],
    request_id: str,
) -> AdminListResult:
    try:
        from openstack import exceptions

        path = "/role_assignments" if kind == "role-assignments" else f"/{kind}"
        params: dict[str, Any] = {"limit": limit}
        if name and kind != "role-assignments":
            params["name"] = name
        params.update(_assignment_filters(filters) if kind == "role-assignments" else filters)
        if cursor:
            parsed = urlparse(cursor)
            path = parsed.path.removeprefix("/v3") or "/"
            params = dict(parse_qsl(parsed.query, keep_blank_values=True))
        response = cast(Any, connection.identity).get(path, params=params)
        exceptions.raise_from_response(response)
        body = response.json()
        key = "role_assignments" if kind == "role-assignments" else str(kind)
        raw_items = body.get(key, [])
        if not isinstance(raw_items, list):
            raise ValueError(f"Identity response {key} must be a list")
        if kind == "role-assignments":
            items: list[IdentityResource | RoleAssignment] = [
                normalize_assignment(item) for item in raw_items
            ]
        else:
            items = [normalize_identity(item) for item in raw_items]
        return AdminListResult(
            items=items,
            next_cursor=_next_link(body),
            openstack_request_id=response_request_id(response) or request_id,
        )
    except Exception as exc:
        raise translate_error(exc) from exc


def get_resource(connection: Any, kind: IdentityKind, resource_id: str) -> IdentityResource:
    try:
        identity = cast(Any, connection.identity)
        resource = getattr(identity, f"get_{kind[:-1]}")(resource_id)
        return normalize_identity(resource)
    except Exception as exc:
        raise translate_error(exc) from exc


def create_resource(
    connection: Any, kind: IdentityKind, payload: IdentityCreate, request_id: str
) -> AdminMutationResult:
    try:
        identity = cast(Any, connection.identity)
        attrs = payload.model_dump(exclude_none=True)
        resource = getattr(identity, f"create_{kind[:-1]}")(**attrs)
        return AdminMutationResult(
            resource=normalize_identity(resource), openstack_request_ids=[request_id]
        )
    except Exception as exc:
        raise translate_error(exc) from exc


def update_resource(
    connection: Any,
    kind: IdentityKind,
    resource_id: str,
    payload: IdentityUpdate,
    request_id: str,
) -> AdminMutationResult:
    try:
        identity = cast(Any, connection.identity)
        attrs = payload.model_dump(exclude_unset=True)
        resource = getattr(identity, f"update_{kind[:-1]}")(resource_id, **attrs)
        return AdminMutationResult(
            resource=normalize_identity(resource), openstack_request_ids=[request_id]
        )
    except Exception as exc:
        raise translate_error(exc) from exc


def delete_resource(
    connection: Any, kind: IdentityKind, resource_id: str, request_id: str
) -> AdminMutationResult:
    try:
        identity = cast(Any, connection.identity)
        getattr(identity, f"delete_{kind[:-1]}")(resource_id, ignore_missing=False)
        return AdminMutationResult(openstack_request_ids=[request_id])
    except Exception as exc:
        raise translate_error(exc) from exc


def change_role(
    connection: Any,
    payload: RoleAssignmentCreate,
    *,
    revoke: bool,
    request_id: str,
) -> AdminMutationResult:
    try:
        identity = cast(Any, connection.identity)
        verb = "unassign" if revoke else "assign"
        method = getattr(
            identity,
            f"{verb}_{payload.scope_type.value}_role_"
            f"{'from' if revoke else 'to'}_{payload.actor_type}",
        )
        if payload.scope_type is AdminScopeType.SYSTEM:
            method(payload.actor_id, payload.role_id, payload.scope_id)
        else:
            method(
                payload.scope_id,
                payload.actor_id,
                payload.role_id,
                inherited=payload.inherited,
            )
        resource = (
            None
            if revoke
            else RoleAssignment(id=assignment_id(payload), **payload.model_dump())
        )
        return AdminMutationResult(resource=resource, openstack_request_ids=[request_id])
    except Exception as exc:
        raise translate_error(exc) from exc


def read_quotas(
    connection: Any,
    project_id: str,
    service: QuotaService,
    user_id: str | None,
) -> tuple[AdminQuota, ...]:
    try:
        if user_id and service is not QuotaService.COMPUTE:
            raise AdapterError(status_code=422)
        proxy = _quota_proxy(connection, service)
        kwargs: dict[str, Any] = {"usage": True}
        if user_id:
            kwargs["user_id"] = user_id
        current = (
            proxy.get_quota(project_id, details=True)
            if service is QuotaService.NETWORK
            else proxy.get_quota_set(project_id, **kwargs)
        )
        defaults = _quota_defaults(proxy, project_id, service)
        return normalize_quotas(current, defaults, service, user_id)
    except Exception as exc:
        raise translate_error(exc) from exc


def update_quotas(
    connection: Any,
    project_id: str,
    service: QuotaService,
    payload: QuotaUpdate,
    request_id: str,
) -> AdminMutationResult:
    try:
        if payload.user_id and service is not QuotaService.COMPUTE:
            raise AdapterError(status_code=422)
        proxy = _quota_proxy(connection, service)
        kwargs: dict[str, Any] = dict(payload.values)
        if payload.user_id:
            kwargs["user"] = payload.user_id
        if service is QuotaService.NETWORK:
            proxy.update_quota(project_id, **kwargs)
        else:
            proxy.update_quota_set(project_id, **kwargs)
        return AdminMutationResult(openstack_request_ids=[request_id])
    except Exception as exc:
        raise translate_error(exc) from exc


def reset_quotas(
    connection: Any,
    project_id: str,
    service: QuotaService,
    user_id: str | None,
    request_id: str,
) -> AdminMutationResult:
    try:
        if user_id and service is not QuotaService.COMPUTE:
            raise AdapterError(status_code=422)
        proxy = _quota_proxy(connection, service)
        if service is QuotaService.NETWORK:
            proxy.delete_quota(project_id, ignore_missing=False)
        else:
            kwargs = {"user_id": user_id} if user_id else {}
            proxy.revert_quota_set(project_id, **kwargs)
        return AdminMutationResult(openstack_request_ids=[request_id])
    except Exception as exc:
        raise translate_error(exc) from exc


def normalize_identity(value: Any) -> IdentityResource:
    source = value if isinstance(value, Mapping) else getattr(value, "to_dict", lambda: {})()
    source = cast(Mapping[str, Any], source)
    known = {
        "id", "name", "description", "domain_id", "enabled", "is_enabled",
        "default_project_id", "email", "parent_id", "parent",
    }
    return IdentityResource(
        id=str(source.get("id", getattr(value, "id", ""))),
        name=str(source.get("name", getattr(value, "name", ""))),
        description=_text(source.get("description")),
        domain_id=_text(source.get("domain_id")),
        enabled=_bool(source.get("enabled", source.get("is_enabled"))),
        default_project_id=_text(source.get("default_project_id")),
        email=_text(source.get("email")),
        parent_id=_text(source.get("parent_id", source.get("parent"))),
        extra={key: item for key, item in source.items() if key not in known},
    )


def normalize_assignment(value: Mapping[str, Any]) -> RoleAssignment:
    actor_type: Literal["user", "group"] = (
        "user" if isinstance(value.get("user"), Mapping) else "group"
    )
    actor = cast(Mapping[str, Any], value.get(actor_type, {}))
    scope_value = cast(Mapping[str, Any], value.get("scope", {}))
    if "system" in scope_value:
        scope_type = AdminScopeType.SYSTEM
        target = cast(Mapping[str, Any], scope_value["system"])
        scope_id = str(target.get("all", "all"))
    elif "domain" in scope_value:
        scope_type = AdminScopeType.DOMAIN
        target = cast(Mapping[str, Any], scope_value["domain"])
        scope_id = str(target.get("id", ""))
    else:
        scope_type = AdminScopeType.PROJECT
        target = cast(Mapping[str, Any], scope_value.get("project", {}))
        scope_id = str(target.get("id", ""))
    role = cast(Mapping[str, Any], value.get("role", {}))
    inherited = value.get("scope", {}).get("OS-INHERIT:inherited_to") == "projects"
    payload = RoleAssignmentCreate(
        role_id=str(role.get("id", "")),
        actor_type=actor_type,
        actor_id=str(actor.get("id", "")),
        scope_type=scope_type,
        scope_id=scope_id,
        inherited=inherited,
    )
    return RoleAssignment(id=assignment_id(payload), **payload.model_dump())


def assignment_id(payload: RoleAssignmentCreate) -> str:
    raw = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def assignment_from_id(value: str) -> RoleAssignmentCreate:
    padding = "=" * (-len(value) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(value + padding))
        return RoleAssignmentCreate.model_validate(data)
    except Exception as exc:
        raise AdapterError(status_code=404) from exc


def normalize_quotas(
    current: Any,
    defaults: Any,
    service: QuotaService,
    user_id: str | None,
) -> tuple[AdminQuota, ...]:
    current_values = _mapping(current)
    default_values = _mapping(defaults)
    ignored = {"id", "project_id", "tenant_id", "location", "name", "force"}
    quotas: list[AdminQuota] = []
    for name, raw in current_values.items():
        if name in ignored or name.startswith("_"):
            continue
        details = raw if isinstance(raw, Mapping) else {}
        limit = details.get("limit", raw) if isinstance(details, Mapping) else raw
        if not isinstance(limit, int):
            continue
        used = details.get("used") if isinstance(details, Mapping) else None
        reserved = details.get("reserved") if isinstance(details, Mapping) else None
        default = default_values.get(name)
        if isinstance(default, Mapping):
            default = default.get("limit")
        quotas.append(
            AdminQuota(
                service=service,
                resource=name,
                limit=None if limit < 0 else limit,
                used=used if isinstance(used, int) and used >= 0 else None,
                reserved=reserved if isinstance(reserved, int) and reserved >= 0 else None,
                default=(None if isinstance(default, int) and default < 0 else default)
                if isinstance(default, int) else None,
                user_id=user_id,
            )
        )
    return tuple(sorted(quotas, key=lambda item: item.resource))


def scope_key(scope: AdminScope) -> str:
    return f"{scope.type.value}:{scope.id}"


def response_request_id(response: Any) -> str | None:
    headers = getattr(response, "headers", {})
    for name in ("x-openstack-request-id", "X-OpenStack-Request-ID"):
        value = headers.get(name) if hasattr(headers, "get") else None
        if isinstance(value, str) and value:
            return value
    return None


def translate_error(exc: Exception) -> AdapterError:
    if isinstance(exc, AdapterError):
        return exc
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None) or 503
    response = getattr(exc, "response", None)
    return AdapterError(status_code=int(status), request_id=response_request_id(response))


def _next_link(body: Mapping[str, Any]) -> str | None:
    links = body.get("links")
    if isinstance(links, Mapping):
        next_value = links.get("next")
        if isinstance(next_value, str) and next_value:
            return next_value
    return None


def _assignment_filters(filters: dict[str, str]) -> dict[str, str]:
    aliases = {
        "user_id": "user.id",
        "group_id": "group.id",
        "role_id": "role.id",
        "project_id": "scope.project.id",
        "domain_id": "scope.domain.id",
    }
    return {aliases.get(key, key): value for key, value in filters.items()}


def _quota_proxy(connection: Any, service: QuotaService) -> Any:
    if service is QuotaService.COMPUTE:
        return cast(Any, connection.compute)
    if service is QuotaService.NETWORK:
        return cast(Any, connection.network)
    return cast(Any, connection.block_storage)


def _quota_defaults(proxy: Any, project_id: str, service: QuotaService) -> Any:
    if service is QuotaService.NETWORK:
        return proxy.get_quota_default(project_id)
    method = getattr(proxy, "get_quota_set_defaults", None)
    return method(project_id) if callable(method) else {}


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    return dict(to_dict()) if callable(to_dict) else {}


def _text(value: Any) -> str | None:
    return str(value) if value is not None else None


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None
