import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from dataclasses import replace
from datetime import UTC, datetime
from typing import Annotated, Any, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from vantage_bff.adapters.base import AdapterError
from vantage_bff.admin.adapter import AdminAdapter
from vantage_bff.admin.models import (
    AdminOperation,
    AdminQuota,
    AdminQuotaCollection,
    AdminScope,
    AdminScopeRequest,
    AdminScopeType,
    AdminSession,
    Confirmation,
    IdentityCreate,
    IdentityKind,
    IdentityPage,
    IdentityResource,
    IdentityUpdate,
    OperationAck,
    QuotaUpdate,
    RoleAssignmentCreate,
    RoleAssignmentPage,
)
from vantage_bff.cursors import CursorKey, MemoryCursorStore
from vantage_bff.models import PageInfo, QuotaService, WidgetError
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
from vantage_bff.sessions import SessionRecord, SessionStore, new_scope_namespace, rotated_session

ErrorFactory = Callable[..., Exception]
SessionDependency = Callable[..., Awaitable[SessionRecord]]
Mutation = Callable[[], Coroutine[Any, Any, Any]]
_PAGE_SIZES = {10, 25, 50, 100}


def build_admin_router(
    *,
    current_session: SessionDependency,
    csrf_session: SessionDependency,
    error: ErrorFactory,
    set_session_cookie: Callable[[Response, SessionRecord], None],
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/admin", tags=["Administration"])

    def admin_scope(record: SessionRecord) -> AdminScope:
        if record.active_admin_scope is None:
            raise error(
                409,
                "admin_scope_required",
                "Administrator scope required",
                "Select an explicit system, domain, or project administrator scope",
            )
        return record.active_admin_scope

    def adapter(request: Request) -> AdminAdapter:
        return cast(AdminAdapter, request.app.state.adapter)

    def cursor_store(request: Request) -> MemoryCursorStore:
        return cast(MemoryCursorStore, request.app.state.instance_cursors)

    def operation_store(request: Request) -> OperationStore:
        return cast(OperationStore, request.app.state.operations)

    def operation_scope(record: SessionRecord) -> OperationScope:
        scope = admin_scope(record)
        return OperationScope(
            user_id=record.user.id,
            project_id=f"admin:{scope.type.value}:{scope.id}",
            region=str(record.auth_context.get("admin_region", "identity")),
        )

    async def fail(request: Request, record: SessionRecord, exc: AdapterError) -> NoReturn:
        if exc.status_code == 401:
            sessions = cast(SessionStore, request.app.state.sessions)
            await sessions.delete(record.id)
            await cursor_store(request).invalidate_namespace(record.scope_namespace)
            raise error(
                401,
                "unauthenticated",
                "Authentication required",
                "Session missing or expired",
                openstack_request_id=exc.request_id,
            ) from exc
        details = {
            400: (422, "admin_invalid", "Invalid administrator request"),
            403: (403, "admin_forbidden", "Administrator action denied by policy"),
            404: (404, "admin_not_found", "Administrator resource not found"),
            409: (409, "admin_conflict", "Administrator resource changed or conflicts"),
            429: (429, "admin_rate_limited", "Administrator request rate limited"),
        }
        status, code, detail = details.get(
            exc.status_code,
            (503, "admin_unavailable", "Administrator service temporarily unavailable"),
        )
        raise error(
            status,
            code,
            "Administrator request failed",
            detail,
            openstack_request_id=exc.request_id,
        ) from exc

    async def identity_page(
        request: Request,
        response: Response,
        record: SessionRecord,
        kind: IdentityKind | str,
        *,
        limit: int,
        page: int,
        name: str | None,
        filters: dict[str, str],
    ) -> tuple[list[Any], PageInfo]:
        if limit not in _PAGE_SIZES:
            raise error(422, "invalid_page_size", "Invalid page size", "Use 10, 25, 50, or 100")
        scope = admin_scope(record)
        query = tuple(sorted((key, value) for key, value in {"name": name, **filters}.items()))
        key = CursorKey(
            scope_namespace=record.scope_namespace,
            resource=f"admin:{scope.type.value}:{scope.id}:{kind}",
            query=(("limit", str(limit)), *query),
        )
        cursors = cursor_store(request)
        lease = await cursors.acquire(key, page)
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
                result = await adapter(request).admin_list(
                    record.auth_context,
                    scope,
                    kind,
                    limit=limit,
                    cursor=lease.marker,
                    name=name,
                    filters=filters,
                )
            except AdapterError as exc:
                await fail(request, record, exc)
            known_pages = await cursors.complete(lease, result.next_cursor)
            if known_pages is None:
                raise error(
                    409,
                    "page_cursor_changed",
                    "Administrator pages changed",
                    "A newer query replaced this response",
                )
            committed = True
            items = list(result.items)
            start = (page - 1) * limit
            if result.openstack_request_id:
                response.headers["X-OpenStack-Request-ID"] = result.openstack_request_id
            return items, PageInfo(
                number=page,
                size=limit,
                item_from=start + 1 if items else 0,
                item_to=start + len(items) if items else 0,
                total_items=None,
                total_pages=None,
                has_previous=page > 1,
                has_next=result.next_cursor is not None,
                navigable_pages=list(known_pages),
                openstack_request_id=result.openstack_request_id,
            )
        finally:
            if not committed:
                await cursors.abandon(lease)

    async def require_confirmation(
        supplied: str | None, expected: set[str], *, action: str
    ) -> None:
        if supplied is None or supplied not in expected:
            raise error(
                422,
                "confirmation_mismatch",
                "Confirmation required",
                f"Type the exact resource name or ID to {action}",
            )

    async def submit(
        request: Request,
        record: SessionRecord,
        *,
        idempotency_key: str | None,
        kind: str,
        target: OperationTarget,
        fingerprint_payload: dict[str, Any],
        mutation: Mutation,
    ) -> OperationAck:
        if not idempotency_key or not idempotency_key.strip():
            raise error(
                422,
                "idempotency_key_required",
                "Idempotency key required",
                "Supply a non-empty Idempotency-Key header",
            )
        scope = operation_scope(record)
        store = operation_store(request)
        try:
            begun = await store.begin(
                scope=scope,
                idempotency_key=idempotency_key,
                fingerprint=operation_fingerprint(kind, fingerprint_payload),
                kind=kind,
                target=target,
                trace_id=request.state.trace_id,
            )
        except IdempotencyConflictError as exc:
            raise error(
                409,
                "idempotency_conflict",
                "Idempotency key conflict",
                "The key was already used with a different administrator command",
            ) from exc
        except OperationCapacityError as exc:
            raise error(
                503,
                "operation_capacity_exceeded",
                "Administrator command unavailable",
                "The operation store is at capacity",
            ) from exc
        if not begun.replayed:
            task = asyncio.create_task(run_mutation(store, scope, begun.operation, mutation))
            tasks = getattr(request.app.state, "admin_tasks", None)
            if not isinstance(tasks, set):
                tasks = set()
                request.app.state.admin_tasks = tasks
            tasks.add(task)
            task.add_done_callback(tasks.discard)
        return OperationAck(
            operation_id=begun.operation.id,
            status=begun.operation.status.value,
            trace_id=begun.operation.trace_id,
            replayed=begun.replayed,
        )

    @router.get("/session", response_model=AdminSession)
    async def get_admin_session(
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> AdminSession:
        if record.admin_scopes:
            return AdminSession(
                available_scopes=list(record.admin_scopes),
                active_scope=record.active_admin_scope,
            )
        candidates = [
            AdminScope(type=AdminScopeType.SYSTEM, id="all", name="System")
        ]
        if record.user.domain_id:
            candidates.append(
                AdminScope(
                    type=AdminScopeType.DOMAIN,
                    id=record.user.domain_id,
                    name=record.user.domain_id,
                )
            )
        scopes: list[AdminScope] = []
        auth_context = record.auth_context
        for candidate in candidates:
            try:
                result = await adapter(request).admin_scope(
                    auth_context, candidate, record.regions[0]
                )
            except AdapterError as exc:
                if exc.status_code == 401:
                    await fail(request, record, exc)
                continue
            scopes.append(result.scope)
            auth_context = result.auth_context
        if not scopes:
            raise error(
                403,
                "admin_workspace_forbidden",
                "Administrator workspace unavailable",
                "No policy-authorized administrator scope was discovered for this session",
            )
        updated = replace(
            record,
            auth_context=auth_context,
            admin_scopes=tuple(scopes),
        )
        sessions = cast(SessionStore, request.app.state.sessions)
        await sessions.create(updated)
        return AdminSession(available_scopes=scopes, active_scope=None)

    @router.put("/scope", response_model=AdminSession)
    async def put_admin_scope(
        payload: AdminScopeRequest,
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(csrf_session)],
    ) -> AdminSession:
        requested = AdminScope(type=payload.type, id=payload.id, name=payload.id)
        try:
            result = await adapter(request).admin_scope(
                record.auth_context, requested, record.regions[0]
            )
        except AdapterError as exc:
            await fail(request, record, exc)
        changed = record.active_admin_scope != result.scope
        scopes_by_key = {
            (item.type, item.id): item for item in (*record.admin_scopes, result.scope)
        }
        scopes = tuple(scopes_by_key.values())
        updated = rotated_session(
            record,
            auth_context=result.auth_context,
            admin_scopes=scopes,
            active_admin_scope=result.scope,
            scope_namespace=new_scope_namespace() if changed else record.scope_namespace,
            expires_at=min(record.expires_at, result.expires_at or record.expires_at),
        )
        sessions = cast(SessionStore, request.app.state.sessions)
        if not await sessions.rotate(record.id, updated):
            raise error(401, "session_changed", "Authentication required", "Session changed")
        if changed:
            await cursor_store(request).invalidate_namespace(record.scope_namespace)
        set_session_cookie(response, updated)
        return AdminSession(available_scopes=list(scopes), active_scope=result.scope)

    @router.get("/identity/{kind}", response_model=IdentityPage)
    async def list_identity(
        kind: IdentityKind,
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
        domain_id: Annotated[str | None, Query(max_length=255)] = None,
        enabled: Annotated[bool | None, Query()] = None,
    ) -> IdentityPage:
        filters = {}
        if domain_id:
            filters["domain_id"] = domain_id
        if enabled is not None:
            filters["enabled"] = str(enabled).lower()
        items, page_info = await identity_page(
            request,
            response,
            record,
            kind,
            limit=limit,
            page=page,
            name=name.strip() if name and name.strip() else None,
            filters=filters,
        )
        return IdentityPage(items=[cast(IdentityResource, item) for item in items], page=page_info)

    @router.get("/identity/{kind}/{resource_id}", response_model=IdentityResource)
    async def get_identity(
        kind: IdentityKind,
        resource_id: str,
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> IdentityResource:
        scope = admin_scope(record)
        try:
            return await adapter(request).admin_get(
                record.auth_context, scope, kind, resource_id
            )
        except AdapterError as exc:
            await fail(request, record, exc)

    @router.post("/identity/{kind}", response_model=OperationAck, status_code=202)
    async def create_identity(
        kind: IdentityKind,
        payload: IdentityCreate,
        request: Request,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Confirm-Target")] = None,
    ) -> OperationAck:
        await require_confirmation(confirmation, {payload.name}, action="create this resource")
        scope = admin_scope(record)
        return await submit(
            request,
            record,
            idempotency_key=idempotency_key,
            kind=f"admin.identity.{kind}.create",
            target=OperationTarget(resource_type=kind, resource_name=payload.name),
            # The operation store retains only the resulting SHA-256 fingerprint. Including
            # the secret here prevents a reused key from replaying a different password.
            fingerprint_payload=payload.model_dump(mode="json"),
            mutation=lambda: adapter(request).admin_create(
                record.auth_context, scope, kind, payload
            ),
        )

    @router.patch("/identity/{kind}/{resource_id}", response_model=OperationAck, status_code=202)
    async def update_identity(
        kind: IdentityKind,
        resource_id: str,
        payload: IdentityUpdate,
        request: Request,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Confirm-Target")] = None,
    ) -> OperationAck:
        await require_confirmation(confirmation, {resource_id}, action="change this resource")
        scope = admin_scope(record)
        return await submit(
            request,
            record,
            idempotency_key=idempotency_key,
            kind=f"admin.identity.{kind}.update",
            target=OperationTarget(resource_type=kind, resource_id=resource_id),
            fingerprint_payload={
                "id": resource_id,
                **payload.model_dump(mode="json"),
            },
            mutation=lambda: adapter(request).admin_update(
                record.auth_context, scope, kind, resource_id, payload
            ),
        )

    @router.delete("/identity/{kind}/{resource_id}", response_model=OperationAck, status_code=202)
    async def delete_identity(
        kind: IdentityKind,
        resource_id: str,
        payload: Confirmation,
        request: Request,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationAck:
        scope = admin_scope(record)
        try:
            resource = await adapter(request).admin_get(
                record.auth_context, scope, kind, resource_id
            )
        except AdapterError as exc:
            await fail(request, record, exc)
        await require_confirmation(
            payload.confirm, {resource.id, resource.name}, action="delete this resource"
        )
        return await submit(
            request,
            record,
            idempotency_key=idempotency_key,
            kind=f"admin.identity.{kind}.delete",
            target=OperationTarget(
                resource_type=kind, resource_id=resource.id, resource_name=resource.name
            ),
            fingerprint_payload={"id": resource_id},
            mutation=lambda: adapter(request).admin_delete(
                record.auth_context, scope, kind, resource_id
            ),
        )

    @router.get("/projects/{project_id}/context", response_model=IdentityResource)
    async def project_context(
        project_id: str,
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> IdentityResource:
        scope = admin_scope(record)
        try:
            return await adapter(request).admin_get(
                record.auth_context, scope, "projects", project_id
            )
        except AdapterError as exc:
            await fail(request, record, exc)

    @router.get("/role-assignments", response_model=RoleAssignmentPage)
    async def list_assignments(
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        user_id: str | None = None,
        group_id: str | None = None,
        role_id: str | None = None,
        project_id: str | None = None,
        domain_id: str | None = None,
    ) -> RoleAssignmentPage:
        filters = {
            key: value for key, value in {
                "user_id": user_id,
                "group_id": group_id,
                "role_id": role_id,
                "project_id": project_id,
                "domain_id": domain_id,
            }.items() if value
        }
        items, page_info = await identity_page(
            request,
            response,
            record,
            "role-assignments",
            limit=limit,
            page=page,
            name=None,
            filters=filters,
        )
        return RoleAssignmentPage(items=items, page=page_info)

    @router.post("/role-assignments", response_model=OperationAck, status_code=202)
    async def grant_role(
        payload: RoleAssignmentCreate,
        request: Request,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Confirm-Target")] = None,
    ) -> OperationAck:
        await require_confirmation(
            confirmation, {payload.actor_id}, action="grant this role assignment"
        )
        scope = admin_scope(record)
        return await submit(
            request,
            record,
            idempotency_key=idempotency_key,
            kind="admin.role_assignment.grant",
            target=OperationTarget(
                resource_type="role-assignment", resource_id=payload.actor_id
            ),
            fingerprint_payload=payload.model_dump(mode="json"),
            mutation=lambda: adapter(request).admin_grant_role(
                record.auth_context, scope, payload
            ),
        )

    @router.delete(
        "/role-assignments/{assignment_id}", response_model=OperationAck, status_code=202
    )
    async def revoke_role(
        assignment_id: str,
        payload: Confirmation,
        request: Request,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationAck:
        await require_confirmation(
            payload.confirm, {assignment_id}, action="revoke this role assignment"
        )
        scope = admin_scope(record)
        return await submit(
            request,
            record,
            idempotency_key=idempotency_key,
            kind="admin.role_assignment.revoke",
            target=OperationTarget(resource_type="role-assignment", resource_id=assignment_id),
            fingerprint_payload={"id": assignment_id},
            mutation=lambda: adapter(request).admin_revoke_role(
                record.auth_context, scope, assignment_id
            ),
        )

    @router.get("/projects/{project_id}/quotas", response_model=AdminQuotaCollection)
    async def get_quotas(
        project_id: str,
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
        service: Annotated[QuotaService | None, Query()] = None,
        user_id: Annotated[str | None, Query(max_length=255)] = None,
    ) -> AdminQuotaCollection:
        scope = admin_scope(record)
        services = (service,) if service else tuple(QuotaService)
        if user_id and service not in {None, QuotaService.COMPUTE}:
            raise error(
                422,
                "user_quota_unsupported",
                "User quota unsupported",
                "User-specific quotas are supported only by Compute",
            )
        results = await asyncio.gather(
            *(
                adapter(request).admin_quotas(
                    record.auth_context,
                    scope,
                    project_id,
                    item,
                    user_id if item is QuotaService.COMPUTE else None,
                )
                for item in services
            ),
            return_exceptions=True,
        )
        quotas: list[AdminQuota] = []
        partial_errors: list[WidgetError] = []
        for item, result in zip(services, results, strict=True):
            if not isinstance(result, BaseException):
                quotas.extend(result)
                continue
            if isinstance(result, AdapterError) and result.status_code == 401:
                await fail(request, record, result)
            request_id = result.request_id if isinstance(result, AdapterError) else None
            partial: WidgetError = {
                "code": f"{item.value}_admin_quota_unavailable",
                "message": f"{item.value.capitalize()} quota data is unavailable",
            }
            if request_id:
                partial["openstack_request_id"] = request_id
            partial_errors.append(partial)
        return AdminQuotaCollection(
            project_id=project_id,
            generated_at=datetime.now(UTC),
            quotas=quotas,
            partial_errors=partial_errors,
        )

    @router.put(
        "/projects/{project_id}/quotas/{service}", response_model=OperationAck, status_code=202
    )
    async def put_quotas(
        project_id: str,
        service: QuotaService,
        payload: QuotaUpdate,
        request: Request,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        confirmation: Annotated[str | None, Header(alias="X-Confirm-Target")] = None,
    ) -> OperationAck:
        await require_confirmation(confirmation, {project_id}, action="change these quotas")
        scope = admin_scope(record)
        return await submit(
            request,
            record,
            idempotency_key=idempotency_key,
            kind=f"admin.quota.{service.value}.update",
            target=OperationTarget(resource_type="project-quota", resource_id=project_id),
            fingerprint_payload={"project_id": project_id, **payload.model_dump(mode="json")},
            mutation=lambda: adapter(request).admin_update_quotas(
                record.auth_context, scope, project_id, service, payload
            ),
        )

    @router.delete(
        "/projects/{project_id}/quotas/{service}", response_model=OperationAck, status_code=202
    )
    async def delete_quotas(
        project_id: str,
        service: QuotaService,
        payload: Confirmation,
        request: Request,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
        user_id: Annotated[str | None, Query(max_length=255)] = None,
    ) -> OperationAck:
        await require_confirmation(payload.confirm, {project_id}, action="delete quota overrides")
        scope = admin_scope(record)
        return await submit(
            request,
            record,
            idempotency_key=idempotency_key,
            kind=f"admin.quota.{service.value}.reset",
            target=OperationTarget(resource_type="project-quota", resource_id=project_id),
            fingerprint_payload={"project_id": project_id, "user_id": user_id},
            mutation=lambda: adapter(request).admin_reset_quotas(
                record.auth_context, scope, project_id, service, user_id
            ),
        )

    @router.get("/operations/{operation_id}", response_model=AdminOperation)
    async def get_operation(
        operation_id: UUID,
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> AdminOperation:
        snapshot = await operation_store(request).get(operation_scope(record), operation_id)
        if snapshot is None:
            raise error(
                404,
                "operation_not_found",
                "Operation not found",
                "The operation does not exist in the active administrator scope",
            )
        return operation_model(snapshot)

    return router


async def run_mutation(
    store: OperationStore,
    scope: OperationScope,
    operation: OperationSnapshot,
    mutation: Mutation,
) -> None:
    await store.mark_running(scope, operation.id)
    try:
        result = await mutation()
        request_ids = tuple(getattr(result, "openstack_request_ids", ()))
        resource = getattr(result, "resource", None)
        target = operation.target
        if resource is not None:
            target = OperationTarget(
                resource_type=target.resource_type,
                resource_id=getattr(resource, "id", target.resource_id),
                resource_name=getattr(resource, "name", target.resource_name),
            )
        await store.succeed(
            scope, operation.id, target=target, openstack_request_ids=request_ids
        )
    except AdapterError as exc:
        status = exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 422, 429} else 503
        await store.fail(
            scope,
            operation.id,
            problem=OperationProblem(
                status=status,
                code="admin_forbidden" if status == 403 else "admin_mutation_failed",
                title="Administrator operation failed",
                detail="OpenStack rejected the administrator operation",
                openstack_request_id=exc.request_id,
            ),
        )
    except Exception:
        await store.fail(
            scope,
            operation.id,
            problem=OperationProblem(
                status=503,
                code="admin_mutation_failed",
                title="Administrator operation failed",
                detail="The administrator operation could not be completed",
            ),
        )


def operation_model(snapshot: OperationSnapshot) -> AdminOperation:
    problem = None
    if snapshot.problem:
        problem = {
            "status": snapshot.problem.status,
            "code": snapshot.problem.code,
            "title": snapshot.problem.title,
            "detail": snapshot.problem.detail,
            "openstack_request_id": snapshot.problem.openstack_request_id,
        }
    return AdminOperation(
        id=snapshot.id,
        kind=snapshot.kind,
        status=snapshot.status.value,
        submitted_at=snapshot.submitted_at,
        updated_at=snapshot.updated_at,
        target_type=snapshot.target.resource_type,
        target_id=snapshot.target.resource_id,
        target_name=snapshot.target.resource_name,
        trace_id=snapshot.trace_id,
        openstack_request_ids=list(snapshot.openstack_request_ids),
        problem=problem,
    )
