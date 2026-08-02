from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vantage_bff.adapters.base import AdapterError, normalized_quota, quota_state
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.adapters.openstack_sdk import OpenStackSdkAdapter, _normalize_quota_resource
from vantage_bff.app import _adapter, create_app
from vantage_bff.config import Settings
from vantage_bff.models import Quota, QuotaService, QuotaState, QuotaUnit


class ControlledQuotaAdapter(FakeOpenStackAdapter):
    def __init__(self) -> None:
        self.calls: list[QuotaService] = []
        self.failures: dict[QuotaService, AdapterError] = {}
        self.delays: dict[QuotaService, float] = {}

    async def quotas(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        service: QuotaService,
    ) -> tuple[Quota, ...]:
        self.calls.append(service)
        if delay := self.delays.get(service):
            await asyncio.sleep(delay)
        if failure := self.failures.get(service):
            raise failure
        return await super().quotas(auth_context, project_id, region, service)


@contextmanager
def client_for(
    adapter: ControlledQuotaAdapter,
    *,
    timeout: float = 0.1,
) -> Iterator[TestClient]:
    settings = Settings(
        cookie_secure=True,
        quota_source_timeout_seconds=timeout,
    )
    with TestClient(
        create_app(settings, adapter=adapter),
        base_url="https://testserver",
    ) as client:
        yield client


def login(client: TestClient) -> str:
    response = client.post(
        "/api/v1/session/login",
        json={"username": "alice", "password": "vantage", "domain": "default"},
    )
    assert response.status_code == 201
    return response.headers["X-CSRF-Token"]


def select_scope(client: TestClient, csrf: str) -> None:
    response = client.put(
        "/api/v1/scope",
        json={"project_id": "project-alpha", "region": "RegionOne"},
        headers={"X-CSRF-Token": csrf},
    )
    assert response.status_code == 200


def test_overview_returns_quota_first_snapshot_without_enumerating_servers() -> None:
    adapter = ControlledQuotaAdapter()
    with client_for(adapter) as client:
        select_scope(client, login(client))

        response = client.get("/api/v1/overview")

    assert response.status_code == 200
    body = response.json()
    assert body["scope"]["project"]["id"] == "project-alpha"
    assert {item["service"] for item in body["quotas"]} == {
        "compute",
        "network",
        "storage",
    }
    assert body["instance_summary"] == {
        "total": 37,
        "active": None,
        "stopped": None,
        "error": None,
    }
    assert body["partial_errors"] == []
    assert set(adapter.calls) == set(QuotaService)


def test_quota_service_filter_calls_only_requested_source() -> None:
    adapter = ControlledQuotaAdapter()
    with client_for(adapter) as client:
        select_scope(client, login(client))
        adapter.calls.clear()

        response = client.get("/api/v1/quotas?service=network")

    assert response.status_code == 200
    assert adapter.calls == [QuotaService.NETWORK]
    assert [item["resource"] for item in response.json()["quotas"]] == ["floating_ips"]


def test_one_quota_failure_preserves_other_service_widgets() -> None:
    adapter = ControlledQuotaAdapter()
    adapter.failures[QuotaService.NETWORK] = AdapterError(
        status_code=503,
        request_id="req-network",
    )
    with client_for(adapter) as client:
        select_scope(client, login(client))

        response = client.get("/api/v1/overview")

    assert response.status_code == 200
    body = response.json()
    assert {item["service"] for item in body["quotas"]} == {"compute", "storage"}
    assert body["partial_errors"] == [{
        "code": "network_quota_unavailable",
        "message": "Network quota data is temporarily unavailable",
        "openstack_request_id": "req-network",
    }]


def test_quota_policy_denial_preserves_authoritative_error_semantics() -> None:
    adapter = ControlledQuotaAdapter()
    adapter.failures[QuotaService.NETWORK] = AdapterError(
        status_code=403,
        request_id="req-policy",
    )
    with client_for(adapter) as client:
        select_scope(client, login(client))

        response = client.get("/api/v1/overview")

    assert response.status_code == 200
    assert response.json()["partial_errors"] == [{
        "code": "network_quota_forbidden",
        "message": "Network quota data is not available for this scope",
        "openstack_request_id": "req-policy",
    }]


def test_slow_quota_source_times_out_without_blocking_snapshot() -> None:
    adapter = ControlledQuotaAdapter()
    adapter.delays[QuotaService.STORAGE] = 0.1
    with client_for(adapter, timeout=0.01) as client:
        select_scope(client, login(client))

        response = client.get("/api/v1/overview")

    assert response.status_code == 200
    body = response.json()
    assert {item["service"] for item in body["quotas"]} == {"compute", "network"}
    assert body["partial_errors"][0]["code"] == "storage_quota_timeout"
    assert "openstack_request_id" not in body["partial_errors"][0]


def test_widget_error_schema_is_optional_string_not_nullable() -> None:
    schema = create_app(Settings()).openapi()["components"]["schemas"]["WidgetError"]

    assert set(schema["required"]) == {"code", "message"}
    assert schema["properties"]["openstack_request_id"]["type"] == "string"
    assert "openstack_request_id" not in schema["required"]


@pytest.mark.parametrize("path", ["/api/v1/overview", "/api/v1/quotas"])
def test_quota_endpoints_require_an_active_scope(path: str) -> None:
    adapter = ControlledQuotaAdapter()
    with client_for(adapter) as client:
        login(client)

        response = client.get(path)

    assert response.status_code == 409
    assert response.json()["code"] == "active_scope_required"
    assert adapter.calls == []


def test_upstream_401_invalidates_server_session() -> None:
    adapter = ControlledQuotaAdapter()
    adapter.failures[QuotaService.COMPUTE] = AdapterError(
        status_code=401,
        request_id="req-expired",
    )
    with client_for(adapter) as client:
        select_scope(client, login(client))

        response = client.get("/api/v1/overview")
        stale_session = client.get("/api/v1/session")

    assert response.status_code == 401
    assert response.json()["code"] == "unauthenticated"
    assert response.json()["openstack_request_id"] == "req-expired"
    assert stale_session.status_code == 401


@pytest.mark.parametrize(
    ("used", "reserved", "limit", "expected"),
    [
        (1, 0, None, QuotaState.UNKNOWN),
        (1, 0, 0, QuotaState.UNKNOWN),
        (6, 0, 10, QuotaState.NORMAL),
        (6, 1, 10, QuotaState.WATCH),
        (8, 1, 10, QuotaState.HIGH),
    ],
)
def test_quota_pressure_includes_reserved_usage(
    used: int,
    reserved: int,
    limit: int | None,
    expected: QuotaState,
) -> None:
    assert quota_state(used, reserved, limit) is expected


def test_negative_limit_is_normalized_as_unlimited() -> None:
    quota = normalized_quota(
        service=QuotaService.COMPUTE,
        resource="instances",
        used=4,
        reserved=1,
        limit=-1,
        unit=QuotaUnit.COUNT,
    )
    assert quota.limit is None
    assert quota.state is QuotaState.UNKNOWN


def test_app_wires_a_separate_quota_sdk_timeout() -> None:
    adapter = _adapter(Settings(
        adapter="openstack",
        auth_url="https://keystone.example/v3",
        request_timeout_seconds=15,
        quota_source_timeout_seconds=2.5,
        instance_source_timeout_seconds=1.5,
    ))

    assert isinstance(adapter, OpenStackSdkAdapter)
    assert adapter.request_timeout_seconds == 15
    assert adapter.quota_timeout_seconds == 2.5
    assert adapter.instance_timeout_seconds == 1.5


def test_sdk_resource_normalization_accepts_usage_and_detail_shapes() -> None:
    compute = _normalize_quota_resource(
        QuotaService.COMPUTE,
        {
            "instances": {"limit": 10, "in_use": 8, "reserved": 1},
            "cores": {"limit": "20", "used": "14", "reserved": "0"},
            "ram": {"limit": -1, "in_use": 2048, "reserved": 0},
        },
    )
    network = _normalize_quota_resource(
        QuotaService.NETWORK,
        {"floatingip": {"limit": 5, "used": 2, "reserved": 1}},
    )

    assert compute[0].state is QuotaState.HIGH
    assert compute[1].state is QuotaState.WATCH
    assert compute[2].limit is None
    assert network[0].model_dump(mode="json") == {
        "service": "network",
        "resource": "floating_ips",
        "used": 2,
        "reserved": 1,
        "limit": 5,
        "unit": "count",
        "state": "normal",
    }


def test_sdk_resource_normalization_omits_absent_quota_fields() -> None:
    storage = _normalize_quota_resource(
        QuotaService.STORAGE,
        {"volumes": {"limit": 20, "in_use": 8, "reserved": 0}},
    )

    assert [quota.resource for quota in storage] == ["volumes"]


class QuotaConnection:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    connection_options: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.connection_options.append(kwargs)
        self.compute = self
        self.network = self
        self.block_storage = self

    def get_quota_set(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("quota_set", args, kwargs))
        return {}

    def get_quota(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("quota", args, kwargs))
        return {}


@pytest.mark.parametrize(
    ("service", "expected"),
    [
        (QuotaService.COMPUTE, ("quota_set", ("project-alpha",), {"usage": True})),
        (QuotaService.NETWORK, ("quota", ("project-alpha",), {"details": True})),
        (QuotaService.STORAGE, ("quota_set", ("project-alpha",), {"usage": True})),
    ],
)
def test_sdk_uses_detailed_quota_calls(
    monkeypatch: pytest.MonkeyPatch,
    service: QuotaService,
    expected: tuple[str, tuple[str, ...], dict[str, bool]],
) -> None:
    import openstack.connection

    QuotaConnection.calls.clear()
    QuotaConnection.connection_options.clear()
    monkeypatch.setattr(openstack.connection, "Connection", QuotaConnection)
    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3", "public", "RegionOne", 15, 2.5
    )

    adapter._quotas(
        {"scoped_token": "server-only"},
        "project-alpha",
        "RegionOne",
        service,
    )

    assert QuotaConnection.calls == [expected]
    assert QuotaConnection.connection_options[0]["api_timeout"] == 2.5
    assert QuotaConnection.connection_options[0]["app_version"] == "0.3.0"
