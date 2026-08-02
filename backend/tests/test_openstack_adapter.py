import asyncio
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest
from vantage_bff.adapters.base import AdapterError, AuthenticationError, ScopeError
from vantage_bff.adapters.openstack_sdk import (
    OpenStackSdkAdapter,
    _authentication_failure,
    _scope_failure,
)


class SdkError(Exception):
    def __init__(self, status_code: int | None, request_id: str = "req-sdk") -> None:
        self.status_code = status_code
        self.request_id = request_id


class FakeConnection:
    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.calls.append(kwargs)
        access = SimpleNamespace(
            user_domain_id="default",
            expires=datetime(2026, 8, 2, 12, tzinfo=UTC),
            service_catalog=SimpleNamespace(catalog=[{
                "endpoints": [{"region_id": "RegionTwo"}, {"region": "RegionOne"}],
            }]),
        )
        self.session = SimpleNamespace(
            auth=SimpleNamespace(get_access=lambda _session: access),
        )
        project = SimpleNamespace(
            id="project-alpha",
            name="Alpha",
            domain_id="default",
            is_enabled=True,
        )
        self.identity = SimpleNamespace(
            user_projects=lambda _user_id: [project],
            get_project=lambda _project_id: project,
        )
        self.current_user_id = "user-alice"

    def authorize(self) -> str:
        return "sdk-token"


@pytest.mark.parametrize(
    ("status", "expected_type", "expected_status"),
    [
        (401, AuthenticationError, 401),
        (403, AdapterError, 403),
        (429, AdapterError, 429),
        (500, AdapterError, 503),
        (None, AdapterError, 503),
    ],
)
def test_authentication_failure_translation(
    status: int | None, expected_type: type[AdapterError], expected_status: int
) -> None:
    translated = _authentication_failure(SdkError(status))
    assert isinstance(translated, expected_type)
    assert translated.status_code == expected_status
    assert translated.request_id == "req-sdk"


@pytest.mark.parametrize(
    ("status", "expected_status"),
    [(401, 401), (403, 403), (404, 404), (409, 409), (429, 429), (500, 503), (None, 503)],
)
def test_scope_failure_translation(status: int | None, expected_status: int) -> None:
    translated = _scope_failure(SdkError(status))
    assert isinstance(translated, ScopeError)
    assert translated.status_code == expected_status
    assert translated.request_id == "req-sdk"


def test_adapter_passes_authentication_connection_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openstack.connection

    FakeConnection.calls.clear()
    monkeypatch.setattr(openstack.connection, "Connection", FakeConnection)
    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3", "internal", "RegionOne", 15
    )

    result = adapter._authenticate("alice", "secret", "default")

    assert result.user.id == "user-alice"
    assert result.regions == ("RegionOne", "RegionTwo")
    assert FakeConnection.calls == [{
        "auth_url": "https://keystone.example/v3",
        "username": "alice",
        "password": "secret",
        "user_domain_name": "default",
        "interface": "internal",
        "api_timeout": 15,
        "app_name": "vantage",
        "app_version": "0.3.0",
    }]


def test_adapter_passes_project_scope_connection_boundaries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import openstack.connection

    FakeConnection.calls.clear()
    monkeypatch.setattr(openstack.connection, "Connection", FakeConnection)
    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3", "public", "RegionOne", 12
    )

    result = adapter._scope(
        {"unscoped_token": "unscoped"}, "project-alpha", "RegionTwo"
    )

    assert result.project.name == "Alpha"
    assert result.region == "RegionTwo"
    assert result.auth_context["project_id"] == "project-alpha"
    assert FakeConnection.calls == [{
        "auth_url": "https://keystone.example/v3",
        "auth_type": "v3token",
        "token": "unscoped",
        "project_id": "project-alpha",
        "region_name": "RegionTwo",
        "interface": "public",
        "api_timeout": 12,
        "app_name": "vantage",
        "app_version": "0.3.0",
    }]


def test_failure_translation_uses_request_id_response_header() -> None:
    error = Exception("not found")
    error.response = SimpleNamespace(
        status_code=404,
        headers={"x-openstack-request-id": "req-from-header"},
    )

    translated = _scope_failure(error)

    assert translated.status_code == 404
    assert translated.request_id == "req-from-header"


@pytest.mark.parametrize("termination", ["cancel", "timeout"])
@pytest.mark.asyncio
async def test_cancelled_sdk_call_holds_capacity_until_thread_finishes(
    monkeypatch: pytest.MonkeyPatch,
    termination: str,
) -> None:
    first_started = Event()
    second_started = Event()
    release_first = Event()

    def fake_authenticate(username: str, password: str, domain: str) -> str:
        del password, domain
        if username == "first":
            first_started.set()
            release_first.wait(timeout=2)
        else:
            second_started.set()
        return username

    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3",
        "internal",
        "RegionOne",
        15,
        thread_capacity=1,
    )
    monkeypatch.setattr(adapter, "_authenticate", fake_authenticate)

    first = asyncio.create_task(adapter.authenticate("first", "secret", "default"))
    for _ in range(100):
        if first_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert first_started.is_set()

    if termination == "cancel":
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
    else:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(first, timeout=0.01)

    second = asyncio.create_task(adapter.authenticate("second", "secret", "default"))
    await asyncio.sleep(0.05)
    assert second_started.is_set() is False

    release_first.set()
    assert await asyncio.wait_for(second, timeout=1) == "second"
    assert second_started.is_set() is True


@pytest.mark.asyncio
async def test_calls_cancelled_while_sdk_capacity_is_full_are_not_submitted_later(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_started = Event()
    release_first = Event()
    started: list[str] = []

    def fake_authenticate(username: str, password: str, domain: str) -> str:
        del password, domain
        started.append(username)
        if username == "first":
            first_started.set()
            release_first.wait(timeout=2)
        return username

    adapter = OpenStackSdkAdapter(
        "https://keystone.example/v3",
        "internal",
        "RegionOne",
        15,
        thread_capacity=1,
    )
    monkeypatch.setattr(adapter, "_authenticate", fake_authenticate)

    first = asyncio.create_task(adapter.authenticate("first", "secret", "default"))
    for _ in range(100):
        if first_started.is_set():
            break
        await asyncio.sleep(0.01)
    assert first_started.is_set()

    queued = [
        asyncio.create_task(
            asyncio.wait_for(
                adapter.authenticate(f"queued-{index}", "secret", "default"),
                timeout=0.02,
            )
        )
        for index in range(3)
    ]
    results = await asyncio.gather(*queued, return_exceptions=True)
    assert all(isinstance(result, TimeoutError) for result in results)

    release_first.set()
    assert await asyncio.wait_for(first, timeout=1) == "first"
    await asyncio.sleep(0.05)
    assert started == ["first"]
