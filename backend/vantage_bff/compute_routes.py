import hashlib
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, NoReturn, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request

from vantage_bff.adapters.base import AdapterError, OpenStackAdapter
from vantage_bff.compute_models import (
    ConsoleRequest,
    ConsoleSession,
    CreateInstanceRequest,
    DeletePreview,
    FlavorAccessRequest,
    FlavorCreateRequest,
    FlavorExtraSpecsRequest,
    FlavorUpdateRequest,
    ImageActionRequest,
    ImageCreateRequest,
    ImageMemberRequest,
    ImageUpdateRequest,
    InstanceActionRequest,
    MutationResult,
    OperationProblemResponse,
    OperationResponse,
    OperationTargetResponse,
    RebuildInstanceRequest,
    ResizeInstanceRequest,
    SnapshotInstanceRequest,
    UpdateInstanceRequest,
)
from vantage_bff.models import Scope, StrictModel
from vantage_bff.operations import (
    IdempotencyConflictError,
    MemoryOperationStore,
    OperationCapacityError,
    OperationProblem,
    OperationScope,
    OperationSnapshot,
    OperationTarget,
    operation_fingerprint,
)
from vantage_bff.sessions import SessionRecord

Dependency = Callable[..., Awaitable[SessionRecord]]
ActiveScope = Callable[[SessionRecord], Scope]
ErrorFactory = Callable[..., Exception]
Mutation = Callable[[], Awaitable[MutationResult]]


def install_compute_routes(
    app: Any,
    *,
    current_session: Dependency,
    csrf_session: Dependency,
    active_scope: ActiveScope,
    error: ErrorFactory,
) -> None:
    router = APIRouter(prefix="/api/v1")

    def operation_scope(record: SessionRecord) -> OperationScope:
        scope = active_scope(record)
        return OperationScope(
            user_id=record.user.id,
            project_id=scope.project.id,
            region=scope.region,
        )

    def adapter(request: Request) -> OpenStackAdapter:
        return cast(OpenStackAdapter, request.app.state.adapter)

    def operations(request: Request) -> MemoryOperationStore:
        return cast(MemoryOperationStore, request.app.state.operations)

    async def submit(
        *,
        request: Request,
        background: BackgroundTasks,
        record: SessionRecord,
        idempotency_key: str | None,
        kind: str,
        target: OperationTarget,
        fingerprint_payload: Mapping[str, Any],
        mutation: Mutation,
    ) -> OperationResponse:
        if idempotency_key is None or not idempotency_key.strip():
            raise error(
                422,
                "idempotency_key_required",
                "Idempotency key required",
                "Provide a non-empty Idempotency-Key header",
            )
        scope = operation_scope(record)
        store = operations(request)
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
                "Idempotency conflict",
                "This key was already used for a different request in the active scope",
            ) from exc
        except OperationCapacityError as exc:
            raise error(
                503,
                "operation_capacity_exceeded",
                "Operation tracking unavailable",
                "Try the request again after existing operations expire",
            ) from exc
        if not begun.replayed:
            background.add_task(run_mutation, store, scope, begun.operation.id, mutation)
        return operation_response(begun.operation)

    @router.get("/operations/{operation_id}", response_model=OperationResponse)
    async def get_operation(
        operation_id: UUID,
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> OperationResponse:
        snapshot = await operations(request).get(operation_scope(record), operation_id)
        if snapshot is None:
            raise error(
                404,
                "operation_not_found",
                "Operation not found",
                "The operation does not exist in the active user, project, and region scope",
            )
        return operation_response(snapshot)

    @router.post("/instances", response_model=OperationResponse, status_code=202)
    async def create_instances(
        payload: CreateInstanceRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        scope = active_scope(record)
        call_payload = secret_payload(payload)
        return await submit(
            request=request,
            background=background,
            record=record,
            idempotency_key=idempotency_key,
            kind="instance.create",
            target=OperationTarget(resource_type="instance", resource_name=payload.name),
            fingerprint_payload=fingerprint_payload(payload),
            mutation=lambda: adapter(request).create_instances(
                record.auth_context, scope.project.id, scope.region, call_payload
            ),
        )

    @router.patch("/instances/{instance_id}", response_model=OperationResponse, status_code=202)
    async def update_instance(
        instance_id: UUID,
        payload: UpdateInstanceRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        scope = active_scope(record)
        data = payload.model_dump(mode="json")
        return await submit(
            request=request,
            background=background,
            record=record,
            idempotency_key=idempotency_key,
            kind="instance.update",
            target=OperationTarget(resource_type="instance", resource_id=str(instance_id)),
            fingerprint_payload=data,
            mutation=lambda: adapter(request).update_instance(
                record.auth_context, scope.project.id, scope.region, str(instance_id), data
            ),
        )

    @router.delete("/instances/{instance_id}", response_model=OperationResponse, status_code=202)
    async def delete_instance(
        instance_id: UUID,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        scope = active_scope(record)
        return await submit(
            request=request,
            background=background,
            record=record,
            idempotency_key=idempotency_key,
            kind="instance.delete",
            target=OperationTarget(resource_type="instance", resource_id=str(instance_id)),
            fingerprint_payload={"instance_id": str(instance_id)},
            mutation=lambda: adapter(request).delete_instance(
                record.auth_context, scope.project.id, scope.region, str(instance_id)
            ),
        )

    @router.get("/instances/{instance_id}/delete-preview", response_model=DeletePreview)
    async def delete_preview(
        instance_id: UUID,
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> DeletePreview:
        scope = active_scope(record)
        try:
            detail = await adapter(request).get_instance(
                record.auth_context, scope.project.id, scope.region, str(instance_id)
            )
        except AdapterError as exc:
            raise_compute_error(error, exc)
        return DeletePreview(
            instance_id=instance_id,
            attached_volume_ids=[volume.id for volume in detail.volumes or []],
            network_contract=f"/api/v1/instances/{instance_id}/interfaces",
            floating_ip_contract=f"/api/v1/floating-ips?instance_id={instance_id}",
            warning=(
                "The instance is deleted; attached volumes and Floating IPs are retained "
                "unless their owning APIs remove them."
            ),
        )

    @router.post(
        "/instances/{instance_id}/actions", response_model=OperationResponse, status_code=202
    )
    async def instance_action(
        instance_id: UUID,
        payload: InstanceActionRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await submit_instance_action(
            instance_id,
            payload.action.value,
            payload.model_dump(mode="json"),
            request,
            background,
            record,
            idempotency_key,
            submit,
            adapter,
            active_scope,
        )

    @router.post(
        "/instances/{instance_id}/resize", response_model=OperationResponse, status_code=202
    )
    async def resize_instance(
        instance_id: UUID,
        payload: ResizeInstanceRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await submit_instance_action(
            instance_id,
            "resize",
            payload.model_dump(mode="json"),
            request,
            background,
            record,
            idempotency_key,
            submit,
            adapter,
            active_scope,
        )

    @router.post(
        "/instances/{instance_id}/resize/confirm", response_model=OperationResponse, status_code=202
    )
    async def confirm_resize(
        instance_id: UUID,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await submit_instance_action(
            instance_id,
            "resize_confirm",
            {},
            request,
            background,
            record,
            idempotency_key,
            submit,
            adapter,
            active_scope,
        )

    @router.post(
        "/instances/{instance_id}/resize/revert", response_model=OperationResponse, status_code=202
    )
    async def revert_resize(
        instance_id: UUID,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await submit_instance_action(
            instance_id,
            "resize_revert",
            {},
            request,
            background,
            record,
            idempotency_key,
            submit,
            adapter,
            active_scope,
        )

    @router.post(
        "/instances/{instance_id}/rebuild", response_model=OperationResponse, status_code=202
    )
    async def rebuild_instance(
        instance_id: UUID,
        payload: RebuildInstanceRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await submit_instance_action(
            instance_id,
            "rebuild",
            secret_payload(payload),
            request,
            background,
            record,
            idempotency_key,
            submit,
            adapter,
            active_scope,
            fingerprint=fingerprint_payload(payload),
        )

    @router.post(
        "/instances/{instance_id}/snapshot", response_model=OperationResponse, status_code=202
    )
    async def snapshot_instance(
        instance_id: UUID,
        payload: SnapshotInstanceRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await submit_instance_action(
            instance_id,
            "snapshot",
            payload.model_dump(mode="json"),
            request,
            background,
            record,
            idempotency_key,
            submit,
            adapter,
            active_scope,
        )

    @router.post("/instances/{instance_id}/console", response_model=ConsoleSession, status_code=201)
    async def create_console(
        instance_id: UUID,
        payload: ConsoleRequest,
        request: Request,
        record: Annotated[SessionRecord, Depends(csrf_session)],
    ) -> ConsoleSession:
        del payload
        scope = active_scope(record)
        try:
            result = await adapter(request).create_console(
                record.auth_context, scope.project.id, scope.region, str(instance_id)
            )
        except AdapterError as exc:
            raise_compute_error(error, exc)
        return ConsoleSession(
            instance_id=instance_id,
            url=result.url,
            expires_at=datetime.now(UTC) + timedelta(minutes=2),
            openstack_request_id=result.openstack_request_id,
        )

    register_image_routes(router, current_session, csrf_session, active_scope, error, submit)
    register_flavor_routes(router, current_session, csrf_session, active_scope, error, submit)
    # Keep routes flat so route auditing sees the same concrete APIRoute set as OpenAPI.
    app.router.routes.extend(router.routes)


async def run_mutation(
    store: MemoryOperationStore,
    scope: OperationScope,
    operation_id: UUID,
    mutation: Mutation,
) -> None:
    await store.mark_running(scope, operation_id)
    try:
        result = await mutation()
    except AdapterError as exc:
        status = exc.status_code
        await store.fail(
            scope,
            operation_id,
            problem=OperationProblem(
                status=status,
                code="openstack_mutation_failed",
                title="OpenStack operation failed",
                detail=(
                    "The active project policy, resource state, or service rejected "
                    "the operation"
                ),
                openstack_request_id=exc.request_id,
            ),
        )
        return
    except Exception:
        await store.fail(
            scope,
            operation_id,
            problem=OperationProblem(
                status=503,
                code="mutation_failed",
                title="Operation failed",
                detail="The operation could not be completed",
            ),
        )
        return
    await store.succeed(
        scope,
        operation_id,
        target=OperationTarget(
            resource_type=(await store.get(scope, operation_id)).target.resource_type,  # type: ignore[union-attr]
            resource_id=result.resource_id,
            resource_name=result.resource_name,
        ),
        openstack_request_ids=(
            [result.openstack_request_id] if result.openstack_request_id else []
        ),
    )


def operation_response(snapshot: OperationSnapshot) -> OperationResponse:
    return OperationResponse(
        id=snapshot.id,
        kind=snapshot.kind,
        status=snapshot.status.value,
        submitted_at=snapshot.submitted_at,
        updated_at=snapshot.updated_at,
        target=OperationTargetResponse(
            resource_type=snapshot.target.resource_type,
            resource_id=snapshot.target.resource_id,
            resource_name=snapshot.target.resource_name,
        ),
        trace_id=snapshot.trace_id,
        openstack_request_ids=list(snapshot.openstack_request_ids),
        problem=(
            OperationProblemResponse(
                status=snapshot.problem.status,
                code=snapshot.problem.code,
                title=snapshot.problem.title,
                detail=snapshot.problem.detail,
                openstack_request_id=snapshot.problem.openstack_request_id,
            )
            if snapshot.problem is not None
            else None
        ),
    )


def fingerprint_payload(model: StrictModel) -> dict[str, Any]:
    data = model.model_dump(mode="json", exclude={"user_data"})
    user_data = getattr(model, "user_data", None)
    if user_data is not None:
        data["user_data_sha256"] = hashlib.sha256(
            user_data.get_secret_value().encode("utf-8")
        ).hexdigest()
    return data


def secret_payload(model: StrictModel) -> dict[str, Any]:
    data = model.model_dump(mode="json", exclude={"user_data"})
    user_data = getattr(model, "user_data", None)
    if user_data is not None:
        data["user_data"] = user_data.get_secret_value()
    return data


async def submit_instance_action(
    instance_id: UUID,
    action: str,
    data: dict[str, Any],
    request: Request,
    background: BackgroundTasks,
    record: SessionRecord,
    idempotency_key: str | None,
    submit: Callable[..., Awaitable[OperationResponse]],
    adapter: Callable[[Request], OpenStackAdapter],
    active_scope: ActiveScope,
    *,
    fingerprint: Mapping[str, Any] | None = None,
) -> OperationResponse:
    scope = active_scope(record)
    return await submit(
        request=request,
        background=background,
        record=record,
        idempotency_key=idempotency_key,
        kind=f"instance.{action}",
        target=OperationTarget(resource_type="instance", resource_id=str(instance_id)),
        fingerprint_payload=fingerprint or data,
        mutation=lambda: adapter(request).instance_action(
            record.auth_context, scope.project.id, scope.region, str(instance_id), action, data
        ),
    )


def register_image_routes(
    router: APIRouter,
    current_session: Dependency,
    csrf_session: Dependency,
    active_scope: ActiveScope,
    error: ErrorFactory,
    submit: Callable[..., Awaitable[OperationResponse]],
) -> None:
    del current_session, error

    async def mutate(
        action: str,
        image_id: UUID | None,
        payload: StrictModel | None,
        request: Request,
        background: BackgroundTasks,
        record: SessionRecord,
        key: str | None,
    ) -> OperationResponse:
        scope = active_scope(record)
        data = payload.model_dump(mode="json") if payload is not None else {}
        adapter = cast(OpenStackAdapter, request.app.state.adapter)
        return await submit(
            request=request,
            background=background,
            record=record,
            idempotency_key=key,
            kind=f"image.{action}",
            target=OperationTarget(
                resource_type="image",
                resource_id=str(image_id) if image_id else None,
                resource_name=data.get("name"),
            ),
            fingerprint_payload=data,
            mutation=lambda: adapter.image_mutation(
                record.auth_context,
                scope.project.id,
                scope.region,
                action,
                str(image_id) if image_id else None,
                data,
            ),
        )

    @router.post("/images", response_model=OperationResponse, status_code=202)
    async def create_image(
        payload: ImageCreateRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate("create", None, payload, request, background, record, key)

    @router.patch("/images/{image_id}", response_model=OperationResponse, status_code=202)
    async def update_image(
        image_id: UUID,
        payload: ImageUpdateRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate("update", image_id, payload, request, background, record, key)

    @router.delete("/images/{image_id}", response_model=OperationResponse, status_code=202)
    async def delete_image(
        image_id: UUID,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate("delete", image_id, None, request, background, record, key)

    @router.post("/images/{image_id}/actions", response_model=OperationResponse, status_code=202)
    async def image_action(
        image_id: UUID,
        payload: ImageActionRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate(payload.action, image_id, payload, request, background, record, key)

    @router.post("/images/{image_id}/members", response_model=OperationResponse, status_code=202)
    async def add_image_member(
        image_id: UUID,
        payload: ImageMemberRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate("member_add", image_id, payload, request, background, record, key)

    @router.delete(
        "/images/{image_id}/members/{project_id}", response_model=OperationResponse, status_code=202
    )
    async def remove_image_member(
        image_id: UUID,
        project_id: str,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate(
            "member_remove",
            image_id,
            ImageMemberRequest(project_id=project_id),
            request,
            background,
            record,
            key,
        )


def register_flavor_routes(
    router: APIRouter,
    current_session: Dependency,
    csrf_session: Dependency,
    active_scope: ActiveScope,
    error: ErrorFactory,
    submit: Callable[..., Awaitable[OperationResponse]],
) -> None:
    del current_session, error

    async def mutate(
        action: str,
        flavor_id: str | None,
        data: dict[str, Any],
        request: Request,
        background: BackgroundTasks,
        record: SessionRecord,
        key: str | None,
    ) -> OperationResponse:
        scope = active_scope(record)
        adapter = cast(OpenStackAdapter, request.app.state.adapter)
        return await submit(
            request=request,
            background=background,
            record=record,
            idempotency_key=key,
            kind=f"flavor.{action}",
            target=OperationTarget(
                resource_type="flavor", resource_id=flavor_id, resource_name=data.get("name")
            ),
            fingerprint_payload=data,
            mutation=lambda: adapter.flavor_mutation(
                record.auth_context, scope.project.id, scope.region, action, flavor_id, data
            ),
        )

    @router.post("/flavors", response_model=OperationResponse, status_code=202)
    async def create_flavor(
        payload: FlavorCreateRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate(
            "create", None, payload.model_dump(mode="json"), request, background, record, key
        )

    @router.patch("/flavors/{flavor_id}", response_model=OperationResponse, status_code=202)
    async def update_flavor(
        flavor_id: str,
        payload: FlavorUpdateRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate(
            "update", flavor_id, payload.model_dump(mode="json"), request, background, record, key
        )

    @router.delete("/flavors/{flavor_id}", response_model=OperationResponse, status_code=202)
    async def delete_flavor(
        flavor_id: str,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate("delete", flavor_id, {}, request, background, record, key)

    @router.put(
        "/flavors/{flavor_id}/extra-specs", response_model=OperationResponse, status_code=202
    )
    async def set_extra_specs(
        flavor_id: str,
        payload: FlavorExtraSpecsRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate(
            "extra_specs_set",
            flavor_id,
            payload.model_dump(mode="json"),
            request,
            background,
            record,
            key,
        )

    @router.delete(
        "/flavors/{flavor_id}/extra-specs/{spec_key}",
        response_model=OperationResponse,
        status_code=202,
    )
    async def unset_extra_spec(
        flavor_id: str,
        spec_key: str,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate(
            "extra_spec_unset", flavor_id, {"key": spec_key}, request, background, record, key
        )

    @router.post("/flavors/{flavor_id}/access", response_model=OperationResponse, status_code=202)
    async def add_flavor_access(
        flavor_id: str,
        payload: FlavorAccessRequest,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate(
            "access_add",
            flavor_id,
            payload.model_dump(mode="json"),
            request,
            background,
            record,
            key,
        )

    @router.delete(
        "/flavors/{flavor_id}/access/{project_id}",
        response_model=OperationResponse,
        status_code=202,
    )
    async def remove_flavor_access(
        flavor_id: str,
        project_id: str,
        request: Request,
        background: BackgroundTasks,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> OperationResponse:
        return await mutate(
            "access_remove", flavor_id, {"project_id": project_id}, request, background, record, key
        )


def raise_compute_error(error: ErrorFactory, exc: AdapterError) -> NoReturn:
    status = (
        exc.status_code if exc.status_code in {400, 401, 403, 404, 409, 429, 501, 503, 504} else 503
    )
    raise error(
        status,
        "compute_request_failed",
        "Compute request failed",
        "The active project policy, resource state, or compute service rejected the request",
        openstack_request_id=exc.request_id,
    ) from exc
