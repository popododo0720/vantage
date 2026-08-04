import asyncio
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request, Response

from vantage_bff.adapters.base import AdapterError, AdapterTimeoutError
from vantage_bff.cursors import CursorKey, MemoryCursorStore
from vantage_bff.models import PageInfo, Scope
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
from vantage_bff.sessions import SessionRecord
from vantage_bff.storage.base import StorageAdapter
from vantage_bff.storage.models import (
    BackupActionRequest,
    BackupCreate,
    BackupImport,
    BackupPatch,
    ManagedVolumeCreate,
    OperationView,
    QosSpecWrite,
    ServiceActionRequest,
    SnapshotActionRequest,
    SnapshotCreate,
    SnapshotPatch,
    StoragePage,
    StorageResourceKind,
    StorageSort,
    VolumeActionRequest,
    VolumeCreate,
    VolumePatch,
    VolumeTypeWrite,
)

ErrorFactory = Callable[..., Exception]
SessionDependency = Callable[..., Awaitable[SessionRecord]]
ScopeResolver = Callable[[SessionRecord], Scope]
PageNavigator = Callable[[int, int], list[int]]


def create_storage_router(
    *,
    current_session: SessionDependency,
    csrf_session: SessionDependency,
    active_scope: ScopeResolver,
    error: ErrorFactory,
    navigable_pages: PageNavigator,
    timeout_seconds: float,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["storage"])

    def adapter(request: Request) -> StorageAdapter:
        return cast(StorageAdapter, request.app.state.storage_adapter)

    def operation_store(request: Request) -> OperationStore:
        return cast(OperationStore, request.app.state.operations)

    def cursors(request: Request) -> MemoryCursorStore:
        return cast(MemoryCursorStore, request.app.state.instance_cursors)

    async def storage_error(
        request: Request,
        record: SessionRecord,
        exc: AdapterError,
        *,
        resource: str,
        cursor_key: CursorKey | None = None,
        marker_bound: bool = False,
    ) -> NoReturn:
        if exc.status_code == 401:
            await request.app.state.sessions.delete(record.id)
            await cursors(request).invalidate_namespace(record.scope_namespace)
            raise error(
                401,
                "unauthenticated",
                "Authentication required",
                "Session missing or expired",
                openstack_request_id=exc.request_id,
            ) from exc
        if marker_bound and cursor_key and exc.status_code in {400, 404, 409}:
            await cursors(request).invalidate(cursor_key)
            raise error(
                409,
                "page_cursor_unavailable",
                "Page no longer available",
                f"Return to page 1 to rebuild the {resource} page sequence",
                openstack_request_id=exc.request_id,
            ) from exc
        status = exc.status_code
        if isinstance(exc, AdapterTimeoutError) or status == 504:
            raise error(
                504,
                "storage_timeout",
                "Storage request timed out",
                "The block storage service did not respond in time",
                openstack_request_id=exc.request_id,
            ) from exc
        if status == 400:
            raise error(
                422,
                "invalid_storage_request",
                "Invalid storage request",
                "Cinder rejected one or more request fields",
                openstack_request_id=exc.request_id,
            ) from exc
        if status == 403:
            raise error(
                403,
                "storage_forbidden",
                "Storage operation denied",
                "Cinder policy denied this request",
                openstack_request_id=exc.request_id,
            ) from exc
        if status == 404:
            raise error(
                404,
                "storage_not_found",
                "Storage resource not found",
                "The resource does not exist in the active scope",
                openstack_request_id=exc.request_id,
            ) from exc
        if status == 409:
            raise error(
                409,
                "storage_conflict",
                "Storage state conflict",
                "The resource state or a dependency conflicts with this operation",
                openstack_request_id=exc.request_id,
            ) from exc
        if status == 413:
            raise error(
                413,
                "storage_quota_exceeded",
                "Storage quota exceeded",
                "Cinder rejected the request because a quota or capacity limit was exceeded",
                openstack_request_id=exc.request_id,
            ) from exc
        if status == 429:
            raise error(
                429,
                "storage_rate_limited",
                "Storage request rate limited",
                "Cinder temporarily rate limited this request",
                openstack_request_id=exc.request_id,
            ) from exc
        raise error(
            503,
            "storage_unavailable",
            "Storage temporarily unavailable",
            "The block storage service is temporarily unavailable",
            openstack_request_id=exc.request_id,
        ) from exc

    def cursor_key(
        record: SessionRecord,
        kind: StorageResourceKind,
        limit: int,
        filters: dict[str, str],
        sort: StorageSort,
        direction: str,
        all_projects: bool,
    ) -> CursorKey:
        return CursorKey(
            scope_namespace=record.scope_namespace,
            resource=f"storage:{kind.value}",
            query=(
                ("limit", str(limit)),
                *(sorted((key, value) for key, value in filters.items())),
                ("sort", sort.value),
                ("direction", direction),
                ("all_projects", str(all_projects).lower()),
            ),
        )

    def resource_marker(item: Any) -> str:
        return str(getattr(item, "id", None) or getattr(item, "name", None) or item.host)

    async def list_page(
        request: Request,
        response: Response,
        record: SessionRecord,
        kind: StorageResourceKind,
        *,
        limit: int,
        page: int,
        name: str | None,
        status: str | None,
        volume_id: str | None,
        sort: StorageSort,
        direction: str,
        all_projects: bool = False,
    ) -> StoragePage:
        if limit not in {10, 25, 50, 100}:
            raise error(
                422,
                "invalid_page_size",
                "Invalid page size",
                "Allowed values are 10, 25, 50, and 100",
            )
        if direction not in {"asc", "desc"}:
            raise error(
                422,
                "invalid_sort_direction",
                "Invalid sort direction",
                "Allowed values are asc and desc",
            )
        scope = active_scope(record)
        filters = {
            key: value.strip()
            for key, value in {"name": name, "status": status, "volume_id": volume_id}.items()
            if value and value.strip()
        }
        key = cursor_key(record, kind, limit, filters, sort, direction, all_projects)
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
                    adapter(request).list_resources(
                        record.auth_context,
                        scope.project.id,
                        scope.region,
                        kind,
                        limit=limit + 1,
                        marker=lease.marker,
                        filters=filters,
                        sort=sort.value,
                        direction=direction,
                        all_projects=all_projects,
                    ),
                    timeout=timeout_seconds,
                )
            except TimeoutError:
                await storage_error(request, record, AdapterTimeoutError(), resource=kind.value)
            except AdapterError as exc:
                await storage_error(
                    request,
                    record,
                    exc,
                    resource=kind.value,
                    cursor_key=key,
                    marker_bound=lease.marker is not None,
                )
            items = list(result.items[:limit])
            has_next = len(result.items) > limit or result.has_next
            next_marker = None
            if has_next and items:
                next_marker = resource_marker(items[-1])
            known = await cursors(request).complete(lease, next_marker)
            if known is None:
                raise error(
                    409,
                    "page_cursor_changed",
                    "Storage pages changed",
                    "A newer page refresh replaced this response",
                )
            committed = True
            if result.request_id:
                response.headers["X-OpenStack-Request-ID"] = result.request_id
            start = (page - 1) * limit
            return StoragePage(
                items=items,
                page=PageInfo(
                    number=page,
                    size=limit,
                    item_from=start + 1 if items else 0,
                    item_to=start + len(items) if items else 0,
                    total_items=None,
                    total_pages=None,
                    has_previous=page > 1,
                    has_next=has_next and page + 1 in known,
                    navigable_pages=navigable_pages(page, max(known)),
                    openstack_request_id=result.request_id,
                ),
            )
        finally:
            if not committed:
                await cursors(request).abandon(lease)

    async def get_one(
        request: Request,
        response: Response,
        record: SessionRecord,
        kind: StorageResourceKind,
        resource_id: str,
    ) -> Any:
        scope = active_scope(record)
        try:
            resource = await asyncio.wait_for(
                adapter(request).get_resource(
                    record.auth_context, scope.project.id, scope.region, kind, resource_id
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            await storage_error(request, record, AdapterTimeoutError(), resource=kind.value)
        except AdapterError as exc:
            await storage_error(request, record, exc, resource=kind.value)
        request_id = getattr(resource, "openstack_request_id", None)
        if request_id:
            response.headers["X-OpenStack-Request-ID"] = request_id
        return resource

    def operation_scope(record: SessionRecord) -> OperationScope:
        scope = active_scope(record)
        return OperationScope(record.user.id, scope.project.id, scope.region)

    def operation_view(
        snapshot: OperationSnapshot,
        result: dict[str, Any] | None = None,
    ) -> OperationView:
        problem = None
        if snapshot.problem:
            problem = {
                "status": snapshot.problem.status,
                "code": snapshot.problem.code,
                "title": snapshot.problem.title,
                "detail": snapshot.problem.detail,
            }
            if snapshot.problem.openstack_request_id:
                problem["openstack_request_id"] = snapshot.problem.openstack_request_id
        return OperationView(
            id=str(snapshot.id),
            kind=snapshot.kind,
            status=snapshot.status.value,
            submitted_at=snapshot.submitted_at,
            updated_at=snapshot.updated_at,
            resource_type=snapshot.target.resource_type,
            resource_id=snapshot.target.resource_id,
            resource_name=snapshot.target.resource_name,
            openstack_request_ids=list(snapshot.openstack_request_ids),
            result=result,
            problem=problem,
        )

    async def mutate(
        request: Request,
        record: SessionRecord,
        kind: StorageResourceKind,
        operation: str,
        resource_id: str | None,
        payload: dict[str, Any],
        idempotency_key: str | None,
    ) -> OperationView:
        if not idempotency_key or not idempotency_key.strip():
            raise error(
                400,
                "idempotency_key_required",
                "Idempotency key required",
                "Send a unique Idempotency-Key for every storage mutation",
            )
        if len(idempotency_key) > 255:
            raise error(
                400,
                "idempotency_key_invalid",
                "Invalid idempotency key",
                "Idempotency-Key must be at most 255 characters",
            )
        scope = active_scope(record)
        op_scope = operation_scope(record)
        kind_name = f"storage.{kind.value}.{operation}"
        target = OperationTarget(kind.value, resource_id, cast(str | None, payload.get("name")))
        try:
            begun = await operation_store(request).begin(
                scope=op_scope,
                idempotency_key=idempotency_key,
                fingerprint=operation_fingerprint(
                    kind_name, {"resource_id": resource_id, "payload": payload}
                ),
                kind=kind_name,
                target=target,
                trace_id=request.state.trace_id,
            )
        except IdempotencyConflictError as exc:
            raise error(
                409,
                "idempotency_conflict",
                "Idempotency key conflict",
                "This Idempotency-Key was already used with a different storage request",
            ) from exc
        except OperationCapacityError as exc:
            raise error(
                503,
                "operation_capacity_exceeded",
                "Operation tracking unavailable",
                "Wait for existing operations to expire before retrying",
            ) from exc
        if begun.replayed:
            return operation_view(begun.operation)
        await operation_store(request).mark_running(op_scope, begun.operation.id)
        try:
            result = await asyncio.wait_for(
                adapter(request).mutate(
                    record.auth_context,
                    scope.project.id,
                    scope.region,
                    kind,
                    operation,
                    resource_id,
                    payload,
                ),
                timeout=timeout_seconds,
            )
        except TimeoutError:
            timeout_error = AdapterTimeoutError()
            await fail_operation(request, op_scope, begun.operation.id, timeout_error)
            await storage_error(request, record, timeout_error, resource=kind.value)
        except AdapterError as exc:
            await fail_operation(request, op_scope, begun.operation.id, exc)
            await storage_error(request, record, exc, resource=kind.value)
        succeeded = await operation_store(request).succeed(
            op_scope,
            begun.operation.id,
            target=OperationTarget(
                kind.value,
                result.resource_id or resource_id,
                result.resource_name or cast(str | None, payload.get("name")),
            ),
            openstack_request_ids=([result.request_id] if result.request_id else []),
        )
        if succeeded is None:
            raise error(
                503,
                "operation_tracking_lost",
                "Operation tracking unavailable",
                "The storage service accepted the request but its operation record was lost",
                openstack_request_id=result.request_id,
            )
        return operation_view(succeeded, result.body)

    async def fail_operation(
        request: Request, scope: OperationScope, operation_id: UUID, exc: AdapterError
    ) -> None:
        status = (
            exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 413, 429, 504} else 503
        )
        await operation_store(request).fail(
            scope,
            operation_id,
            problem=OperationProblem(
                status=status,
                code="storage_upstream_error",
                title="Storage operation failed",
                detail="Cinder rejected or could not complete the storage operation",
                openstack_request_id=exc.request_id,
            ),
            openstack_request_ids=([exc.request_id] if exc.request_id else []),
        )

    def require_confirmation(resource_id: str, confirmation: str | None) -> None:
        if confirmation != resource_id:
            raise error(
                422,
                "confirmation_mismatch",
                "Confirmation does not match",
                "Type the exact resource ID to confirm this dangerous operation",
            )

    ListRecord = Annotated[SessionRecord, Depends(current_session)]
    MutateRecord = Annotated[SessionRecord, Depends(csrf_session)]
    Idempotency = Annotated[str | None, Header(alias="Idempotency-Key")]

    async def list_kind(
        request: Request,
        response: Response,
        record: SessionRecord,
        kind: StorageResourceKind,
        limit: int,
        page: int,
        name: str | None,
        status: str | None,
        volume_id: str | None,
        sort: StorageSort,
        direction: str,
        all_projects: bool = False,
    ) -> StoragePage:
        return await list_page(
            request,
            response,
            record,
            kind,
            limit=limit,
            page=page,
            name=name,
            status=status,
            volume_id=volume_id,
            sort=sort,
            direction=direction,
            all_projects=all_projects,
        )

    @router.get("/volumes", response_model=StoragePage)
    async def volumes(
        request: Request,
        response: Response,
        record: ListRecord,
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
        status: Annotated[str | None, Query(max_length=64)] = None,
        sort: StorageSort = StorageSort.CREATED_AT,
        direction: str = "desc",
    ) -> StoragePage:
        return await list_kind(
            request,
            response,
            record,
            StorageResourceKind.VOLUME,
            limit,
            page,
            name,
            status,
            None,
            sort,
            direction,
        )

    @router.post("/volumes", response_model=OperationView, status_code=202)
    async def create_volume(
        payload: VolumeCreate,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.VOLUME,
            "create",
            None,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.get("/volumes/{volume_id}")
    async def volume(
        volume_id: str, request: Request, response: Response, record: ListRecord
    ) -> Any:
        return await get_one(request, response, record, StorageResourceKind.VOLUME, volume_id)

    @router.patch("/volumes/{volume_id}", response_model=OperationView, status_code=202)
    async def update_volume(
        volume_id: str,
        payload: VolumePatch,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.VOLUME,
            "update",
            volume_id,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.delete("/volumes/{volume_id}", response_model=OperationView, status_code=202)
    async def delete_volume(
        volume_id: str,
        request: Request,
        record: MutateRecord,
        confirmation: Annotated[str, Query()],
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        require_confirmation(volume_id, confirmation)
        return await mutate(
            request,
            record,
            StorageResourceKind.VOLUME,
            "delete",
            volume_id,
            {"confirmation": confirmation},
            idempotency_key,
        )

    @router.post("/volumes/{volume_id}/actions", response_model=OperationView, status_code=202)
    async def volume_action(
        volume_id: str,
        payload: VolumeActionRequest,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        dangerous = {"force_delete", "migrate", "unmanage", "revert_to_snapshot"}
        if payload.action.value in dangerous:
            require_confirmation(volume_id, payload.confirmation)
        return await mutate(
            request,
            record,
            StorageResourceKind.VOLUME,
            payload.action.value,
            volume_id,
            payload.model_dump(mode="json", exclude={"action"}),
            idempotency_key,
        )

    @router.get("/volume-snapshots", response_model=StoragePage)
    async def snapshots(
        request: Request,
        response: Response,
        record: ListRecord,
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
        status: Annotated[str | None, Query(max_length=64)] = None,
        volume_id: Annotated[str | None, Query(max_length=255)] = None,
        sort: StorageSort = StorageSort.CREATED_AT,
        direction: str = "desc",
    ) -> StoragePage:
        return await list_kind(
            request,
            response,
            record,
            StorageResourceKind.SNAPSHOT,
            limit,
            page,
            name,
            status,
            volume_id,
            sort,
            direction,
        )

    @router.post("/volume-snapshots", response_model=OperationView, status_code=202)
    async def create_snapshot(
        payload: SnapshotCreate,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.SNAPSHOT,
            "create",
            None,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.get("/volume-snapshots/{snapshot_id}")
    async def snapshot(
        snapshot_id: str, request: Request, response: Response, record: ListRecord
    ) -> Any:
        return await get_one(request, response, record, StorageResourceKind.SNAPSHOT, snapshot_id)

    @router.patch("/volume-snapshots/{snapshot_id}", response_model=OperationView, status_code=202)
    async def update_snapshot(
        snapshot_id: str,
        payload: SnapshotPatch,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.SNAPSHOT,
            "update",
            snapshot_id,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.delete("/volume-snapshots/{snapshot_id}", response_model=OperationView, status_code=202)
    async def delete_snapshot(
        snapshot_id: str,
        request: Request,
        record: MutateRecord,
        confirmation: Annotated[str, Query()],
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        require_confirmation(snapshot_id, confirmation)
        return await mutate(
            request,
            record,
            StorageResourceKind.SNAPSHOT,
            "delete",
            snapshot_id,
            {"confirmation": confirmation},
            idempotency_key,
        )

    @router.post(
        "/volume-snapshots/{snapshot_id}/actions", response_model=OperationView, status_code=202
    )
    async def snapshot_action(
        snapshot_id: str,
        payload: SnapshotActionRequest,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        require_confirmation(snapshot_id, payload.confirmation)
        return await mutate(
            request,
            record,
            StorageResourceKind.SNAPSHOT,
            payload.action,
            snapshot_id,
            payload.model_dump(mode="json", exclude={"action"}),
            idempotency_key,
        )

    @router.get("/volume-backups", response_model=StoragePage)
    async def backups(
        request: Request,
        response: Response,
        record: ListRecord,
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
        status: Annotated[str | None, Query(max_length=64)] = None,
        volume_id: Annotated[str | None, Query(max_length=255)] = None,
        sort: StorageSort = StorageSort.CREATED_AT,
        direction: str = "desc",
    ) -> StoragePage:
        return await list_kind(
            request,
            response,
            record,
            StorageResourceKind.BACKUP,
            limit,
            page,
            name,
            status,
            volume_id,
            sort,
            direction,
        )

    @router.post("/volume-backups", response_model=OperationView, status_code=202)
    async def create_backup(
        payload: BackupCreate,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.BACKUP,
            "create",
            None,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.post("/volume-backups/import", response_model=OperationView, status_code=202)
    async def import_backup(
        payload: BackupImport,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.BACKUP,
            "import_record",
            None,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.get("/volume-backups/{backup_id}")
    async def backup(
        backup_id: str, request: Request, response: Response, record: ListRecord
    ) -> Any:
        return await get_one(request, response, record, StorageResourceKind.BACKUP, backup_id)

    @router.patch("/volume-backups/{backup_id}", response_model=OperationView, status_code=202)
    async def update_backup(
        backup_id: str,
        payload: BackupPatch,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.BACKUP,
            "update",
            backup_id,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.delete("/volume-backups/{backup_id}", response_model=OperationView, status_code=202)
    async def delete_backup(
        backup_id: str,
        request: Request,
        record: MutateRecord,
        confirmation: Annotated[str, Query()],
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        require_confirmation(backup_id, confirmation)
        return await mutate(
            request,
            record,
            StorageResourceKind.BACKUP,
            "delete",
            backup_id,
            {"confirmation": confirmation},
            idempotency_key,
        )

    @router.post(
        "/volume-backups/{backup_id}/actions", response_model=OperationView, status_code=202
    )
    async def backup_action(
        backup_id: str,
        payload: BackupActionRequest,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        if payload.action == "force_delete":
            require_confirmation(backup_id, payload.confirmation)
        return await mutate(
            request,
            record,
            StorageResourceKind.BACKUP,
            payload.action,
            backup_id,
            payload.model_dump(mode="json", exclude={"action"}),
            idempotency_key,
        )

    @router.post("/admin/storage/volumes/manage", response_model=OperationView, status_code=202)
    async def manage_volume(
        payload: ManagedVolumeCreate,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.VOLUME,
            "manage",
            None,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.get("/admin/storage/volume-types", response_model=StoragePage)
    async def volume_types(
        request: Request,
        response: Response,
        record: ListRecord,
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
    ) -> StoragePage:
        return await list_kind(
            request,
            response,
            record,
            StorageResourceKind.VOLUME_TYPE,
            limit,
            page,
            name,
            None,
            None,
            StorageSort.NAME,
            "asc",
            True,
        )

    @router.post("/admin/storage/volume-types", response_model=OperationView, status_code=202)
    async def create_volume_type(
        payload: VolumeTypeWrite,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.VOLUME_TYPE,
            "create",
            None,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.get("/admin/storage/volume-types/{type_id}")
    async def volume_type(
        type_id: str, request: Request, response: Response, record: ListRecord
    ) -> Any:
        return await get_one(request, response, record, StorageResourceKind.VOLUME_TYPE, type_id)

    @router.put(
        "/admin/storage/volume-types/{type_id}", response_model=OperationView, status_code=202
    )
    async def update_volume_type(
        type_id: str,
        payload: VolumeTypeWrite,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.VOLUME_TYPE,
            "update",
            type_id,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.delete(
        "/admin/storage/volume-types/{type_id}", response_model=OperationView, status_code=202
    )
    async def delete_volume_type(
        type_id: str,
        request: Request,
        record: MutateRecord,
        confirmation: Annotated[str, Query()],
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        require_confirmation(type_id, confirmation)
        return await mutate(
            request,
            record,
            StorageResourceKind.VOLUME_TYPE,
            "delete",
            type_id,
            {"confirmation": confirmation},
            idempotency_key,
        )

    @router.get("/admin/storage/qos-specs", response_model=StoragePage)
    async def qos_specs(
        request: Request,
        response: Response,
        record: ListRecord,
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
    ) -> StoragePage:
        return await list_kind(
            request,
            response,
            record,
            StorageResourceKind.QOS_SPEC,
            limit,
            page,
            name,
            None,
            None,
            StorageSort.NAME,
            "asc",
            True,
        )

    @router.post("/admin/storage/qos-specs", response_model=OperationView, status_code=202)
    async def create_qos(
        payload: QosSpecWrite,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.QOS_SPEC,
            "create",
            None,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.get("/admin/storage/qos-specs/{qos_id}")
    async def qos_spec(
        qos_id: str, request: Request, response: Response, record: ListRecord
    ) -> Any:
        return await get_one(request, response, record, StorageResourceKind.QOS_SPEC, qos_id)

    @router.put("/admin/storage/qos-specs/{qos_id}", response_model=OperationView, status_code=202)
    async def update_qos(
        qos_id: str,
        payload: QosSpecWrite,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        return await mutate(
            request,
            record,
            StorageResourceKind.QOS_SPEC,
            "update",
            qos_id,
            payload.model_dump(mode="json"),
            idempotency_key,
        )

    @router.delete(
        "/admin/storage/qos-specs/{qos_id}", response_model=OperationView, status_code=202
    )
    async def delete_qos(
        qos_id: str,
        request: Request,
        record: MutateRecord,
        confirmation: Annotated[str, Query()],
        force: bool = False,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        require_confirmation(qos_id, confirmation)
        operation = "force_delete" if force else "delete"
        return await mutate(
            request,
            record,
            StorageResourceKind.QOS_SPEC,
            operation,
            qos_id,
            {"confirmation": confirmation, "force": force},
            idempotency_key,
        )

    @router.get("/admin/storage/pools", response_model=StoragePage)
    async def pools(
        request: Request,
        response: Response,
        record: ListRecord,
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
    ) -> StoragePage:
        return await list_kind(
            request,
            response,
            record,
            StorageResourceKind.POOL,
            limit,
            page,
            name,
            None,
            None,
            StorageSort.NAME,
            "asc",
            True,
        )

    @router.get("/admin/storage/services", response_model=StoragePage)
    async def services(
        request: Request,
        response: Response,
        record: ListRecord,
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        status: Annotated[str | None, Query(max_length=64)] = None,
    ) -> StoragePage:
        return await list_kind(
            request,
            response,
            record,
            StorageResourceKind.SERVICE,
            limit,
            page,
            None,
            status,
            None,
            StorageSort.NAME,
            "asc",
            True,
        )

    @router.post(
        "/admin/storage/services/{service_id}/actions",
        response_model=OperationView,
        status_code=202,
    )
    async def service_action(
        service_id: str,
        payload: ServiceActionRequest,
        request: Request,
        record: MutateRecord,
        idempotency_key: Idempotency = None,
    ) -> OperationView:
        require_confirmation(service_id, payload.confirmation)
        return await mutate(
            request,
            record,
            StorageResourceKind.SERVICE,
            payload.action,
            service_id,
            payload.model_dump(mode="json", exclude={"action"}),
            idempotency_key,
        )

    @router.get("/operations/{operation_id}", response_model=OperationView)
    async def operation(operation_id: UUID, request: Request, record: ListRecord) -> OperationView:
        snapshot = await operation_store(request).get(operation_scope(record), operation_id)
        if snapshot is None:
            raise error(
                404,
                "operation_not_found",
                "Operation not found",
                "The operation does not exist in the active user, project, and region scope",
            )
        return operation_view(snapshot)

    return router
