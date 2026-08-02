import asyncio
import hmac
import math
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, cast

from fastapi import Cookie, Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from vantage_bff.adapters.base import (
    AdapterError,
    AuthenticationError,
    OpenStackAdapter,
    ScopeError,
)
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.adapters.openstack_sdk import OpenStackSdkAdapter
from vantage_bff.config import Settings
from vantage_bff.models import (
    InstanceSummary,
    LoginRequest,
    PageInfo,
    Problem,
    ProjectOverview,
    ProjectPage,
    Quota,
    QuotaCollection,
    QuotaService,
    Scope,
    ScopeRequest,
    SessionPreferenceRequest,
    SessionResponse,
    WidgetError,
)
from vantage_bff.rate_limit import LoginRateLimiter
from vantage_bff.sessions import (
    MemorySessionStore,
    SessionRecord,
    SessionStore,
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
            settings.auth_url,
            settings.interface,
            settings.default_region,
            settings.request_timeout_seconds,
            settings.quota_source_timeout_seconds,
        )
    raise RuntimeError(f"Unsupported adapter: {settings.adapter}")


def create_app(
    settings: Settings | None = None,
    adapter: OpenStackAdapter | None = None,
    store: SessionStore | None = None,
) -> FastAPI:
    active_settings = settings or Settings.from_env()
    frontend_root = Path(__file__).resolve().parents[2] / "frontend" / "dist"

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.settings = active_settings
        app.state.adapter = adapter or _adapter(active_settings)
        app.state.sessions = store or MemorySessionStore()
        app.state.login_limiter = LoginRateLimiter(
            active_settings.login_attempt_limit,
            active_settings.login_attempt_window_seconds,
        )
        yield

    app = FastAPI(title="Vantage BFF", version="0.2.0", lifespan=lifespan)

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
                await request.app.state.sessions.delete(record.id)
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
                message = (
                    f"{service.value.capitalize()} quota data is not available for this scope"
                )
            elif isinstance(result, AdapterError) and result.status_code == 429:
                suffix = "rate_limited"
                message = (
                    f"{service.value.capitalize()} quota data is temporarily rate limited"
                )
            else:
                suffix = "unavailable"
                message = (
                    f"{service.value.capitalize()} quota data is temporarily unavailable"
                )
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
            await request.app.state.sessions.delete(previous_session_id)
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
            project for project in record.projects
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
                await request.app.state.sessions.delete(record.id)
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
        updated = rotated_session(
            record,
            auth_context=result.auth_context,
            active_scope=Scope(project=result.project, region=result.region),
            expires_at=min(
                record.expires_at,
                result.expires_at or record.expires_at,
            ),
        )
        if not await request.app.state.sessions.rotate(record.id, updated):
            raise ApiError(401, "session_changed", "Authentication required", "Session has changed")
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
                if quota.service is QuotaService.COMPUTE
                and quota.resource == "instances"
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
        async def frontend() -> FileResponse:
            return FileResponse(frontend_root / "index.html")

    return app


app = create_app()
