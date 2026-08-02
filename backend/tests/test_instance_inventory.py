from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from vantage_bff.adapters.base import (
    AdapterError,
    AdapterTimeoutError,
    InstanceListResult,
)
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.adapters.openstack_sdk import (
    OpenStackSdkAdapter,
    _instance_failure,
    _normalize_instance,
    _normalize_instance_detail,
)
from vantage_bff.app import _navigable_pages, create_app
from vantage_bff.config import Settings
from vantage_bff.cursors import CursorKey, MemoryCursorStore
from vantage_bff.models import (
    Instance,
    InstanceDetail,
    InstanceSort,
    SortDirection,
)


class RecordingAdapter(FakeOpenStackAdapter):
    def __init__(self) -> None:
        self.list_calls: list[dict[str, Any]] = []
        self.detail_calls: list[str] = []
        self.list_failure: AdapterError | None = None
        self.detail_failure: AdapterError | None = None
        self.list_delay = 0.0
        self.detail_delay = 0.0

    async def list_instances(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
        image_id: str | None,
        sort: InstanceSort,
        direction: SortDirection,
    ) -> InstanceListResult:
        self.list_calls.append({
            "project_id": project_id,
            "region": region,
            "limit": limit,
            "marker": marker,
            "name": name,
            "status": status,
            "image_id": image_id,
            "sort": sort,
            "direction": direction,
        })
        if self.list_delay:
            await asyncio.sleep(self.list_delay)
        if self.list_failure is not None:
            raise self.list_failure
        return await super().list_instances(
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
            name=name,
            status=status,
            image_id=image_id,
            sort=sort,
            direction=direction,
        )

    async def get_instance(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        instance_id: str,
    ) -> InstanceDetail:
        self.detail_calls.append(instance_id)
        if self.detail_delay:
            await asyncio.sleep(self.detail_delay)
        if self.detail_failure is not None:
            raise self.detail_failure
        return await super().get_instance(
            auth_context,
            project_id,
            region,
            instance_id,
        )


class LargeInventoryAdapter(RecordingAdapter):
    total = 10_000

    def __init__(self, max_limit: int | None = None) -> None:
        super().__init__()
        self.generated = 0
        self.max_limit = max_limit

    async def list_instances(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        status: str | None,
        image_id: str | None,
        sort: InstanceSort,
        direction: SortDirection,
    ) -> InstanceListResult:
        del auth_context, name, status, image_id, sort, direction
        self.list_calls.append({
            "project_id": project_id,
            "region": region,
            "limit": limit,
            "marker": marker,
        })
        start = int(UUID(marker)) if marker is not None else 0
        effective_limit = min(limit, self.max_limit) if self.max_limit is not None else limit
        count = min(effective_limit, self.total - start)
        self.generated += count
        items = tuple(
            Instance(
                id=UUID(int=index + 1),
                status="ACTIVE",
                name=f"vm-{index + 1}",
                created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
                flavor="m1.small",
                image="image-one",
                addresses=[],
            )
            for index in range(start, start + count)
        )
        return InstanceListResult(
            items=items,
            has_next=start + count < self.total,
            openstack_request_id="req-00000000-0000-0000-0000-000000000010",
        )


class TrackingCursorStore(MemoryCursorStore):
    def __init__(self) -> None:
        super().__init__(ttl_seconds=300, max_chains=256, max_pages=1000)
        self.invalidated_namespaces: list[str] = []

    async def invalidate_namespace(self, scope_namespace: str) -> None:
        self.invalidated_namespaces.append(scope_namespace)
        await super().invalidate_namespace(scope_namespace)


@contextmanager
def client_for(
    adapter: FakeOpenStackAdapter,
    *,
    timeout: float = 0.1,
    cursors: MemoryCursorStore | None = None,
) -> Iterator[TestClient]:
    settings = Settings(
        cookie_secure=True,
        instance_source_timeout_seconds=timeout,
    )
    with TestClient(
        create_app(settings, adapter=adapter, cursor_store=cursors),
        base_url="https://testserver",
    ) as client:
        yield client


def login_and_scope(client: TestClient, project_id: str = "project-alpha") -> str:
    login = client.post(
        "/api/v1/session/login",
        json={"username": "alice", "password": "vantage", "domain": "default"},
    )
    assert login.status_code == 201
    scope = client.put(
        "/api/v1/scope",
        json={"project_id": project_id, "region": "RegionOne"},
        headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
    )
    assert scope.status_code == 200
    return scope.headers["X-CSRF-Token"]


def test_default_page_uses_limit_plus_one_and_progressive_markers() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)

        first = client.get("/api/v1/instances")
        unavailable = client.get("/api/v1/instances?page=3")
        second = client.get("/api/v1/instances?page=2")
        back = client.get("/api/v1/instances?page=1")

    assert first.status_code == 200
    first_body = first.json()
    assert len(first_body["items"]) == 25
    assert first_body["page"] == {
        "number": 1,
        "size": 25,
        "item_from": 1,
        "item_to": 25,
        "total_items": None,
        "total_pages": None,
        "has_previous": False,
        "has_next": True,
        "navigable_pages": [1, 2],
        "openstack_request_id": first.headers["X-OpenStack-Request-ID"],
    }
    assert unavailable.status_code == 409
    assert unavailable.json()["code"] == "page_cursor_unavailable"
    assert second.status_code == 200
    assert len(second.json()["items"]) == 12
    assert second.json()["page"]["navigable_pages"] == [1, 2]
    assert second.json()["page"]["has_next"] is False
    assert back.status_code == 200
    assert [call["limit"] for call in adapter.list_calls] == [26, 26, 26]
    assert adapter.list_calls[0]["marker"] is None
    assert adapter.list_calls[1]["marker"] == first_body["items"][-1]["id"]
    assert adapter.list_calls[2]["marker"] is None


@pytest.mark.parametrize("page_size", [10, 25, 50, 100])
def test_page_sizes_are_discrete_and_upstream_is_always_limit_plus_one(
    page_size: int,
) -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        response = client.get(f"/api/v1/instances?limit={page_size}")

    assert response.status_code == 200
    assert response.json()["page"]["size"] == page_size
    assert adapter.list_calls[-1]["limit"] == page_size + 1


def test_invalid_page_size_and_unvisited_page_never_reach_nova() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        bad_size = client.get("/api/v1/instances?limit=20")
        long_status = client.get(f"/api/v1/instances?status={'A' * 65}")
        unvisited = client.get("/api/v1/instances?page=2")

    assert bad_size.status_code == 422
    assert bad_size.json()["code"] == "invalid_page_size"
    assert long_status.status_code == 422
    assert long_status.json()["code"] == "invalid_request"
    assert unvisited.status_code == 409
    assert adapter.list_calls == []


def test_filters_sort_and_scope_are_forwarded_without_all_projects() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        baseline = client.get("/api/v1/instances?limit=10")
        image_id = baseline.json()["items"][0]["image"]
        response = client.get(
            "/api/v1/instances",
            params={
                "limit": 10,
                "name": "alpha",
                "status": "active",
                "image_id": image_id,
                "sort": "name",
                "direction": "asc",
            },
        )

    assert response.status_code == 200
    call = adapter.list_calls[-1]
    assert call == {
        "project_id": "project-alpha",
        "region": "RegionOne",
        "limit": 11,
        "marker": None,
        "name": "alpha",
        "status": "ACTIVE",
        "image_id": image_id,
        "sort": InstanceSort.NAME,
        "direction": SortDirection.ASC,
    }
    assert "all_projects" not in call


def test_empty_frontend_filters_are_normalized_before_nova_call() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        response = client.get(
            "/api/v1/instances?name=&status=&image_id=",
        )

    assert response.status_code == 200
    call = adapter.list_calls[-1]
    assert call["name"] is None
    assert call["status"] is None
    assert call["image_id"] is None


def test_failed_page_one_refresh_preserves_the_previous_marker_chain() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        assert client.get("/api/v1/instances").status_code == 200
        original_marker = adapter.list_calls[-1]["marker"]

        adapter.list_failure = AdapterError(status_code=503, request_id="req-refresh")
        failed_refresh = client.get("/api/v1/instances")
        adapter.list_failure = None
        second = client.get("/api/v1/instances?page=2")

    assert original_marker is None
    assert failed_refresh.status_code == 503
    assert second.status_code == 200
    assert adapter.list_calls[-1]["marker"] is not None


def test_locale_rotation_preserves_cursor_but_scope_and_logout_invalidate_it() -> None:
    adapter = RecordingAdapter()
    cursors = TrackingCursorStore()
    with client_for(adapter, cursors=cursors) as client:
        csrf = login_and_scope(client)
        baseline_invalidations = len(cursors.invalidated_namespaces)
        assert client.get("/api/v1/instances").status_code == 200

        locale = client.patch(
            "/api/v1/session",
            json={"locale": "ko"},
            headers={"X-CSRF-Token": csrf},
        )
        assert locale.status_code == 200
        assert client.get("/api/v1/instances?page=2").status_code == 200
        assert len(cursors.invalidated_namespaces) == baseline_invalidations

        switched = client.put(
            "/api/v1/scope",
            json={"project_id": "project-beta", "region": "RegionOne"},
            headers={"X-CSRF-Token": locale.headers["X-CSRF-Token"]},
        )
        assert switched.status_code == 200
        assert len(cursors.invalidated_namespaces) == baseline_invalidations + 1
        assert client.get("/api/v1/instances?page=2").status_code == 409
        assert client.get("/api/v1/instances").status_code == 200

        logged_out = client.delete(
            "/api/v1/session",
            headers={"X-CSRF-Token": switched.headers["X-CSRF-Token"]},
        )
        assert logged_out.status_code == 204
        assert len(cursors.invalidated_namespaces) == baseline_invalidations + 2


def test_upstream_401_invalidates_session_and_cursor_namespace() -> None:
    adapter = RecordingAdapter()
    cursors = TrackingCursorStore()
    with client_for(adapter, cursors=cursors) as client:
        login_and_scope(client)
        assert client.get("/api/v1/instances").status_code == 200
        baseline_invalidations = len(cursors.invalidated_namespaces)
        adapter.list_failure = AdapterError(status_code=401, request_id="req-expired")

        response = client.get("/api/v1/instances?page=2")
        stale_session = client.get("/api/v1/session")

    assert response.status_code == 401
    assert response.json()["openstack_request_id"] == "req-expired"
    assert stale_session.status_code == 401
    assert len(cursors.invalidated_namespaces) == baseline_invalidations + 1


@pytest.mark.parametrize("upstream_status", [400, 404])
def test_disappeared_stored_marker_becomes_cursor_conflict(
    upstream_status: int,
) -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        assert client.get("/api/v1/instances").status_code == 200
        adapter.list_failure = AdapterError(
            status_code=upstream_status,
            request_id="req-marker",
        )
        response = client.get("/api/v1/instances?page=2")
        calls_after_failure = len(adapter.list_calls)
        adapter.list_failure = None
        unavailable = client.get("/api/v1/instances?page=2")

    assert response.status_code == 409
    assert response.json()["code"] == "page_cursor_unavailable"
    assert response.json()["openstack_request_id"] == "req-marker"
    assert unavailable.status_code == 409
    assert len(adapter.list_calls) == calls_after_failure


def test_nova_filter_400_on_page_one_is_browser_safe_422() -> None:
    adapter = RecordingAdapter()
    adapter.list_failure = AdapterError(status_code=400, request_id="req-filter")
    with client_for(adapter) as client:
        login_and_scope(client)
        response = client.get("/api/v1/instances?name=[")

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_instance_filter"
    assert response.json()["openstack_request_id"] == "req-filter"


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_code"),
    [
        (403, 403, "instances_forbidden"),
        (404, 404, "instances_not_found"),
        (429, 429, "instance_rate_limited"),
        (503, 503, "instance_unavailable"),
    ],
)
def test_list_error_mapping_preserves_request_id(
    upstream_status: int,
    expected_status: int,
    expected_code: str,
) -> None:
    adapter = RecordingAdapter()
    adapter.list_failure = AdapterError(
        status_code=upstream_status,
        request_id="req-list",
    )
    with client_for(adapter) as client:
        login_and_scope(client)
        response = client.get("/api/v1/instances")

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert response.json()["openstack_request_id"] == "req-list"


def test_bff_timeout_is_504_and_failed_reset_can_be_retried() -> None:
    adapter = RecordingAdapter()
    adapter.list_delay = 0.05
    with client_for(adapter, timeout=0.01) as client:
        login_and_scope(client)
        timed_out = client.get("/api/v1/instances")
        adapter.list_delay = 0
        retried = client.get("/api/v1/instances")

    assert timed_out.status_code == 504
    assert timed_out.json()["code"] == "instance_timeout"
    assert retried.status_code == 200


def test_detail_returns_volume_objects_and_partial_unknown_fields_as_null() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        inventory = client.get("/api/v1/instances?limit=100")
        items = inventory.json()["items"]
        regular = next(item for item in items if item["status"] != "UNKNOWN")
        partial = next(item for item in items if item["status"] == "UNKNOWN")

        regular_detail = client.get(f"/api/v1/instances/{regular['id']}")
        partial_detail = client.get(f"/api/v1/instances/{partial['id']}")

    assert regular_detail.status_code == 200
    assert regular_detail.json()["volumes"] == [{
        "id": regular_detail.json()["volumes"][0]["id"],
        "device": "/dev/vda",
    }]
    assert regular_detail.headers["X-OpenStack-Request-ID"] == (
        regular_detail.json()["openstack_request_id"]
    )
    assert partial_detail.status_code == 200
    assert partial_detail.json() == {
        "id": partial["id"],
        "status": "UNKNOWN",
        "name": None,
        "created_at": None,
        "flavor": None,
        "image": None,
        "addresses": None,
        "volumes": None,
        "openstack_request_id": partial_detail.headers["X-OpenStack-Request-ID"],
    }


@pytest.mark.parametrize(
    ("failure", "expected_status", "expected_code"),
    [
        (AdapterError(status_code=403, request_id="req-detail"), 403, "instance_forbidden"),
        (AdapterError(status_code=404, request_id="req-detail"), 404, "instance_not_found"),
        (AdapterError(status_code=409, request_id="req-detail"), 409, "instance_conflict"),
        (AdapterError(status_code=429, request_id="req-detail"), 429, "instance_rate_limited"),
        (AdapterError(status_code=503, request_id="req-detail"), 503, "instance_unavailable"),
        (AdapterTimeoutError(request_id="req-detail"), 504, "instance_timeout"),
    ],
)
def test_detail_error_mapping_preserves_request_id(
    failure: AdapterError,
    expected_status: int,
    expected_code: str,
) -> None:
    adapter = RecordingAdapter()
    adapter.detail_failure = failure
    instance_id = "00000000-0000-0000-0000-000000000001"
    with client_for(adapter) as client:
        login_and_scope(client)
        response = client.get(f"/api/v1/instances/{instance_id}")

    assert response.status_code == expected_status
    assert response.json()["code"] == expected_code
    assert response.json()["openstack_request_id"] == "req-detail"


def test_invalid_detail_uuid_is_rejected_before_adapter_call() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        response = client.get("/api/v1/instances/not-a-uuid")

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"
    assert adapter.detail_calls == []


def test_ten_thousand_instance_inventory_generates_only_one_bounded_page() -> None:
    adapter = LargeInventoryAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        response = client.get("/api/v1/instances")

    assert response.status_code == 200
    assert len(response.json()["items"]) == 25
    assert response.json()["page"]["has_next"] is True
    assert adapter.list_calls == [{
        "project_id": "project-alpha",
        "region": "RegionOne",
        "limit": 26,
        "marker": None,
    }]
    assert adapter.generated == 26


def test_operator_max_limit_preserves_next_page_from_upstream_signal() -> None:
    adapter = LargeInventoryAdapter(max_limit=100)
    with client_for(adapter) as client:
        login_and_scope(client)
        first = client.get("/api/v1/instances?limit=100")

        assert len(adapter.list_calls) == 1
        second = client.get("/api/v1/instances?limit=100&page=2")

    assert first.status_code == 200
    assert len(first.json()["items"]) == 100
    assert first.json()["page"]["has_next"] is True
    assert second.status_code == 200
    assert second.json()["items"][0]["id"] == str(UUID(int=101))
    assert adapter.list_calls == [
        {
            "project_id": "project-alpha",
            "region": "RegionOne",
            "limit": 101,
            "marker": None,
        },
        {
            "project_id": "project-alpha",
            "region": "RegionOne",
            "limit": 101,
            "marker": str(UUID(int=100)),
        },
    ]
    assert adapter.generated == 200


@pytest.mark.asyncio
async def test_failed_page_one_reset_is_transactional() -> None:
    store = MemoryCursorStore(ttl_seconds=300, max_chains=4, max_pages=1000)
    key = CursorKey("scope-one", "instances", (("limit", "25"),))
    initial = await store.acquire(key, 1)
    assert initial is not None
    assert await store.complete(initial, "old-marker") == (1, 2)

    failed_refresh = await store.acquire(key, 1)
    assert failed_refresh is not None
    await store.abandon(failed_refresh)
    second = await store.acquire(key, 2)

    assert second is not None
    assert second.marker == "old-marker"


@pytest.mark.asyncio
async def test_older_page_one_response_cannot_overwrite_newer_generation() -> None:
    store = MemoryCursorStore(ttl_seconds=300, max_chains=4, max_pages=1000)
    key = CursorKey("scope-one", "instances", (("limit", "25"),))
    older = await store.acquire(key, 1)
    newer = await store.acquire(key, 1)
    assert older is not None and newer is not None

    assert await store.complete(older, "old-marker") is None
    assert await store.complete(newer, "new-marker") == (1, 2)
    second = await store.acquire(key, 2)

    assert second is not None
    assert second.marker == "new-marker"


@pytest.mark.asyncio
async def test_deep_cursor_chain_exposes_only_bounded_navigation_window() -> None:
    store = MemoryCursorStore(ttl_seconds=300, max_chains=4, max_pages=1000)
    key = CursorKey("scope-one", "instances", (("limit", "10"),))
    known_pages: tuple[int, ...] | None = None
    for page in range(1, 501):
        lease = await store.acquire(key, page)
        assert lease is not None
        known_pages = await store.complete(lease, f"marker-{page + 1}")
        assert known_pages is not None

    assert len(known_pages) == 501
    navigation = _navigable_pages(500, max(known_pages))
    assert len(navigation) <= 7
    assert navigation == [1, 497, 498, 499, 500, 501]


@pytest.mark.asyncio
async def test_cursor_store_enforces_ttl_chain_and_page_bounds() -> None:
    now = [0.0]
    store = MemoryCursorStore(
        ttl_seconds=10,
        max_chains=1,
        max_pages=2,
        clock=lambda: now[0],
    )
    first_key = CursorKey("scope-one", "instances", (("limit", "10"),))
    second_key = CursorKey("scope-one", "instances", (("limit", "25"),))
    first = await store.acquire(first_key, 1)
    assert first is not None
    assert await store.complete(first, "first-page-two") == (1, 2)
    page_two = await store.acquire(first_key, 2)
    assert page_two is not None
    assert await store.complete(page_two, "must-not-create-page-three") == (1, 2)
    assert await store.acquire(first_key, 3) is None

    second = await store.acquire(second_key, 1)
    assert second is not None
    assert await store.complete(second, "second-page-two") == (1, 2)
    assert await store.acquire(first_key, 2) is None

    now[0] = 11.0
    assert await store.acquire(second_key, 2) is None


@pytest.mark.parametrize(
    ("sort", "nova_sort_key"),
    [
        (InstanceSort.CREATED_AT, "created_at"),
        (InstanceSort.NAME, "display_name"),
        (InstanceSort.STATUS, "vm_state"),
    ],
)
def test_sdk_list_is_single_page_project_scoped_and_uses_nova_sort_keys(
    monkeypatch: pytest.MonkeyPatch,
    sort: InstanceSort,
    nova_sort_key: str,
) -> None:
    import openstack.connection
    from openstack.compute.v2.server import Server

    connection_calls: list[dict[str, Any]] = []
    get_calls: list[dict[str, Any]] = []

    class InventoryResponse:
        status_code = 200
        links: dict[str, Any] = {}

        def json(self) -> dict[str, Any]:
            return {
                "servers": [{
                    "id": "00000000-0000-0000-0000-000000000001",
                    "status": "ACTIVE",
                    "name": "api-01",
                    "created": "2026-01-01T00:00:00Z",
                    "flavor": {"original_name": "m1.small"},
                    "image": {"id": "image-one"},
                    "addresses": {"private": [{"addr": "10.0.0.10"}]},
                }],
                "servers_links": [],
            }

    class InventoryCompute:
        def get(self, url: str, **kwargs: Any) -> InventoryResponse:
            get_calls.append({"url": url, **kwargs})
            return InventoryResponse()

    class InventoryConnection:
        def __init__(self, **kwargs: Any) -> None:
            connection_calls.append(kwargs)
            self.compute = InventoryCompute()

    monkeypatch.setattr(openstack.connection, "Connection", InventoryConnection)
    monkeypatch.setattr(
        Server,
        "_get_microversion",
        classmethod(lambda _cls, _session: "2.95"),
    )
    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3",
        "internal",
        "RegionOne",
        15,
        2.5,
        3.0,
    )

    result = adapter._list_instances(
        {
            "scoped_token": "scoped",
            "project_id": "project-alpha",
            "region": "RegionOne",
        },
        "project-alpha",
        "RegionOne",
        limit=26,
        marker="00000000-0000-0000-0000-000000000099",
        name="api",
        status="ACTIVE",
        image_id="image-one",
        sort=sort,
        direction=SortDirection.ASC,
    )

    assert len(result.items) == 1
    assert result.has_next is False
    assert re.fullmatch(
        r"req-[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
        result.openstack_request_id or "",
    )
    assert connection_calls[0]["project_id"] == "project-alpha"
    assert connection_calls[0]["region_name"] == "RegionOne"
    assert connection_calls[0]["api_timeout"] == 3.0
    assert connection_calls[0]["app_version"] == "0.3.0"
    assert connection_calls[0]["global_request_id"] == result.openstack_request_id
    assert "all_projects" not in connection_calls[0]
    assert len(get_calls) == 1
    call = get_calls[0]
    assert call["url"] == "/servers/detail"
    assert call["headers"] == {"Accept": "application/json"}
    assert call["microversion"] == "2.95"
    assert call["params"]["limit"] == 26
    assert call["params"]["marker"] == "00000000-0000-0000-0000-000000000099"
    assert call["params"]["name"] == "api"
    assert call["params"]["status"] == "ACTIVE"
    assert call["params"]["image"] == "image-one"
    assert call["params"]["sort_key"] == nova_sort_key
    assert call["params"]["sort_dir"] == "asc"
    assert "all_projects" not in call["params"]
    assert "all_tenants" not in call["params"]


def test_sdk_list_preserves_nova_next_link_when_max_limit_clamps_lookahead(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openstack.connection
    from openstack.compute.v2.server import Server

    get_calls: list[dict[str, Any]] = []
    servers = [
        {"id": str(UUID(int=index + 1)), "status": "ACTIVE"}
        for index in range(100)
    ]

    class InventoryResponse:
        status_code = 200
        links: dict[str, Any] = {}

        def json(self) -> dict[str, Any]:
            return {
                "servers": servers,
                "servers_links": [{
                    "rel": "next",
                    "href": (
                        "https://nova.example/v2.1/project-alpha/servers/detail"
                        f"?limit=101&marker={UUID(int=100)}"
                    ),
                }],
            }

    class InventoryCompute:
        def get(self, url: str, **kwargs: Any) -> InventoryResponse:
            get_calls.append({"url": url, **kwargs})
            return InventoryResponse()

    class InventoryConnection:
        def __init__(self, **kwargs: Any) -> None:
            del kwargs
            self.compute = InventoryCompute()

    monkeypatch.setattr(openstack.connection, "Connection", InventoryConnection)
    monkeypatch.setattr(
        Server,
        "_get_microversion",
        classmethod(lambda _cls, _session: "2.95"),
    )
    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3",
        "internal",
        "RegionOne",
        15,
        2.5,
        3.0,
    )

    result = adapter._list_instances(
        {
            "scoped_token": "scoped",
            "project_id": "project-alpha",
            "region": "RegionOne",
        },
        "project-alpha",
        "RegionOne",
        limit=101,
        marker=None,
        name=None,
        status=None,
        image_id=None,
        sort=InstanceSort.CREATED_AT,
        direction=SortDirection.DESC,
    )

    assert len(result.items) == 100
    assert result.has_next is True
    assert len(get_calls) == 1
    assert get_calls[0]["url"] == "/servers/detail"
    assert get_calls[0]["params"]["limit"] == 101
    assert "all_projects" not in get_calls[0]["params"]
    assert "all_tenants" not in get_calls[0]["params"]


def test_partial_down_cell_normalization_does_not_fabricate_fields() -> None:
    partial = {
        "id": "00000000-0000-0000-0000-000000000001",
        "status": "UNKNOWN",
    }

    instance = _normalize_instance(partial)
    detail = _normalize_instance_detail(partial, "req-partial")
    explicit_empty = _normalize_instance_detail(
        {**partial, "addresses": {}, "os-extended-volumes:volumes_attached": []},
        "req-empty",
    )

    assert instance.model_dump(mode="json") == {
        "id": partial["id"],
        "status": "UNKNOWN",
        "name": None,
        "created_at": None,
        "flavor": None,
        "image": None,
        "addresses": None,
    }
    assert detail.volumes is None
    assert explicit_empty.addresses == []
    assert explicit_empty.volumes == []


def test_exception_request_id_prefers_nova_response_header() -> None:
    error = Exception("nova unavailable")
    error.request_id = "req-client-correlation"
    error.response = SimpleNamespace(
        status_code=503,
        headers={"x-openstack-request-id": "req-nova"},
    )

    translated = _instance_failure(error)

    assert translated.status_code == 503
    assert translated.request_id == "req-nova"


def test_fake_inventory_is_paginated_and_has_one_partial_server_per_project() -> None:
    adapter = FakeOpenStackAdapter()

    alpha = adapter._instances("project-alpha")
    beta = adapter._instances("project-beta")

    assert len(alpha) == 37
    assert len(beta) == 63
    assert sum(item.status == "UNKNOWN" for item in alpha) == 1
    assert sum(item.status == "UNKNOWN" for item in beta) == 1
