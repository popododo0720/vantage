from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.adapters.openstack_sdk import OpenStackSdkAdapter
from vantage_bff.app import create_app
from vantage_bff.cache import CacheKey, CoalescingCache, MemoryJsonCache
from vantage_bff.config import Settings
from vantage_bff.models import QuotaService


def test_production_configuration_requires_redis_and_secure_cookie() -> None:
    with pytest.raises(ValueError, match="Production requires.*redis"):
        Settings(environment="production")
    with pytest.raises(ValueError, match="secure session cookies"):
        Settings(
            environment="production",
            adapter="openstack",
            store_backend="redis",
            redis_url="redis://redis:6379/0",
            cookie_secure=False,
        )


@pytest.mark.asyncio
async def test_cache_coalesces_misses_and_never_crosses_policy_scope() -> None:
    cache = CoalescingCache(MemoryJsonCache(max_entries=10))
    calls = 0

    async def load() -> Mapping[str, Any]:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0.01)
        return {"items": [1]}

    first = CacheKey("user", "project", "RegionOne", "scope-a", "compute", "quota")
    other = CacheKey("user", "project", "RegionOne", "scope-b", "compute", "quota")
    results = await asyncio.gather(*(cache.get_or_load(first, load, 10) for _ in range(25)))
    assert calls == 1
    assert sum(1 for _, _, coalesced in results if coalesced) == 24

    await cache.get_or_load(other, load, 10)
    assert calls == 2
    await cache.invalidate_policy_scope("scope-a")
    await cache.get_or_load(first, load, 10)
    assert calls == 3


class ParallelQuotaAdapter(FakeOpenStackAdapter):
    def __init__(self) -> None:
        self.entered: set[QuotaService] = set()
        self.all_entered = asyncio.Event()
        self.calls: dict[QuotaService, int] = {service: 0 for service in QuotaService}

    async def quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Any, ...]:
        self.calls[service] += 1
        self.entered.add(service)
        if len(self.entered) == len(QuotaService):
            self.all_entered.set()
        await asyncio.wait_for(self.all_entered.wait(), timeout=0.25)
        return await super().quotas(auth_context, project_id, region, service)


@pytest.mark.asyncio
async def test_overview_fans_out_in_parallel_and_warm_request_uses_cache() -> None:
    adapter = ParallelQuotaAdapter()
    app = create_app(
        Settings(cookie_secure=False, quota_source_timeout_seconds=0.5),
        adapter=adapter,
    )
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            login = await client.post(
                "/api/v1/session/login",
                json={"username": "demo", "password": "vantage", "domain": "default"},
            )
            csrf = login.headers["X-CSRF-Token"]
            scope = await client.put(
                "/api/v1/scope",
                headers={"X-CSRF-Token": csrf},
                json={"project_id": "project-alpha", "region": "RegionOne"},
            )
            assert scope.status_code == 200

            cold_responses = await asyncio.gather(
                *(client.get("/api/v1/overview") for _ in range(20))
            )
            second = await client.get("/api/v1/overview")
            assert all(response.status_code == 200 for response in cold_responses)
            assert second.status_code == 200
            assert adapter.calls == {service: 1 for service in QuotaService}


@pytest.mark.asyncio
async def test_health_metrics_are_available_without_openstack() -> None:
    app = create_app(Settings(cookie_secure=False))
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/health/live")).json() == {"status": "ok"}
            assert (await client.get("/health/ready")).json() == {"status": "ready"}
            metrics = await client.get("/metrics")
            assert metrics.status_code == 200
            assert "vantage_http_request_duration_seconds_bucket" in metrics.text


def test_structured_log_formatter_drops_secret_fields() -> None:
    import logging

    from vantage_bff.observability import JsonFormatter

    record = logging.LogRecord("test", logging.INFO, "", 0, "done", (), None)
    record.fields = {"trace_id": "trace", "password": "secret", "token": "secret-token"}
    payload = json.loads(JsonFormatter().format(record))
    assert payload["trace_id"] == "trace"
    assert "password" not in payload
    assert "token" not in payload


def test_sdk_connection_is_reused_per_worker_thread_and_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openstack.connection

    calls: list[dict[str, Any]] = []

    class Connection:
        def __init__(self, **kwargs: Any) -> None:
            calls.append(kwargs)
            self.session = SimpleNamespace(global_request_id=kwargs["global_request_id"])

    monkeypatch.setattr(openstack.connection, "Connection", Connection)
    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3", "internal", "RegionOne", 15
    )
    context = {
        "scoped_token": "server-only",
        "project_id": "project-alpha",
        "region": "RegionOne",
    }

    first = adapter._project_connection(context, "project-alpha", "RegionOne", "req-first")
    second = adapter._project_connection(context, "project-alpha", "RegionOne", "req-second")

    assert first is second
    assert len(calls) == 1
    assert second.session.global_request_id == "req-second"
