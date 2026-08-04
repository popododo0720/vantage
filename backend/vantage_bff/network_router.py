from __future__ import annotations

import asyncio
import hmac
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, NoReturn, Protocol, cast
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request, Response

from vantage_bff.adapters.base import AdapterError, AdapterTimeoutError
from vantage_bff.adapters.network_base import (
    NetworkMutationResult,
    NetworkServicesAdapter,
)
from vantage_bff.cursors import CursorKey, MemoryCursorStore
from vantage_bff.models import PageInfo
from vantage_bff.network_contracts import RESOURCE_SPECS, resource_contract, validate_attributes
from vantage_bff.network_models import (
    DeletePreview,
    NetworkCapabilities,
    NetworkResource,
    NetworkResourcePage,
    OperationProblemResponse,
    OperationResponse,
    ResourceActionRequest,
    ResourceDeleteRequest,
    ResourceKind,
    ResourceMutationRequest,
)
from vantage_bff.operations import (
    IdempotencyConflictError,
    OperationCapacityError,
    OperationProblem,
    OperationScope,
    OperationSnapshot,
    OperationStore,
    OperationTarget,
    operation_fingerprint,
)
from vantage_bff.sessions import SessionRecord, SessionStore


class ApiErrorFactory(Protocol):
    def __call__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str,
        *,
        openstack_request_id: str | None = None,
    ) -> Exception: ...


def create_network_router(api_error: ApiErrorFactory) -> APIRouter:
    router = APIRouter(prefix="/api/v1/network", tags=["Network Services"])

    def error(
        status: int,
        code: str,
        title: str,
        detail: str,
        *,
        request_id: str | None = None,
    ) -> Exception:
        return api_error(
            status,
            code,
            title,
            detail,
            openstack_request_id=request_id,
        )

    async def session(request: Request) -> SessionRecord:
        settings = request.app.state.settings
        session_id = request.cookies.get(settings.cookie_name)
        if not session_id:
            raise error(
                401, "unauthenticated", "Authentication required", "Session missing or expired"
            )
        sessions = cast(SessionStore, request.app.state.sessions)
        record = await sessions.get(session_id)
        if record is None:
            raise error(
                401, "unauthenticated", "Authentication required", "Session missing or expired"
            )
        if record.active_scope is None:
            raise error(
                409,
                "active_scope_required",
                "Project scope required",
                "Select a project and region before requesting project resources",
            )
        return record

    async def csrf_session(request: Request) -> SessionRecord:
        record = await session(request)
        token = request.headers.get("X-CSRF-Token")
        if not token or not hmac.compare_digest(token, record.csrf_token):
            raise error(403, "csrf_invalid", "Request rejected", "CSRF token is missing or invalid")
        return record

    def adapter(request: Request) -> NetworkServicesAdapter:
        value = request.app.state.network_adapter
        if value is None:
            raise error(
                503,
                "network_adapter_unavailable",
                "Network service unavailable",
                "The configured OpenStack adapter does not provide network services",
            )
        return cast(NetworkServicesAdapter, value)

    def cursors(request: Request) -> MemoryCursorStore:
        return cast(MemoryCursorStore, request.app.state.instance_cursors)

    def scope(record: SessionRecord) -> tuple[str, str]:
        assert record.active_scope is not None
        return record.active_scope.project.id, record.active_scope.region

    async def invalidate_session(request: Request, record: SessionRecord) -> None:
        await cast(SessionStore, request.app.state.sessions).delete(record.id)
        await cursors(request).invalidate_namespace(record.scope_namespace)

    async def raise_adapter_error(
        request: Request,
        record: SessionRecord,
        exc: AdapterError,
        kind: ResourceKind,
        *,
        list_request: bool,
        cursor_key: CursorKey | None = None,
        marker_bound: bool = False,
    ) -> NoReturn:
        label = kind.value.replace("_", " ")
        if isinstance(exc, AdapterTimeoutError) or exc.status_code == 504:
            raise error(
                504,
                "network_service_timeout",
                "OpenStack request timed out",
                "The network service did not respond in time",
                request_id=exc.request_id,
            ) from exc
        if exc.status_code == 401:
            await invalidate_session(request, record)
            raise error(
                401,
                "unauthenticated",
                "Authentication required",
                "Session missing or expired",
                request_id=exc.request_id,
            ) from exc
        if list_request and marker_bound and exc.status_code in {400, 404, 409}:
            if cursor_key is not None:
                await cursors(request).invalidate(cursor_key)
            raise error(
                409,
                "page_cursor_unavailable",
                "Page no longer available",
                "Return to page 1 to rebuild the resource page sequence",
                request_id=exc.request_id,
            ) from exc
        if exc.status_code == 400:
            raise error(
                422,
                "invalid_network_request",
                "Invalid network request",
                "OpenStack rejected one or more fields or filters",
                request_id=exc.request_id,
            ) from exc
        if exc.status_code == 403:
            raise error(
                403,
                "network_policy_forbidden",
                f"{label.title()} unavailable",
                "OpenStack policy denied this request",
                request_id=exc.request_id,
            ) from exc
        if exc.status_code == 404:
            raise error(
                404,
                "network_resource_not_found",
                f"{label.title()} unavailable",
                "The resource is unavailable in the active project",
                request_id=exc.request_id,
            ) from exc
        if exc.status_code == 409:
            raise error(
                409,
                "network_resource_conflict",
                f"{label.title()} changed",
                "The resource state, revision, or dependencies prevent this operation",
                request_id=exc.request_id,
            ) from exc
        if exc.status_code == 429:
            raise error(
                429,
                "network_rate_limited",
                "Network request rate limited",
                "The OpenStack service temporarily rate limited this request",
                request_id=exc.request_id,
            ) from exc
        raise error(
            503,
            "network_service_unavailable",
            "Network service temporarily unavailable",
            "The OpenStack service is temporarily unavailable",
            request_id=exc.request_id,
        ) from exc

    def validate_parent(kind: ResourceKind, parent_id: str | None) -> None:
        if RESOURCE_SPECS[kind].parent_required and not parent_id:
            raise error(
                422,
                "parent_required",
                "Parent resource required",
                f"{kind.value} requires parent_id",
            )

    def adapter_parent(
        kind: ResourceKind, parent_id: str | None, rule_type: str | None
    ) -> str | None:
        if kind is not ResourceKind.QOS_RULE:
            return parent_id
        if not rule_type:
            raise error(
                422,
                "qos_rule_type_required",
                "QoS rule type required",
                "Select one advertised QoS rule type",
            )
        return f"{rule_type}:{parent_id}"

    def validate_payload(
        kind: ResourceKind, payload: ResourceMutationRequest, create: bool
    ) -> None:
        validate_parent(kind, payload.parent_id)
        unknown, missing, admin_only = validate_attributes(
            kind, cast(dict[str, object], payload.attributes), create=create
        )
        if admin_only:
            fields = ", ".join(sorted(admin_only))
            raise error(
                403,
                "admin_scope_required",
                "Administrator scope required",
                f"Project routes cannot change administrator-only fields: {fields}",
            )
        if unknown:
            fields = ", ".join(sorted(unknown))
            raise error(
                422,
                "unsupported_network_fields",
                "Unsupported fields",
                f"These fields are not mutable for {kind.value}: {fields}",
            )
        if missing:
            fields = ", ".join(sorted(missing))
            raise error(
                422,
                "required_network_fields_missing",
                "Required fields missing",
                f"Required fields: {fields}",
            )
        if create and kind is ResourceKind.LOAD_BALANCER and not any(
            payload.attributes.get(field)
            for field in ("vip_subnet_id", "vip_network_id", "vip_port_id")
        ):
            raise error(
                422,
                "load_balancer_vip_required",
                "Load balancer VIP source required",
                "Supply one of vip_subnet_id, vip_network_id, or vip_port_id",
            )
        if create and kind is ResourceKind.POOL and not any(
            payload.attributes.get(field) for field in ("listener_id", "load_balancer_id")
        ):
            raise error(
                422,
                "pool_parent_required",
                "Pool parent required",
                "Supply listener_id or load_balancer_id",
            )

    @router.get("/capabilities", response_model=NetworkCapabilities)
    async def capabilities(request: Request) -> NetworkCapabilities:
        record = await session(request)
        project_id, region = scope(record)
        try:
            result = await asyncio.wait_for(
                adapter(request).network_capabilities(record.auth_context, project_id, region),
                timeout=request.app.state.settings.network_source_timeout_seconds,
            )
        except TimeoutError:
            await raise_adapter_error(
                request,
                record,
                AdapterTimeoutError(),
                ResourceKind.NETWORK,
                list_request=False,
            )
        except AdapterError as exc:
            await raise_adapter_error(
                request, record, exc, ResourceKind.NETWORK, list_request=False
            )
        return NetworkCapabilities(
            neutron=result.neutron,
            octavia=result.octavia,
            resources=[
                resource_contract(kind, neutron=result.neutron, octavia=result.octavia)
                for kind in ResourceKind
            ],
        )

    @router.get("/resources/{kind}", response_model=NetworkResourcePage)
    async def list_resources(
        kind: ResourceKind,
        request: Request,
        response: Response,
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        parent_id: Annotated[str | None, Query(max_length=255)] = None,
        name: Annotated[str | None, Query(max_length=255)] = None,
        status: Annotated[str | None, Query(max_length=64)] = None,
        network_id: Annotated[str | None, Query(max_length=255)] = None,
        rule_type: Annotated[str | None, Query(max_length=64)] = None,
    ) -> NetworkResourcePage:
        if limit not in {10, 25, 50, 100}:
            raise error(
                422,
                "invalid_page_size",
                "Invalid page size",
                "Allowed values are 10, 25, 50, and 100",
            )
        validate_parent(kind, parent_id)
        if kind is ResourceKind.QOS_RULE and not rule_type:
            raise error(
                422,
                "qos_rule_type_required",
                "QoS rule type required",
                "Select one advertised QoS rule type",
            )
        record = await session(request)
        project_id, region = scope(record)
        filters = {
            key: value.strip()
            for key, value in {
                "name": name,
                "status": status,
                "network_id": network_id,
                "rule_type": rule_type,
            }.items()
            if value is not None and value.strip()
        }
        key = CursorKey(
            scope_namespace=record.scope_namespace,
            resource=f"network:{kind.value}",
            query=(
                ("limit", str(limit)),
                ("parent_id", parent_id),
                *((field, value) for field, value in sorted(filters.items())),
            ),
        )
        lease = await cursors(request).acquire(key, page)
        if lease is None:
            raise error(
                409,
                "page_cursor_unavailable",
                "Page not available yet",
                "Open the preceding page before requesting this page",
            )
        committed = False
        try:
            try:
                result = await asyncio.wait_for(
                    adapter(request).list_network_resources(
                        record.auth_context,
                        project_id,
                        region,
                        kind,
                        limit=limit + 1,
                        marker=lease.marker,
                        parent_id=parent_id,
                        filters=filters,
                    ),
                    timeout=request.app.state.settings.network_source_timeout_seconds,
                )
            except TimeoutError:
                await raise_adapter_error(
                    request,
                    record,
                    AdapterTimeoutError(),
                    kind,
                    list_request=True,
                    cursor_key=key,
                    marker_bound=lease.marker is not None,
                )
            except AdapterError as exc:
                await raise_adapter_error(
                    request,
                    record,
                    exc,
                    kind,
                    list_request=True,
                    cursor_key=key,
                    marker_bound=lease.marker is not None,
                )
            visible = list(result.items[:limit])
            has_next = len(result.items) > limit or result.has_next
            next_marker = visible[-1].id if visible and has_next else None
            known = await cursors(request).complete(lease, next_marker)
            if known is None:
                raise error(
                    409,
                    "page_cursor_changed",
                    "Resource pages changed",
                    "A newer page refresh replaced this response",
                )
            committed = True
            has_next = has_next and page + 1 in known
            start = (page - 1) * limit
            if result.openstack_request_id:
                response.headers["X-OpenStack-Request-ID"] = result.openstack_request_id
            return NetworkResourcePage(
                items=visible,
                page=PageInfo(
                    number=page,
                    size=limit,
                    item_from=start + 1 if visible else 0,
                    item_to=start + len(visible) if visible else 0,
                    total_items=None,
                    total_pages=None,
                    has_previous=page > 1,
                    has_next=has_next,
                    navigable_pages=_pages(page, max(known)),
                    openstack_request_id=result.openstack_request_id,
                ),
            )
        finally:
            if not committed:
                await cursors(request).abandon(lease)

    @router.get("/resources/{kind}/{resource_id}", response_model=NetworkResource)
    async def get_resource(
        kind: ResourceKind,
        resource_id: str,
        request: Request,
        response: Response,
        parent_id: Annotated[str | None, Query(max_length=255)] = None,
        rule_type: Annotated[str | None, Query(max_length=64)] = None,
    ) -> NetworkResource:
        validate_parent(kind, parent_id)
        record = await session(request)
        project_id, region = scope(record)
        try:
            result = await asyncio.wait_for(
                adapter(request).get_network_resource(
                    record.auth_context,
                    project_id,
                    region,
                    kind,
                    resource_id,
                    parent_id=adapter_parent(kind, parent_id, rule_type),
                ),
                timeout=request.app.state.settings.network_source_timeout_seconds,
            )
        except TimeoutError:
            await raise_adapter_error(
                request,
                record,
                AdapterTimeoutError(),
                kind,
                list_request=False,
            )
        except AdapterError as exc:
            await raise_adapter_error(request, record, exc, kind, list_request=False)
        if result.openstack_request_id:
            response.headers["X-OpenStack-Request-ID"] = result.openstack_request_id
        return result

    @router.get("/resources/{kind}/{resource_id}/delete-preview", response_model=DeletePreview)
    async def delete_preview(
        kind: ResourceKind,
        resource_id: str,
        request: Request,
        parent_id: Annotated[str | None, Query(max_length=255)] = None,
        rule_type: Annotated[str | None, Query(max_length=64)] = None,
    ) -> DeletePreview:
        resource = await get_resource(kind, resource_id, request, Response(), parent_id, rule_type)
        raw_dependencies = resource.attributes.get("dependencies", [])
        dependencies = [
            {str(key): str(value) for key, value in item.items()}
            for item in raw_dependencies
            if isinstance(item, dict)
        ][:100]
        return DeletePreview(
            resource=resource,
            dependencies=dependencies,
            confirmation_value=resource.name or resource.id,
        )

    async def begin_mutation(
        request: Request,
        record: SessionRecord,
        *,
        kind: ResourceKind,
        action: str,
        target_id: str | None,
        target_name: str | None,
        idempotency_key: str | None,
        fingerprint_payload: dict[str, Any],
        execute: Callable[[], Awaitable[NetworkMutationResult]],
    ) -> OperationResponse:
        if not idempotency_key or not idempotency_key.strip() or len(idempotency_key) > 255:
            raise error(
                422,
                "idempotency_key_required",
                "Idempotency key required",
                "Provide a non-empty Idempotency-Key header of at most 255 characters",
            )
        project_id, region = scope(record)
        operation_scope = OperationScope(record.user.id, project_id, region)
        store = cast(OperationStore, request.app.state.operations)
        operation_kind = f"{kind.value}.{action}"
        try:
            begun = await store.begin(
                scope=operation_scope,
                idempotency_key=idempotency_key,
                fingerprint=operation_fingerprint(operation_kind, fingerprint_payload),
                kind=operation_kind,
                target=OperationTarget(kind.value, target_id, target_name),
                trace_id=request.state.trace_id,
            )
        except IdempotencyConflictError as exc:
            raise error(
                409,
                "idempotency_conflict",
                "Idempotency key conflict",
                "This key was already used with a different network operation",
            ) from exc
        except OperationCapacityError as exc:
            raise error(
                503,
                "operation_capacity_exceeded",
                "Operation tracking unavailable",
                "Try the request again later",
            ) from exc
        if not begun.replayed:
            asyncio.create_task(
                execute_operation(
                    request,
                    record,
                    operation_scope,
                    begun.operation,
                    execute,
                )
            )
        return operation_response(begun.operation)

    async def execute_operation(
        request: Request,
        record: SessionRecord,
        operation_scope: OperationScope,
        operation: OperationSnapshot,
        execute: Callable[[], Awaitable[NetworkMutationResult]],
    ) -> None:
        store = cast(OperationStore, request.app.state.operations)
        await store.mark_running(operation_scope, operation.id)
        try:
            result = await asyncio.wait_for(
                execute(),
                timeout=request.app.state.settings.network_source_timeout_seconds,
            )
        except TimeoutError:
            await store.fail(
                operation_scope,
                operation.id,
                problem=_operation_problem(AdapterTimeoutError()),
            )
            return
        except AdapterError as exc:
            if exc.status_code == 401:
                await invalidate_session(request, record)
            problem = _operation_problem(exc)
            await store.fail(
                operation_scope,
                operation.id,
                problem=problem,
                openstack_request_ids=((exc.request_id,) if exc.request_id else ()),
            )
            return
        target = None
        if result.resource is not None:
            target = OperationTarget(
                result.resource.resource_type.value,
                result.resource.id,
                result.resource.name,
            )
        await store.succeed(
            operation_scope,
            operation.id,
            target=target,
            openstack_request_ids=(
                (result.openstack_request_id,) if result.openstack_request_id else ()
            ),
        )
        await cursors(request).invalidate_namespace(record.scope_namespace)

    @router.post("/resources/{kind}", response_model=OperationResponse, status_code=202)
    async def create_resource(
        kind: ResourceKind,
        payload: ResourceMutationRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        validate_payload(kind, payload, True)
        record = await csrf_session(request)
        project_id, region = scope(record)
        return await begin_mutation(
            request,
            record,
            kind=kind,
            action="create",
            target_id=None,
            target_name=_string(payload.attributes.get("name")),
            idempotency_key=idempotency_key,
            fingerprint_payload=payload.model_dump(mode="json"),
            execute=lambda: adapter(request).create_network_resource(
                record.auth_context,
                project_id,
                region,
                kind,
                parent_id=payload.parent_id,
                attributes=payload.attributes,
            ),
        )

    @router.patch(
        "/resources/{kind}/{resource_id}", response_model=OperationResponse, status_code=202
    )
    async def update_resource(
        kind: ResourceKind,
        resource_id: str,
        payload: ResourceMutationRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        validate_payload(kind, payload, False)
        if not payload.attributes:
            raise error(
                422, "empty_update", "No changes supplied", "Supply at least one mutable field"
            )
        record = await csrf_session(request)
        project_id, region = scope(record)
        return await begin_mutation(
            request,
            record,
            kind=kind,
            action="update",
            target_id=resource_id,
            target_name=_string(payload.attributes.get("name")),
            idempotency_key=idempotency_key,
            fingerprint_payload={"resource_id": resource_id, **payload.model_dump(mode="json")},
            execute=lambda: adapter(request).update_network_resource(
                record.auth_context,
                project_id,
                region,
                kind,
                resource_id,
                parent_id=adapter_parent(kind, payload.parent_id, payload.rule_type),
                attributes=payload.attributes,
                revision_number=payload.revision_number,
            ),
        )

    @router.post(
        "/resources/{kind}/{resource_id}/delete",
        response_model=OperationResponse,
        status_code=202,
    )
    async def delete_resource(
        kind: ResourceKind,
        resource_id: str,
        payload: ResourceDeleteRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        validate_parent(kind, payload.parent_id)
        record = await csrf_session(request)
        project_id, region = scope(record)
        try:
            current = await asyncio.wait_for(
                adapter(request).get_network_resource(
                    record.auth_context,
                    project_id,
                    region,
                    kind,
                    resource_id,
                    parent_id=adapter_parent(kind, payload.parent_id, payload.rule_type),
                ),
                timeout=request.app.state.settings.network_source_timeout_seconds,
            )
        except TimeoutError:
            await raise_adapter_error(
                request,
                record,
                AdapterTimeoutError(),
                kind,
                list_request=False,
            )
        except AdapterError as exc:
            await raise_adapter_error(request, record, exc, kind, list_request=False)
        if payload.confirmation not in {current.id, current.name}:
            raise error(
                422,
                "delete_confirmation_mismatch",
                "Delete confirmation does not match",
                "Type the exact resource name or ID",
            )
        return await begin_mutation(
            request,
            record,
            kind=kind,
            action="delete",
            target_id=resource_id,
            target_name=current.name,
            idempotency_key=idempotency_key,
            fingerprint_payload={"resource_id": resource_id, **payload.model_dump(mode="json")},
            execute=lambda: adapter(request).delete_network_resource(
                record.auth_context,
                project_id,
                region,
                kind,
                resource_id,
                parent_id=adapter_parent(kind, payload.parent_id, payload.rule_type),
                revision_number=payload.revision_number,
                cascade=payload.cascade,
            ),
        )

    @router.post(
        "/resources/{kind}/{resource_id}/actions",
        response_model=OperationResponse,
        status_code=202,
    )
    async def resource_action(
        kind: ResourceKind,
        resource_id: str,
        payload: ResourceActionRequest,
        request: Request,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        if payload.action not in RESOURCE_SPECS[kind].actions:
            raise error(
                422,
                "unsupported_network_action",
                "Unsupported action",
                f"{payload.action} is not available for {kind.value}",
            )
        record = await csrf_session(request)
        project_id, region = scope(record)
        return await begin_mutation(
            request,
            record,
            kind=kind,
            action=payload.action,
            target_id=resource_id,
            target_name=None,
            idempotency_key=idempotency_key,
            fingerprint_payload={"resource_id": resource_id, **payload.model_dump(mode="json")},
            execute=lambda: adapter(request).run_network_action(
                record.auth_context,
                project_id,
                region,
                kind,
                resource_id,
                action=payload.action,
                parameters=payload.parameters,
                revision_number=payload.revision_number,
            ),
        )

    @router.get("/operations/{operation_id}", response_model=OperationResponse)
    async def get_operation(operation_id: UUID, request: Request) -> OperationResponse:
        record = await session(request)
        project_id, region = scope(record)
        store = cast(OperationStore, request.app.state.operations)
        snapshot = await store.get(OperationScope(record.user.id, project_id, region), operation_id)
        if snapshot is None:
            raise error(
                404,
                "operation_not_found",
                "Operation unavailable",
                "The operation is unavailable in the active project",
            )
        return operation_response(snapshot)

    return router


def operation_response(snapshot: OperationSnapshot) -> OperationResponse:
    problem = None
    if snapshot.problem is not None:
        problem = OperationProblemResponse(
            status=snapshot.problem.status,
            code=snapshot.problem.code,
            title=snapshot.problem.title,
            detail=snapshot.problem.detail,
            openstack_request_id=snapshot.problem.openstack_request_id,
        )
    return OperationResponse(
        id=snapshot.id,
        kind=snapshot.kind,
        status=snapshot.status.value,
        submitted_at=snapshot.submitted_at,
        updated_at=snapshot.updated_at,
        resource_type=snapshot.target.resource_type,
        resource_id=snapshot.target.resource_id,
        resource_name=snapshot.target.resource_name,
        trace_id=snapshot.trace_id,
        openstack_request_ids=list(snapshot.openstack_request_ids),
        problem=problem,
    )


def _operation_problem(exc: AdapterError) -> OperationProblem:
    status = exc.status_code
    if status == 401:
        values = ("unauthenticated", "Authentication required", "Session missing or expired")
    elif status == 403:
        values = (
            "network_policy_forbidden",
            "Permission denied",
            "OpenStack policy denied this operation",
        )
    elif status == 404:
        values = (
            "network_resource_not_found",
            "Resource unavailable",
            "The resource is unavailable in the active project",
        )
    elif status == 409:
        values = (
            "network_resource_conflict",
            "Resource conflict",
            "The resource state, revision, or dependencies prevent this operation",
        )
    elif status == 429:
        values = (
            "network_rate_limited",
            "Operation rate limited",
            "OpenStack temporarily rate limited this operation",
        )
    elif status == 400:
        status = 422
        values = (
            "invalid_network_request",
            "Invalid network request",
            "OpenStack rejected the operation",
        )
    else:
        status = 504 if status == 504 else 503
        values = (
            "network_service_unavailable",
            "Network service unavailable",
            "The OpenStack service did not complete this operation",
        )
    return OperationProblem(
        status=status,
        code=values[0],
        title=values[1],
        detail=values[2],
        openstack_request_id=exc.request_id,
    )


def _pages(current: int, total: int) -> list[int]:
    if total <= 7:
        return list(range(1, total + 1))
    if current <= 4:
        middle = range(2, 6)
    elif current >= total - 3:
        middle = range(total - 4, total)
    else:
        middle = range(current - 1, current + 2)
    return [1, *middle, total]


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None
