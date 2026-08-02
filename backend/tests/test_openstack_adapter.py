from datetime import UTC, datetime
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
        "app_version": "0.1.0",
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
        "app_version": "0.1.0",
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
