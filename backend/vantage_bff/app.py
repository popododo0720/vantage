import asyncio
import hmac
import math
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, NoReturn, cast

from fastapi import Cookie, Depends, FastAPI, Header, Query, Request, Response
from fastapi import Path as PathParameter
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from vantage_bff.adapters.base import (
    AdapterError,
    AdapterTimeoutError,
    AuthenticationError,
    OpenStackAdapter,
    ProvisioningListResult,
    ScopeError,
)
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.adapters.openstack_sdk import OpenStackSdkAdapter
from vantage_bff.config import Settings
from vantage_bff.cursors import CursorKey, MemoryCursorStore
from vantage_bff.models import (
    CreatedKeyPair,
    CreateKeyPairRequest,
    FlavorPage,
    ImagePage,
    ImageVisibility,
    InstanceDetail,
    InstancePage,
    InstanceSort,
    InstanceSummary,
    KeyPairMode,
    KeyPairPage,
    LoginRequest,
    NetworkPage,
    PageInfo,
    Problem,
    ProjectOverview,
    ProjectPage,
    Quota,
    QuotaCollection,
    QuotaService,
    Scope,
    ScopeRequest,
    SecurityGroupPage,
    SessionPreferenceRequest,
    SessionResponse,
    SortDirection,
    WidgetError,
)
from vantage_bff.models import (
    Operation as OperationResponse,
)
from vantage_bff.models import (
    OperationTarget as OperationTargetResponse,
)
from vantage_bff.operations import (
    BeginOperationResult,
    IdempotencyConflictError,
    MemoryOperationStore,
    OperationCapacityError,
    OperationScope,
    OperationSnapshot,
    OperationStatus,
    OperationStore,
    operation_fingerprint,
)
from vantage_bff.operations import (
    OperationProblem as StoredOperationProblem,
)
from vantage_bff.operations import (
    OperationTarget as StoredOperationTarget,
)
from vantage_bff.rate_limit import LoginRateLimiter
from vantage_bff.sessions import (
    MemorySessionStore,
    SessionRecord,
    SessionStore,
    new_scope_namespace,
    new_session,
    rotated_session,
)


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        title: str,
        detail: str,
        *,
        openstack_request_id: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.code = code
        self.title = title
        self.detail = detail
        self.openstack_request_id = openstack_request_id
        self.headers = headers or {}


def _operation_response(snapshot: OperationSnapshot) -> OperationResponse:
    problem = None
    if snapshot.problem is not None:
        problem = Problem(
            title=snapshot.problem.title,
            status=snapshot.problem.status,
            detail=snapshot.problem.detail,
            code=snapshot.problem.code,
            trace_id=snapshot.trace_id,
            openstack_request_id=snapshot.problem.openstack_request_id,
        )
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
        problem=problem,
    )


def _navigable_pages(current: int, total: int) -> list[int]:
    if total <= 7:
        return list(range(1, total + 1))
    if current <= 4:
        middle = range(2, 6)
    elif current >= total - 3:
        middle = range(total - 4, total)
    else:
        middle = range(current - 1, current + 2)
    return [1, *middle, total]


def _adapter(settings: Settings) -> OpenStackAdapter:
    if settings.adapter == "fake":
        return FakeOpenStackAdapter()
    if settings.adapter == "openstack":
        if not settings.auth_url:
            raise RuntimeError("VANTAGE_OS_AUTH_URL is required for the openstack adapter")
        return OpenStackSdkAdapter(
            auth_url=settings.auth_url,
            interface=settings.interface,
            default_region=settings.default_region,
            request_timeout_seconds=settings.request_timeout_seconds,
            quota_timeout_seconds=settings.quota_source_timeout_seconds,
            instance_timeout_seconds=settings.instance_source_timeout_seconds,
            provisioning_timeout_seconds=settings.provisioning_source_timeout_seconds,
            thread_capacity=settings.openstack_sdk_thread_capacity,
        )
    raise RuntimeError(f"Unsupported adapter: {settings.adapter}")


def create_app(
    settings: Settings | None = None,
    adapter: OpenStackAdapter | None = None,
    store: SessionStore | None = None,
    cursor_store: MemoryCursorStore | None = None,
    operation_store: OperationStore | None = None,
) -> FastAPI:
    active_settings = settings or Settings.from_env()
    frontend_root = Path(__file__).resolve().parents[2] / "frontend" / "dist"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = active_settings
        app.state.adapter = adapter or _adapter(active_settings)
        app.state.sessions = store or MemorySessionStore()
        app.state.instance_cursors = cursor_store or MemoryCursorStore(
            active_settings.instance_cursor_ttl_seconds,
            active_settings.instance_cursor_max_chains,
            active_settings.instance_cursor_max_pages,
        )
        app.state.operations = operation_store or MemoryOperationStore(
            terminal_ttl_seconds=active_settings.operation_terminal_ttl_seconds,
            max_records=active_settings.operation_max_records,
        )
        app.state.login_limiter = LoginRateLimiter(
            active_settings.login_attempt_limit,
            active_settings.login_attempt_window_seconds,
        )
        yield

    app = FastAPI(title="Vantage BFF", version="0.4.0", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError) -> JSONResponse:
        trace_id = request.state.trace_id
        problem = Problem(
            title=exc.title,
            status=exc.status,
            detail=exc.detail,
            code=exc.code,
            trace_id=trace_id,
            openstack_request_id=exc.openstack_request_id,
        )
        return JSONResponse(
            problem.model_dump(exclude_none=True),
            status_code=exc.status,
            media_type="application/problem+json",
            headers={"X-Trace-ID": trace_id, **exc.headers},
        )

    @app.exception_handler(RequestValidationError)
    async def request_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        del exc
        trace_id = request.state.trace_id
        problem = Problem(
            title="Invalid request",
            status=422,
            detail="The request does not match the expected schema",
            code="invalid_request",
            trace_id=trace_id,
        )
        return JSONResponse(
            problem.model_dump(exclude_none=True),
            status_code=422,
            media_type="application/problem+json",
            headers={"X-Trace-ID": trace_id},
        )

    @app.middleware("http")
    async def trace(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request.state.trace_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Trace-ID"] = request.state.trace_id
        if request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'none'; form-action 'self'"
        )
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    def set_session_cookie(response: Response, record: SessionRecord) -> None:
        remaining_seconds = max(0, int((record.expires_at - datetime.now(UTC)).total_seconds()))
        response.set_cookie(
            key=active_settings.cookie_name,
            value=record.id,
            max_age=remaining_seconds,
            httponly=True,
            secure=active_settings.cookie_secure,
            samesite="lax",
            path="/",
        )
        response.headers["X-CSRF-Token"] = record.csrf_token

    async def current_session(
        request: Request,
        session_id: Annotated[str | None, Cookie(alias=active_settings.cookie_name)] = None,
    ) -> SessionRecord:
        if not session_id:
            raise ApiError(
                401, "unauthenticated", "Authentication required", "Session missing or expired"
            )
        sessions = cast(SessionStore, request.app.state.sessions)
        record = await sessions.get(session_id)
        if record is None:
            raise ApiError(
                401, "unauthenticated", "Authentication required", "Session missing or expired"
            )
        return record

    async def csrf_session(
        record: Annotated[SessionRecord, Depends(current_session)],
        csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> SessionRecord:
        if not csrf or not hmac.compare_digest(csrf, record.csrf_token):
            raise ApiError(
                403, "csrf_invalid", "Request rejected", "CSRF token is missing or invalid"
            )
        return record

    def instance_cursors(request: Request) -> MemoryCursorStore:
        return cast(MemoryCursorStore, request.app.state.instance_cursors)

    async def invalidate_session(request: Request, record: SessionRecord) -> None:
        await request.app.state.sessions.delete(record.id)
        await instance_cursors(request).invalidate_namespace(record.scope_namespace)

    def active_scope(record: SessionRecord) -> Scope:
        if record.active_scope is None:
            raise ApiError(
                409,
                "active_scope_required",
                "Project scope required",
                "Select a project and region before requesting project resources",
            )
        return record.active_scope

    def operations(request: Request) -> OperationStore:
        return cast(OperationStore, request.app.state.operations)

    def operation_scope(record: SessionRecord) -> OperationScope:
        scope = active_scope(record)
        return OperationScope(
            user_id=record.user.id,
            project_id=scope.project.id,
            region=scope.region,
        )

    def validated_idempotency_key(
        value: Annotated[
            str | None,
            Header(alias="Idempotency-Key", min_length=1, max_length=255),
        ] = None,
    ) -> str:
        normalized = value.strip() if value is not None else ""
        if not 16 <= len(normalized) <= 255:
            raise ApiError(
                422,
                "invalid_request",
                "Invalid request",
                "Idempotency-Key must contain between 16 and 255 characters",
            )
        return normalized

    async def begin_keypair_operation(
        request: Request,
        *,
        scope: OperationScope,
        idempotency_key: str,
        kind: str,
        fingerprint_payload: dict[str, Any],
        name: str,
    ) -> BeginOperationResult:
        try:
            return await operations(request).begin(
                scope=scope,
                idempotency_key=idempotency_key,
                fingerprint=operation_fingerprint(kind, fingerprint_payload),
                kind=kind,
                target=StoredOperationTarget(
                    resource_type="keypair",
                    resource_name=name,
                ),
                trace_id=request.state.trace_id,
            )
        except IdempotencyConflictError as exc:
            raise ApiError(
                409,
                "idempotency_conflict",
                "Idempotency key conflict",
                "The Idempotency-Key was already used with a different request",
            ) from exc
        except OperationCapacityError as exc:
            raise ApiError(
                503,
                "operation_store_unavailable",
                "Operation temporarily unavailable",
                "The operation store cannot accept another mutation",
            ) from exc

    async def keypair_api_error(
        request: Request,
        record: SessionRecord,
        exc: AdapterError,
    ) -> ApiError:
        if isinstance(exc, AdapterTimeoutError) or exc.status_code == 504:
            return ApiError(
                504,
                "keypair_timeout",
                "Key pair request timed out",
                "The compute service did not respond in time",
                openstack_request_id=exc.request_id,
            )
        if exc.status_code == 401:
            await invalidate_session(request, record)
            return ApiError(
                401,
                "unauthenticated",
                "Authentication required",
                "Session missing or expired",
                openstack_request_id=exc.request_id,
            )
        if exc.status_code == 400:
            return ApiError(
                422,
                "invalid_keypair",
                "Invalid key pair request",
                "The compute service rejected the key pair request",
                openstack_request_id=exc.request_id,
            )
        if exc.status_code == 403:
            return ApiError(
                403,
                "keypair_forbidden",
                "Key pair request denied",
                "The compute policy denied this request",
                openstack_request_id=exc.request_id,
            )
        if exc.status_code == 404:
            return ApiError(
                404,
                "keypair_not_found",
                "Key pair not found",
                "The key pair or compute endpoint does not exist in the active scope",
                openstack_request_id=exc.request_id,
            )
        if exc.status_code == 409:
            return ApiError(
                409,
                "keypair_conflict",
                "Key pair conflict",
                "The key pair request conflicts with the current compute state",
                openstack_request_id=exc.request_id,
            )
        if exc.status_code == 429:
            return ApiError(
                429,
                "keypair_rate_limited",
                "Key pair request rate limited",
                "The compute service temporarily rate limited this request",
                openstack_request_id=exc.request_id,
            )
        return ApiError(
            503,
            "keypair_unavailable",
            "Key pair service unavailable",
            "The compute service is temporarily unavailable",
            openstack_request_id=exc.request_id,
        )

    async def fail_keypair_operation(
        request: Request,
        *,
        scope: OperationScope,
        operation_id: uuid.UUID,
        error: ApiError,
        cause: BaseException,
    ) -> NoReturn:
        await operations(request).fail(
            scope,
            operation_id,
            problem=StoredOperationProblem(
                status=error.status,
                code=error.code,
                title=error.title,
                detail=error.detail,
                openstack_request_id=error.openstack_request_id,
            ),
            openstack_request_ids=(
                (error.openstack_request_id,) if error.openstack_request_id else ()
            ),
        )
        raise error from cause

    async def raise_replayed_failure(
        request: Request,
        record: SessionRecord,
        snapshot: OperationSnapshot,
    ) -> None:
        if snapshot.status is not OperationStatus.FAILED:
            return
        if snapshot.problem is None:
            raise ApiError(
                503,
                "operation_state_unavailable",
                "Operation state unavailable",
                "The failed operation has no recorded problem",
            )
        problem = snapshot.problem
        if problem.status == 401:
            await invalidate_session(request, record)
        raise ApiError(
            problem.status,
            problem.code,
            problem.title,
            problem.detail,
            openstack_request_id=problem.openstack_request_id,
        )

    def preserve_operation_request_id(response: Response, snapshot: OperationSnapshot) -> None:
        if snapshot.openstack_request_ids:
            response.headers["X-OpenStack-Request-ID"] = snapshot.openstack_request_ids[-1]

    def instance_cursor_key(
        record: SessionRecord,
        *,
        limit: int,
        name: str | None,
        status: str | None,
        image_id: str | None,
        sort: InstanceSort,
        direction: SortDirection,
    ) -> CursorKey:
        return CursorKey(
            scope_namespace=record.scope_namespace,
            resource="instances",
            query=(
                ("limit", str(limit)),
                ("name", name),
                ("status", status),
                ("image_id", image_id),
                ("sort", sort.value),
                ("direction", direction.value),
            ),
        )

    def provisioning_cursor_key(
        record: SessionRecord,
        resource: str,
        *,
        limit: int,
        filters: tuple[tuple[str, str | None], ...],
    ) -> CursorKey:
        return CursorKey(
            scope_namespace=record.scope_namespace,
            resource=resource,
            query=(("limit", str(limit)), *filters),
        )

    def normalized_optional_filter(value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    async def raise_instance_error(
        request: Request,
        record: SessionRecord,
        exc: AdapterError,
        *,
        detail: bool,
        cursor_key: CursorKey | None = None,
        marker_bound: bool = False,
    ) -> NoReturn:
        if isinstance(exc, AdapterTimeoutError) or exc.status_code == 504:
            raise ApiError(
                504,
                "instance_timeout",
                "Compute request timed out",
                "The compute service did not respond in time",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 401:
            await invalidate_session(request, record)
            raise ApiError(
                401,
                "unauthenticated",
                "Authentication required",
                "Session missing or expired",
                openstack_request_id=exc.request_id,
            ) from exc
        if not detail and marker_bound and cursor_key is not None and exc.status_code in {400, 404}:
            await instance_cursors(request).invalidate(cursor_key)
            raise ApiError(
                409,
                "page_cursor_unavailable",
                "Page no longer available",
                "Return to page 1 to rebuild the instance page sequence",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 400:
            raise ApiError(
                422,
                "invalid_instance_filter",
                "Invalid instance filter",
                "Nova rejected one or more instance filters",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 403:
            raise ApiError(
                403,
                "instance_forbidden" if detail else "instances_forbidden",
                "Instance unavailable" if detail else "Instances unavailable",
                "The compute policy denied this request",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 404:
            raise ApiError(
                404,
                "instance_not_found" if detail else "instances_not_found",
                "Instance not found" if detail else "Instances unavailable",
                (
                    "The instance does not exist in the active project"
                    if detail
                    else "The compute service could not find the instance collection"
                ),
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 409:
            if cursor_key is not None:
                await instance_cursors(request).invalidate(cursor_key)
                raise ApiError(
                    409,
                    "page_cursor_unavailable",
                    "Page no longer available",
                    "Return to page 1 to rebuild the instance page sequence",
                    openstack_request_id=exc.request_id,
                ) from exc
            raise ApiError(
                409,
                "instance_conflict",
                "Instance temporarily unavailable",
                "The instance state changed while it was being read",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 429:
            raise ApiError(
                429,
                "instance_rate_limited",
                "Compute request rate limited",
                "The compute service temporarily rate limited this request",
                openstack_request_id=exc.request_id,
            ) from exc
        raise ApiError(
            503,
            "instance_unavailable",
            "Compute temporarily unavailable",
            "The compute service is temporarily unavailable",
            openstack_request_id=exc.request_id,
        ) from exc

    async def raise_provisioning_error(
        request: Request,
        record: SessionRecord,
        exc: AdapterError,
        *,
        resource: str,
        singular: str,
        service: str,
        cursor_key: CursorKey,
        marker_bound: bool,
    ) -> NoReturn:
        if isinstance(exc, AdapterTimeoutError) or exc.status_code == 504:
            raise ApiError(
                504,
                f"{singular}_timeout",
                f"{service} request timed out",
                f"The {service.lower()} service did not respond in time",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 401:
            await invalidate_session(request, record)
            raise ApiError(
                401,
                "unauthenticated",
                "Authentication required",
                "Session missing or expired",
                openstack_request_id=exc.request_id,
            ) from exc
        if marker_bound and exc.status_code in {400, 404}:
            await instance_cursors(request).invalidate(cursor_key)
            raise ApiError(
                409,
                "page_cursor_unavailable",
                "Page no longer available",
                f"Return to page 1 to rebuild the {resource} page sequence",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 400:
            raise ApiError(
                422,
                f"invalid_{singular}_filter",
                f"Invalid {singular.replace('_', ' ')} filter",
                f"The {service.lower()} service rejected one or more filters",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 403:
            raise ApiError(
                403,
                f"{resource.replace('-', '_')}_forbidden",
                f"{resource.replace('-', ' ').title()} unavailable",
                f"The {service.lower()} policy denied this request",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 404:
            raise ApiError(
                404,
                f"{resource.replace('-', '_')}_not_found",
                f"{resource.replace('-', ' ').title()} unavailable",
                f"The {service.lower()} service could not find this collection",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 409:
            await instance_cursors(request).invalidate(cursor_key)
            raise ApiError(
                409,
                "page_cursor_unavailable",
                "Page no longer available",
                f"Return to page 1 to rebuild the {resource} page sequence",
                openstack_request_id=exc.request_id,
            ) from exc
        if exc.status_code == 429:
            raise ApiError(
                429,
                f"{singular}_rate_limited",
                f"{service} request rate limited",
                f"The {service.lower()} service temporarily rate limited this request",
                openstack_request_id=exc.request_id,
            ) from exc
        raise ApiError(
            503,
            f"{singular}_unavailable",
            f"{service} temporarily unavailable",
            f"The {service.lower()} service is temporarily unavailable",
            openstack_request_id=exc.request_id,
        ) from exc

    async def provisioning_page(
        request: Request,
        response: Response,
        record: SessionRecord,
        *,
        resource: str,
        singular: str,
        service: str,
        limit: int,
        page: int,
        filters: tuple[tuple[str, str | None], ...],
        load: Callable[[str | None], Awaitable[ProvisioningListResult]],
    ) -> tuple[list[Any], PageInfo]:
        if limit not in {10, 25, 50, 100}:
            raise ApiError(
                422,
                "invalid_page_size",
                "Invalid page size",
                "Allowed values are 10, 25, 50, and 100",
            )
        active_scope(record)
        cursor_key = provisioning_cursor_key(record, resource, limit=limit, filters=filters)
        cursors = instance_cursors(request)
        lease = await cursors.acquire(cursor_key, page)
        if lease is None:
            raise ApiError(
                409,
                "page_cursor_unavailable",
                "Page not available yet",
                f"Open the preceding {resource} page before requesting this page",
            )
        cursor_committed = False
        try:
            try:
                result = await asyncio.wait_for(
                    load(lease.marker),
                    timeout=active_settings.provisioning_source_timeout_seconds,
                )
            except TimeoutError:
                await raise_provisioning_error(
                    request,
                    record,
                    AdapterTimeoutError(),
                    resource=resource,
                    singular=singular,
                    service=service,
                    cursor_key=cursor_key,
                    marker_bound=lease.marker is not None,
                )
            except AdapterError as exc:
                await raise_provisioning_error(
                    request,
                    record,
                    exc,
                    resource=resource,
                    singular=singular,
                    service=service,
                    cursor_key=cursor_key,
                    marker_bound=lease.marker is not None,
                )
            visible_items = list(result.items[:limit])
            has_next = len(result.items) > limit or result.has_next
            next_marker = None
            if has_next and visible_items:
                last = visible_items[-1]
                marker_value = getattr(last, "id", None) or getattr(last, "name", None)
                next_marker = str(marker_value) if marker_value is not None else None
            known_pages = await cursors.complete(lease, next_marker)
            if known_pages is None:
                raise ApiError(
                    409,
                    "page_cursor_changed",
                    f"{resource.replace('-', ' ').title()} pages changed",
                    "A newer page refresh replaced this response",
                )
            cursor_committed = True
            known_max = max(known_pages)
            has_next = has_next and page + 1 in known_pages
            start = (page - 1) * limit
            if result.openstack_request_id is not None:
                response.headers["X-OpenStack-Request-ID"] = result.openstack_request_id
            return visible_items, PageInfo(
                number=page,
                size=limit,
                item_from=start + 1 if visible_items else 0,
                item_to=start + len(visible_items) if visible_items else 0,
                total_items=None,
                total_pages=None,
                has_previous=page > 1,
                has_next=has_next,
                navigable_pages=_navigable_pages(page, known_max),
                openstack_request_id=result.openstack_request_id,
            )
        finally:
            if not cursor_committed:
                await cursors.abandon(lease)

    async def collect_quotas(
        request: Request,
        record: SessionRecord,
        services: tuple[QuotaService, ...],
    ) -> tuple[list[Quota], list[WidgetError]]:
        scope = record.active_scope
        if scope is None:
            raise ApiError(
                409,
                "active_scope_required",
                "Project scope required",
                "Select a project and region before requesting project resources",
            )

        async def load(service: QuotaService) -> tuple[Quota, ...]:
            return await asyncio.wait_for(
                request.app.state.adapter.quotas(
                    record.auth_context,
                    scope.project.id,
                    scope.region,
                    service,
                ),
                timeout=active_settings.quota_source_timeout_seconds,
            )

        results = await asyncio.gather(
            *(load(service) for service in services),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, AdapterError) and result.status_code == 401:
                await invalidate_session(request, record)
                raise ApiError(
                    401,
                    "unauthenticated",
                    "Authentication required",
                    "Session missing or expired",
                    openstack_request_id=result.request_id,
                )

        quotas: list[Quota] = []
        errors: list[WidgetError] = []
        for service, result in zip(services, results, strict=True):
            if not isinstance(result, BaseException):
                quotas.extend(result)
                continue
            request_id = result.request_id if isinstance(result, AdapterError) else None
            if isinstance(result, TimeoutError):
                suffix = "timeout"
                message = f"{service.value.capitalize()} quota data did not respond in time"
            elif isinstance(result, AdapterError) and result.status_code == 403:
                suffix = "forbidden"
                message = f"{service.value.capitalize()} quota data is not available for this scope"
            elif isinstance(result, AdapterError) and result.status_code == 429:
                suffix = "rate_limited"
                message = f"{service.value.capitalize()} quota data is temporarily rate limited"
            else:
                suffix = "unavailable"
                message = f"{service.value.capitalize()} quota data is temporarily unavailable"
            error = WidgetError(
                code=f"{service.value}_quota_{suffix}",
                message=message,
            )
            if request_id is not None:
                error["openstack_request_id"] = request_id
            errors.append(error)
        return quotas, errors

    @app.post("/api/v1/session/login", response_model=SessionResponse, status_code=201)
    async def login(payload: LoginRequest, request: Request, response: Response) -> SessionResponse:
        client_host = request.client.host if request.client else "unknown"
        limiter_key = f"{client_host}\0{payload.domain.casefold()}\0{payload.username.casefold()}"
        reservation = await request.app.state.login_limiter.reserve(limiter_key)
        if reservation is None:
            raise ApiError(
                429,
                "authentication_rate_limited",
                "Sign in temporarily unavailable",
                (
                    "Too many failed sign-in attempts. Try again in "
                    f"{active_settings.login_attempt_window_seconds} seconds"
                ),
                headers={
                    "Retry-After": str(active_settings.login_attempt_window_seconds),
                },
            )
        try:
            result = await request.app.state.adapter.authenticate(
                payload.username, payload.password, payload.domain
            )
        except AuthenticationError as exc:
            raise ApiError(
                401,
                "invalid_credentials",
                "Sign in failed",
                "The supplied credentials are invalid",
                openstack_request_id=exc.request_id,
            ) from exc
        except AdapterError as exc:
            await request.app.state.login_limiter.release(limiter_key, reservation)
            if exc.status_code == 403:
                raise ApiError(
                    403,
                    "authentication_forbidden",
                    "Sign in not permitted",
                    "The identity service denied access",
                    openstack_request_id=exc.request_id,
                ) from exc
            if exc.status_code == 429:
                raise ApiError(
                    429,
                    "identity_rate_limited",
                    "Sign in temporarily unavailable",
                    "The identity service rate limited the request",
                    openstack_request_id=exc.request_id,
                ) from exc
            raise ApiError(
                503,
                "identity_unavailable",
                "Sign in temporarily unavailable",
                "The identity service is unavailable",
                openstack_request_id=exc.request_id,
            ) from exc
        await request.app.state.login_limiter.succeeded(limiter_key)
        record = new_session(
            user=result.user,
            projects=result.projects,
            regions=result.regions,
            auth_context=result.auth_context,
            ttl_seconds=active_settings.session_ttl_seconds,
            upstream_expires_at=result.expires_at,
        )
        previous_session_id = request.cookies.get(active_settings.cookie_name)
        await request.app.state.sessions.create(record)
        if previous_session_id:
            previous = await request.app.state.sessions.get(previous_session_id)
            await request.app.state.sessions.delete(previous_session_id)
            if previous is not None:
                await instance_cursors(request).invalidate_namespace(previous.scope_namespace)
        set_session_cookie(response, record)
        return record.public()

    @app.get("/api/v1/session", response_model=SessionResponse)
    async def get_session(
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> SessionResponse:
        response.headers["X-CSRF-Token"] = record.csrf_token
        return record.public()

    @app.patch("/api/v1/session", response_model=SessionResponse)
    async def update_session(
        payload: SessionPreferenceRequest,
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(csrf_session)],
    ) -> SessionResponse:
        updated = rotated_session(record, locale=payload.locale)
        if not await request.app.state.sessions.rotate(record.id, updated):
            raise ApiError(401, "session_changed", "Authentication required", "Session has changed")
        set_session_cookie(response, updated)
        return updated.public()

    @app.delete("/api/v1/session", status_code=204)
    async def logout(
        request: Request,
        response: Response,
        session_id: Annotated[str | None, Cookie(alias=active_settings.cookie_name)] = None,
        csrf: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
    ) -> None:
        record = await request.app.state.sessions.get(session_id) if session_id else None
        if record is not None:
            if not csrf or not hmac.compare_digest(csrf, record.csrf_token):
                raise ApiError(
                    403,
                    "csrf_invalid",
                    "Request rejected",
                    "CSRF token is missing or invalid",
                )
            await request.app.state.sessions.delete(record.id)
            await instance_cursors(request).invalidate_namespace(record.scope_namespace)
        response.delete_cookie(
            active_settings.cookie_name,
            path="/",
            secure=active_settings.cookie_secure,
            httponly=True,
            samesite="lax",
        )

    @app.get("/api/v1/projects", response_model=ProjectPage)
    async def projects(
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
    ) -> ProjectPage:
        if limit not in {10, 25, 50, 100}:
            raise ApiError(
                422,
                "invalid_page_size",
                "Invalid page size",
                "Allowed values are 10, 25, 50, and 100",
            )
        filtered = [
            project
            for project in record.projects
            if name is None or name.casefold() in project.name.casefold()
        ]
        total = len(filtered)
        start = (page - 1) * limit
        items = filtered[start : start + limit]
        pages = math.ceil(total / limit) if total else 0
        return ProjectPage(
            items=items,
            page=PageInfo(
                number=page,
                size=limit,
                item_from=start + 1 if items else 0,
                item_to=start + len(items) if items else 0,
                total_items=total,
                total_pages=pages,
                has_previous=page > 1,
                has_next=page < pages,
                navigable_pages=_navigable_pages(page, pages),
            ),
        )

    @app.put("/api/v1/scope", response_model=SessionResponse)
    async def set_scope(
        payload: ScopeRequest,
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(csrf_session)],
    ) -> SessionResponse:
        visible = {project.id for project in record.projects}
        if payload.project_id not in visible or payload.region not in record.regions:
            raise ApiError(
                403,
                "scope_forbidden",
                "Scope unavailable",
                "The requested scope is not accessible",
            )
        try:
            result = await request.app.state.adapter.scope(
                record.auth_context, payload.project_id, payload.region
            )
        except ScopeError as exc:
            if exc.status_code == 401:
                await invalidate_session(request, record)
                error = ApiError(
                    401,
                    "unauthenticated",
                    "Authentication required",
                    "Session missing or expired",
                    openstack_request_id=exc.request_id,
                )
            elif exc.status_code == 403:
                error = ApiError(
                    403,
                    "scope_forbidden",
                    "Scope unavailable",
                    "The requested scope is not accessible",
                    openstack_request_id=exc.request_id,
                )
            elif exc.status_code == 404:
                error = ApiError(
                    404,
                    "scope_unavailable",
                    "Scope unavailable",
                    "The requested scope is unavailable",
                    openstack_request_id=exc.request_id,
                )
            elif exc.status_code == 429:
                error = ApiError(
                    429,
                    "identity_rate_limited",
                    "Scope temporarily unavailable",
                    "The identity service rate limited the request",
                    openstack_request_id=exc.request_id,
                )
            elif exc.status_code >= 500:
                error = ApiError(
                    503,
                    "identity_unavailable",
                    "Scope temporarily unavailable",
                    "The identity service is unavailable",
                    openstack_request_id=exc.request_id,
                )
            else:
                error = ApiError(
                    409,
                    "scope_failed",
                    "Scope unavailable",
                    "The requested scope could not be established",
                    openstack_request_id=exc.request_id,
                )
            raise error from exc
        scope_changed = (
            record.active_scope is None
            or record.active_scope.project.id != result.project.id
            or record.active_scope.region != result.region
        )
        updated = rotated_session(
            record,
            auth_context=result.auth_context,
            active_scope=Scope(project=result.project, region=result.region),
            scope_namespace=(new_scope_namespace() if scope_changed else record.scope_namespace),
            expires_at=min(
                record.expires_at,
                result.expires_at or record.expires_at,
            ),
        )
        if not await request.app.state.sessions.rotate(record.id, updated):
            raise ApiError(401, "session_changed", "Authentication required", "Session has changed")
        if scope_changed:
            await instance_cursors(request).invalidate_namespace(record.scope_namespace)
        set_session_cookie(response, updated)
        return updated.public()

    @app.get("/api/v1/overview", response_model=ProjectOverview)
    async def overview(
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> ProjectOverview:
        if record.active_scope is None:
            raise ApiError(
                409,
                "active_scope_required",
                "Project scope required",
                "Select a project and region before requesting project resources",
            )
        quotas, errors = await collect_quotas(
            request,
            record,
            tuple(QuotaService),
        )
        instances = next(
            (
                quota
                for quota in quotas
                if quota.service is QuotaService.COMPUTE and quota.resource == "instances"
            ),
            None,
        )
        return ProjectOverview(
            scope=record.active_scope,
            generated_at=datetime.now(UTC),
            quotas=quotas,
            instance_summary=(
                InstanceSummary(total=instances.used) if instances is not None else None
            ),
            partial_errors=errors,
        )

    @app.get("/api/v1/quotas", response_model=QuotaCollection)
    async def quotas(
        request: Request,
        record: Annotated[SessionRecord, Depends(current_session)],
        service: Annotated[QuotaService | None, Query()] = None,
    ) -> QuotaCollection:
        if record.active_scope is None:
            raise ApiError(
                409,
                "active_scope_required",
                "Project scope required",
                "Select a project and region before requesting project resources",
            )
        services = (service,) if service is not None else tuple(QuotaService)
        items, errors = await collect_quotas(request, record, services)
        return QuotaCollection(
            scope=record.active_scope,
            generated_at=datetime.now(UTC),
            quotas=items,
            partial_errors=errors,
        )

    @app.get("/api/v1/images", response_model=ImagePage)
    async def images(
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
        visibility: Annotated[ImageVisibility | None, Query()] = None,
    ) -> ImagePage:
        scope = active_scope(record)
        normalized_name = normalized_optional_filter(name)
        adapter = cast(OpenStackAdapter, request.app.state.adapter)

        async def load(marker: str | None) -> ProvisioningListResult:
            return await adapter.list_images(
                record.auth_context,
                scope.project.id,
                scope.region,
                limit=limit + 1,
                marker=marker,
                name=normalized_name,
                visibility=visibility,
            )

        items, page_info = await provisioning_page(
            request,
            response,
            record,
            resource="images",
            singular="image",
            service="Image",
            limit=limit,
            page=page,
            filters=(
                ("name", normalized_name),
                ("visibility", visibility.value if visibility else None),
            ),
            load=load,
        )
        return ImagePage(items=items, page=page_info)

    @app.get("/api/v1/flavors", response_model=FlavorPage)
    async def flavors(
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> FlavorPage:
        scope = active_scope(record)
        adapter = cast(OpenStackAdapter, request.app.state.adapter)

        async def load(marker: str | None) -> ProvisioningListResult:
            return await adapter.list_flavors(
                record.auth_context,
                scope.project.id,
                scope.region,
                limit=limit + 1,
                marker=marker,
            )

        items, page_info = await provisioning_page(
            request,
            response,
            record,
            resource="flavors",
            singular="flavor",
            service="Compute",
            limit=limit,
            page=page,
            filters=(),
            load=load,
        )
        return FlavorPage(items=items, page=page_info)

    @app.get("/api/v1/keypairs", response_model=KeyPairPage)
    async def keypairs(
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> KeyPairPage:
        scope = active_scope(record)
        adapter = cast(OpenStackAdapter, request.app.state.adapter)

        async def load(marker: str | None) -> ProvisioningListResult:
            return await adapter.list_keypairs(
                record.auth_context,
                scope.project.id,
                scope.region,
                limit=limit + 1,
                marker=marker,
            )

        items, page_info = await provisioning_page(
            request,
            response,
            record,
            resource="keypairs",
            singular="keypair",
            service="Compute",
            limit=limit,
            page=page,
            filters=(),
            load=load,
        )
        return KeyPairPage(items=items, page=page_info)

    @app.post(
        "/api/v1/keypairs",
        response_model=CreatedKeyPair | OperationResponse,
        status_code=201,
    )
    async def create_keypair(
        payload: CreateKeyPairRequest,
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str, Depends(validated_idempotency_key)],
    ) -> CreatedKeyPair | OperationResponse:
        scope = operation_scope(record)
        kind = f"keypair.{payload.mode.value}"
        begun = await begin_keypair_operation(
            request,
            scope=scope,
            idempotency_key=idempotency_key,
            kind=kind,
            fingerprint_payload=payload.model_dump(mode="json"),
            name=payload.name,
        )
        if begun.replayed:
            await raise_replayed_failure(request, record, begun.operation)
            if payload.mode is KeyPairMode.GENERATE:
                request_id = (
                    begun.operation.openstack_request_ids[-1]
                    if begun.operation.openstack_request_ids
                    else None
                )
                if begun.operation.status in {
                    OperationStatus.ACCEPTED,
                    OperationStatus.RUNNING,
                }:
                    raise ApiError(
                        409,
                        "operation_in_progress",
                        "Operation in progress",
                        "The original key pair request is still being processed",
                        openstack_request_id=request_id,
                    )
                raise ApiError(
                    409,
                    "one_time_secret_unavailable",
                    "Private key unavailable",
                    "Generated private key material is only returned to the original request",
                    openstack_request_id=request_id,
                )
            response.status_code = 202
            preserve_operation_request_id(response, begun.operation)
            return _operation_response(begun.operation)

        await operations(request).mark_running(scope, begun.operation.id)
        adapter = cast(OpenStackAdapter, request.app.state.adapter)
        try:
            result = await asyncio.wait_for(
                adapter.create_keypair(
                    record.auth_context,
                    scope.project_id,
                    scope.region,
                    name=payload.name,
                    key_type=payload.type,
                    public_key=payload.public_key,
                ),
                timeout=active_settings.provisioning_source_timeout_seconds,
            )
        except TimeoutError as exc:
            error = await keypair_api_error(request, record, AdapterTimeoutError())
            await fail_keypair_operation(
                request,
                scope=scope,
                operation_id=begun.operation.id,
                error=error,
                cause=exc,
            )
        except AdapterError as exc:
            error = await keypair_api_error(request, record, exc)
            await fail_keypair_operation(
                request,
                scope=scope,
                operation_id=begun.operation.id,
                error=error,
                cause=exc,
            )

        generated_private_key = result.private_key
        if payload.mode is KeyPairMode.GENERATE and not generated_private_key:
            malformed = AdapterError(
                status_code=503,
                request_id=result.openstack_request_id,
            )
            error = await keypair_api_error(request, record, malformed)
            await fail_keypair_operation(
                request,
                scope=scope,
                operation_id=begun.operation.id,
                error=error,
                cause=malformed,
            )

        succeeded = await operations(request).succeed(
            scope,
            begun.operation.id,
            target=StoredOperationTarget(
                resource_type="keypair",
                resource_name=result.keypair.name,
            ),
            openstack_request_ids=(
                (result.openstack_request_id,) if result.openstack_request_id else ()
            ),
        )
        if succeeded is None:
            raise ApiError(
                503,
                "operation_state_unavailable",
                "Operation state unavailable",
                "The key pair operation state could not be recorded",
            )
        preserve_operation_request_id(response, succeeded)
        if payload.mode is KeyPairMode.IMPORT:
            response.status_code = 202
            return _operation_response(succeeded)

        if generated_private_key is None:
            raise ApiError(
                503,
                "keypair_unavailable",
                "Key pair service unavailable",
                "The compute service did not return generated private key material",
            )
        response.status_code = 201
        return CreatedKeyPair(
            keypair=result.keypair,
            private_key=generated_private_key,
        )

    @app.delete(
        "/api/v1/keypairs/{keypair_name:path}",
        response_model=OperationResponse,
        status_code=202,
    )
    async def delete_keypair(
        keypair_name: Annotated[str, PathParameter(min_length=1, max_length=255)],
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(csrf_session)],
        idempotency_key: Annotated[str, Depends(validated_idempotency_key)],
    ) -> OperationResponse:
        scope = operation_scope(record)
        begun = await begin_keypair_operation(
            request,
            scope=scope,
            idempotency_key=idempotency_key,
            kind="keypair.delete",
            fingerprint_payload={"name": keypair_name},
            name=keypair_name,
        )
        if begun.replayed:
            await raise_replayed_failure(request, record, begun.operation)
            preserve_operation_request_id(response, begun.operation)
            return _operation_response(begun.operation)

        await operations(request).mark_running(scope, begun.operation.id)
        adapter = cast(OpenStackAdapter, request.app.state.adapter)
        try:
            result = await asyncio.wait_for(
                adapter.delete_keypair(
                    record.auth_context,
                    scope.project_id,
                    scope.region,
                    name=keypair_name,
                ),
                timeout=active_settings.provisioning_source_timeout_seconds,
            )
        except TimeoutError as exc:
            error = await keypair_api_error(request, record, AdapterTimeoutError())
            await fail_keypair_operation(
                request,
                scope=scope,
                operation_id=begun.operation.id,
                error=error,
                cause=exc,
            )
        except AdapterError as exc:
            error = await keypair_api_error(request, record, exc)
            await fail_keypair_operation(
                request,
                scope=scope,
                operation_id=begun.operation.id,
                error=error,
                cause=exc,
            )

        succeeded = await operations(request).succeed(
            scope,
            begun.operation.id,
            openstack_request_ids=(
                (result.openstack_request_id,) if result.openstack_request_id else ()
            ),
        )
        if succeeded is None:
            raise ApiError(
                503,
                "operation_state_unavailable",
                "Operation state unavailable",
                "The key pair operation state could not be recorded",
            )
        preserve_operation_request_id(response, succeeded)
        return _operation_response(succeeded)

    @app.get("/api/v1/operations/{operation_id}", response_model=OperationResponse)
    async def get_operation(
        operation_id: uuid.UUID,
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> OperationResponse:
        active = record.active_scope
        if active is None:
            raise ApiError(
                404,
                "operation_not_found",
                "Operation not found",
                "The operation does not exist in the active scope",
            )
        scope = OperationScope(
            user_id=record.user.id,
            project_id=active.project.id,
            region=active.region,
        )
        snapshot = await operations(request).get(scope, operation_id)
        if snapshot is None:
            raise ApiError(
                404,
                "operation_not_found",
                "Operation not found",
                "The operation does not exist in the active scope",
            )
        preserve_operation_request_id(response, snapshot)
        return _operation_response(snapshot)

    @app.get("/api/v1/networks", response_model=NetworkPage)
    async def networks(
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
        status: Annotated[str | None, Query(max_length=64)] = None,
    ) -> NetworkPage:
        scope = active_scope(record)
        normalized_name = normalized_optional_filter(name)
        normalized_status_value = normalized_optional_filter(status)
        normalized_status = normalized_status_value.upper() if normalized_status_value else None
        adapter = cast(OpenStackAdapter, request.app.state.adapter)

        async def load(marker: str | None) -> ProvisioningListResult:
            return await adapter.list_networks(
                record.auth_context,
                scope.project.id,
                scope.region,
                limit=limit + 1,
                marker=marker,
                name=normalized_name,
                status=normalized_status,
            )

        items, page_info = await provisioning_page(
            request,
            response,
            record,
            resource="networks",
            singular="network",
            service="Network",
            limit=limit,
            page=page,
            filters=(("name", normalized_name), ("status", normalized_status)),
            load=load,
        )
        return NetworkPage(items=items, page=page_info)

    @app.get("/api/v1/security-groups", response_model=SecurityGroupPage)
    async def security_groups(
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
    ) -> SecurityGroupPage:
        scope = active_scope(record)
        normalized_name = normalized_optional_filter(name)
        adapter = cast(OpenStackAdapter, request.app.state.adapter)

        async def load(marker: str | None) -> ProvisioningListResult:
            return await adapter.list_security_groups(
                record.auth_context,
                scope.project.id,
                scope.region,
                limit=limit + 1,
                marker=marker,
                name=normalized_name,
            )

        items, page_info = await provisioning_page(
            request,
            response,
            record,
            resource="security-groups",
            singular="security_group",
            service="Network",
            limit=limit,
            page=page,
            filters=(("name", normalized_name),),
            load=load,
        )
        return SecurityGroupPage(items=items, page=page_info)

    @app.get("/api/v1/instances", response_model=InstancePage)
    async def instances(
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
        limit: Annotated[int, Query()] = 25,
        page: Annotated[int, Query(ge=1)] = 1,
        name: Annotated[str | None, Query(max_length=255)] = None,
        status: Annotated[str | None, Query(max_length=64)] = None,
        image_id: Annotated[str | None, Query(max_length=255)] = None,
        sort: Annotated[InstanceSort, Query()] = InstanceSort.CREATED_AT,
        direction: Annotated[SortDirection, Query()] = SortDirection.DESC,
    ) -> InstancePage:
        if limit not in {10, 25, 50, 100}:
            raise ApiError(
                422,
                "invalid_page_size",
                "Invalid page size",
                "Allowed values are 10, 25, 50, and 100",
            )
        scope = active_scope(record)
        normalized_name = normalized_optional_filter(name)
        normalized_status_value = normalized_optional_filter(status)
        normalized_status = (
            normalized_status_value.upper() if normalized_status_value is not None else None
        )
        normalized_image_id = normalized_optional_filter(image_id)
        cursor_key = instance_cursor_key(
            record,
            limit=limit,
            name=normalized_name,
            status=normalized_status,
            image_id=normalized_image_id,
            sort=sort,
            direction=direction,
        )
        cursors = instance_cursors(request)
        lease = await cursors.acquire(cursor_key, page)
        if lease is None:
            raise ApiError(
                409,
                "page_cursor_unavailable",
                "Page not available yet",
                "Open the preceding instance page before requesting this page",
            )

        cursor_committed = False
        try:
            try:
                adapter = cast(OpenStackAdapter, request.app.state.adapter)
                result = await asyncio.wait_for(
                    adapter.list_instances(
                        record.auth_context,
                        scope.project.id,
                        scope.region,
                        limit=limit + 1,
                        marker=lease.marker,
                        name=normalized_name,
                        status=normalized_status,
                        image_id=normalized_image_id,
                        sort=sort,
                        direction=direction,
                    ),
                    timeout=active_settings.instance_source_timeout_seconds,
                )
            except TimeoutError:
                await raise_instance_error(
                    request,
                    record,
                    AdapterTimeoutError(),
                    detail=False,
                    cursor_key=cursor_key,
                    marker_bound=lease.marker is not None,
                )
            except AdapterError as exc:
                await raise_instance_error(
                    request,
                    record,
                    exc,
                    detail=False,
                    cursor_key=cursor_key,
                    marker_bound=lease.marker is not None,
                )

            visible_items = list(result.items[:limit])
            has_next = len(result.items) > limit or result.has_next
            next_marker = str(visible_items[-1].id) if has_next and visible_items else None
            known_pages = await cursors.complete(lease, next_marker)
            if known_pages is None:
                raise ApiError(
                    409,
                    "page_cursor_changed",
                    "Instance pages changed",
                    "A newer page refresh replaced this response",
                )
            cursor_committed = True
            known_max = max(known_pages)
            has_next = has_next and page + 1 in known_pages
            start = (page - 1) * limit
            if result.openstack_request_id is not None:
                response.headers["X-OpenStack-Request-ID"] = result.openstack_request_id
            return InstancePage(
                items=visible_items,
                page=PageInfo(
                    number=page,
                    size=limit,
                    item_from=start + 1 if visible_items else 0,
                    item_to=start + len(visible_items) if visible_items else 0,
                    total_items=None,
                    total_pages=None,
                    has_previous=page > 1,
                    has_next=has_next,
                    navigable_pages=_navigable_pages(page, known_max),
                    openstack_request_id=result.openstack_request_id,
                ),
            )
        finally:
            if not cursor_committed:
                await cursors.abandon(lease)

    @app.get("/api/v1/instances/{instance_id}", response_model=InstanceDetail)
    async def instance_detail(
        instance_id: uuid.UUID,
        request: Request,
        response: Response,
        record: Annotated[SessionRecord, Depends(current_session)],
    ) -> InstanceDetail:
        scope = active_scope(record)
        adapter = cast(OpenStackAdapter, request.app.state.adapter)
        try:
            result = await asyncio.wait_for(
                adapter.get_instance(
                    record.auth_context,
                    scope.project.id,
                    scope.region,
                    str(instance_id),
                ),
                timeout=active_settings.instance_source_timeout_seconds,
            )
        except TimeoutError:
            await raise_instance_error(
                request,
                record,
                AdapterTimeoutError(),
                detail=True,
            )
        except AdapterError as exc:
            await raise_instance_error(request, record, exc, detail=True)
        if result.openstack_request_id is not None:
            response.headers["X-OpenStack-Request-ID"] = result.openstack_request_id
        return result

    if (frontend_root / "index.html").is_file():
        app.mount(
            "/assets",
            StaticFiles(directory=frontend_root / "assets"),
            name="frontend-assets",
        )

        @app.get("/", include_in_schema=False)
        @app.get("/login", include_in_schema=False)
        @app.get("/projects/select", include_in_schema=False)
        @app.get("/overview", include_in_schema=False)
        @app.get("/quotas", include_in_schema=False)
        @app.get("/instances", include_in_schema=False)
        @app.get("/instances/{instance_id}", include_in_schema=False)
        @app.get("/images", include_in_schema=False)
        @app.get("/keypairs", include_in_schema=False)
        async def frontend() -> FileResponse:
            return FileResponse(frontend_root / "index.html")

    return app


app = create_app()
