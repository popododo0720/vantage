from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vantage_bff.adapters.base import AdapterError, ProvisioningListResult
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.adapters.openstack_sdk import OpenStackSdkAdapter
from vantage_bff.app import create_app
from vantage_bff.config import Settings
from vantage_bff.models import ImageVisibility


class RecordingAdapter(FakeOpenStackAdapter):
    def __init__(self) -> None:
        self.image_calls: list[dict[str, Any]] = []
        self.image_failure: AdapterError | None = None

    async def list_images(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        limit: int,
        marker: str | None,
        name: str | None,
        visibility: ImageVisibility | None,
    ) -> ProvisioningListResult:
        self.image_calls.append(
            {
                "project_id": project_id,
                "region": region,
                "limit": limit,
                "marker": marker,
                "name": name,
                "visibility": visibility,
            }
        )
        if self.image_failure is not None:
            raise self.image_failure
        return await super().list_images(
            auth_context,
            project_id,
            region,
            limit=limit,
            marker=marker,
            name=name,
            visibility=visibility,
        )


@contextmanager
def client_for(adapter: FakeOpenStackAdapter) -> Iterator[TestClient]:
    with TestClient(
        create_app(Settings(cookie_secure=True), adapter=adapter),
        base_url="https://testserver",
    ) as client:
        yield client


def login_and_scope(client: TestClient, project_id: str = "project-alpha") -> str:
    login = client.post(
        "/api/v1/session/login",
        json={"username": "alice", "password": "vantage", "domain": "default"},
    )
    assert login.status_code == 201
    scoped = client.put(
        "/api/v1/scope",
        json={"project_id": project_id, "region": "RegionOne"},
        headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
    )
    assert scoped.status_code == 200
    return scoped.headers["X-CSRF-Token"]


@pytest.mark.parametrize(
    "path",
    ["/images", "/flavors", "/keypairs", "/networks", "/security-groups"],
)
def test_inventory_requires_authentication_and_active_scope(path: str) -> None:
    with client_for(FakeOpenStackAdapter()) as client:
        unauthenticated = client.get(f"/api/v1{path}")
        login = client.post(
            "/api/v1/session/login",
            json={"username": "alice", "password": "vantage", "domain": "default"},
        )
        unscoped = client.get(f"/api/v1{path}")

    assert login.status_code == 201
    assert unauthenticated.status_code == 401
    assert unscoped.status_code == 409
    assert unscoped.json()["code"] == "active_scope_required"


@pytest.mark.parametrize("limit", [10, 25, 50, 100])
def test_discrete_page_sizes_use_exactly_one_limit_plus_one_call(limit: int) -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        response = client.get(f"/api/v1/images?limit={limit}")

    assert response.status_code == 200
    assert response.json()["page"]["size"] == limit
    assert len(adapter.image_calls) == 1
    assert adapter.image_calls[0]["limit"] == limit + 1


def test_progressive_cursor_scope_filters_request_id_and_no_totals() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        csrf = login_and_scope(client)
        first = client.get(
            "/api/v1/images",
            params={"limit": 10, "name": "alpha-image", "visibility": "public"},
        )
        unavailable = client.get(
            "/api/v1/images",
            params={
                "limit": 10,
                "page": 3,
                "name": "alpha-image",
                "visibility": "public",
            },
        )
        second = client.get(
            "/api/v1/images",
            params={
                "limit": 10,
                "page": 2,
                "name": "alpha-image",
                "visibility": "public",
            },
        )
        switched = client.put(
            "/api/v1/scope",
            json={"project_id": "project-beta", "region": "RegionOne"},
            headers={"X-CSRF-Token": csrf},
        )
        stale = client.get(
            "/api/v1/images",
            params={
                "limit": 10,
                "page": 2,
                "name": "alpha-image",
                "visibility": "public",
            },
        )

    assert first.status_code == 200
    assert unavailable.status_code == 409
    assert second.status_code == 200
    assert switched.status_code == 200
    assert stale.status_code == 409
    assert len(adapter.image_calls) == 2
    assert adapter.image_calls[0] == {
        "project_id": "project-alpha",
        "region": "RegionOne",
        "limit": 11,
        "marker": None,
        "name": "alpha-image",
        "visibility": ImageVisibility.PUBLIC,
    }
    assert adapter.image_calls[1]["marker"] == first.json()["items"][-1]["id"]
    page = first.json()["page"]
    assert page["total_items"] is None
    assert page["total_pages"] is None
    assert page["openstack_request_id"] == first.headers["X-OpenStack-Request-ID"]


def test_fake_filters_and_second_pages_cover_every_inventory() -> None:
    cases = [
        ("/images", {"visibility": "private"}, "visibility", "private"),
        ("/flavors", {}, None, None),
        ("/keypairs", {}, None, None),
        ("/networks", {"status": "down"}, "status", "DOWN"),
        ("/security-groups", {"name": "alpha-sg"}, "name", "alpha-sg"),
    ]
    with client_for(FakeOpenStackAdapter()) as client:
        login_and_scope(client)
        for path, filters, field, expected in cases:
            first = client.get(f"/api/v1{path}", params={"limit": 10, **filters})
            second = client.get(f"/api/v1{path}", params={"limit": 10, "page": 2, **filters})
            assert first.status_code == 200
            assert second.status_code == 200
            assert second.json()["items"]
            if field is not None and expected is not None:
                assert all(expected in item[field] for item in second.json()["items"])


def test_invalid_size_and_authoritative_policy_error_do_not_enumerate() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        invalid = client.get("/api/v1/images?limit=20")
        adapter.image_failure = AdapterError(status_code=403, request_id="req-policy")
        forbidden = client.get("/api/v1/images")

    assert invalid.status_code == 422
    assert invalid.json()["code"] == "invalid_page_size"
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "images_forbidden"
    assert forbidden.json()["openstack_request_id"] == "req-policy"
    assert len(adapter.image_calls) == 1


def test_disappeared_marker_invalidates_the_saved_page_sequence() -> None:
    adapter = RecordingAdapter()
    with client_for(adapter) as client:
        login_and_scope(client)
        first = client.get("/api/v1/images?limit=10")
        adapter.image_failure = AdapterError(status_code=400, request_id="req-stale")
        stale = client.get("/api/v1/images?limit=10&page=2")
        calls_after_stale = len(adapter.image_calls)
        adapter.image_failure = None
        unavailable = client.get("/api/v1/images?limit=10&page=2")

    assert first.status_code == 200
    assert stale.status_code == 409
    assert stale.json()["code"] == "page_cursor_unavailable"
    assert stale.json()["openstack_request_id"] == "req-stale"
    assert unavailable.status_code == 409
    assert len(adapter.image_calls) == calls_after_stale


class FakeResponse:
    def __init__(self, key: str, items: list[dict[str, Any]]) -> None:
        self.key = key
        self.items = items
        self.headers = {"x-openstack-request-id": "req-upstream"}
        self.links: dict[str, Any] = {}

    def json(self) -> dict[str, Any]:
        return {self.key: self.items}


class FakeSession:
    def __init__(self, key: str, items: list[dict[str, Any]]) -> None:
        self.default_microversion = None
        self.response = FakeResponse(key, items)
        self.calls: list[dict[str, Any]] = []

    def get(self, path: str, **kwargs: Any) -> FakeResponse:
        self.calls.append({"path": path, **kwargs})
        return self.response

    def get_endpoint_data(self) -> SimpleNamespace:
        return SimpleNamespace(min_microversion="2.1", max_microversion="2.103")


@pytest.mark.parametrize(
    ("method", "service", "key", "path", "kwargs", "item"),
    [
        (
            "_list_images",
            "image",
            "images",
            "/images",
            {"name": "ubuntu", "visibility": ImageVisibility.PUBLIC},
            {"id": "00000000-0000-0000-0000-000000000001"},
        ),
        (
            "_list_flavors",
            "compute",
            "flavors",
            "/flavors/detail",
            {},
            {"id": "small"},
        ),
        (
            "_list_keypairs",
            "compute",
            "keypairs",
            "/os-keypairs",
            {},
            {"keypair": {"name": "alice"}},
        ),
        (
            "_list_networks",
            "network",
            "networks",
            "/networks",
            {"name": "private", "status": "ACTIVE"},
            {"id": "00000000-0000-0000-0000-000000000002"},
        ),
        (
            "_list_security_groups",
            "network",
            "security_groups",
            "/security-groups",
            {"name": "default"},
            {"id": "00000000-0000-0000-0000-000000000003"},
        ),
    ],
)
def test_sdk_query_translation_is_one_direct_non_paginating_request(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    service: str,
    key: str,
    path: str,
    kwargs: dict[str, Any],
    item: dict[str, Any],
) -> None:
    sessions = {
        "image": FakeSession(key, [item]),
        "compute": FakeSession(key, [item]),
        "network": FakeSession(key, [item]),
    }
    connection = SimpleNamespace(**sessions)
    connection_calls: list[dict[str, Any]] = []
    adapter = OpenStackSdkAdapter(
        "https://keystone",
        "public",
        "RegionOne",
        5,
        provisioning_timeout_seconds=2.5,
    )

    def project_connection(*_args: Any, **kwargs: Any) -> Any:
        connection_calls.append(kwargs)
        return connection

    monkeypatch.setattr(adapter, "_project_connection", project_connection)
    monkeypatch.setattr("openstack.exceptions.raise_from_response", lambda _response: None)

    result = getattr(adapter, method)(
        {"scoped_token": "token", "project_id": "project", "region": "RegionOne"},
        "project",
        "RegionOne",
        limit=26,
        marker="marker-one",
        **kwargs,
    )

    assert result.openstack_request_id == "req-upstream"
    assert connection_calls == [{"request_timeout_seconds": 2.5}]
    assert len(sessions[service].calls) == 1
    call = sessions[service].calls[0]
    assert call["path"] == path
    assert call["params"]["limit"] == 26
    assert call["params"]["marker"] == "marker-one"
    for name, value in kwargs.items():
        expected = value.value if isinstance(value, ImageVisibility) else value
        assert call["params"][name] == expected
    if method == "_list_keypairs":
        assert call["microversion"] == "2.35"
