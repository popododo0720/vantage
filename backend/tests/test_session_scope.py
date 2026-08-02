from __future__ import annotations

import asyncio
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vantage_bff.adapters.base import (
    AdapterError,
    AuthenticationError,
    AuthResult,
    ScopeError,
    ScopeResult,
)
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.app import _navigable_pages, create_app
from vantage_bff.config import Settings
from vantage_bff.models import Project, User
from vantage_bff.rate_limit import LoginRateLimiter
from vantage_bff.sessions import MemorySessionStore, new_session, rotated_session


@pytest.fixture
def client() -> Iterator[TestClient]:
    app = create_app(Settings(cookie_secure=True, session_ttl_seconds=3600))
    with TestClient(app, base_url="https://testserver") as test_client:
        yield test_client


def test_runtime_boundaries_must_be_positive() -> None:
    with pytest.raises(ValueError, match="request_timeout_seconds"):
        Settings(request_timeout_seconds=0)


def login(client: TestClient, username: str = "alice") -> tuple[str, str]:
    response = client.post(
        "/api/v1/session/login",
        json={"username": username, "password": "vantage", "domain": "default"},
    )
    assert response.status_code == 201
    session_id = response.cookies.get("vantage_session")
    if session_id is None:
        cookie = SimpleCookie()
        cookie.load(response.headers["Set-Cookie"])
        session_id = cookie["vantage_session"].value
    return session_id, response.headers["X-CSRF-Token"]


class FailingLoginAdapter(FakeOpenStackAdapter):
    def __init__(self, error: AdapterError) -> None:
        self.error = error

    async def authenticate(self, username: str, password: str, domain: str) -> AuthResult:
        raise self.error


class FailingScopeAdapter(FakeOpenStackAdapter):
    def __init__(self, error: ScopeError) -> None:
        self.error = error

    async def scope(
        self, auth_context: dict[str, Any], project_id: str, region: str
    ) -> ScopeResult:
        raise self.error


def test_login_cookie_is_hardened_and_no_token_leaks(client: TestClient) -> None:
    response = client.post(
        "/api/v1/session/login",
        json={"username": "alice", "password": "vantage", "domain": "default"},
    )
    assert response.status_code == 201
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    body = response.text.lower()
    assert "token" not in body
    assert "password" not in body
    assert "projects" not in response.json()
    assert response.headers["Content-Security-Policy"].startswith("default-src 'self'")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PUT", "/api/v1/scope", {"project_id": "project-alpha", "region": "RegionOne"}),
        ("PATCH", "/api/v1/session", {"locale": "ko"}),
        ("DELETE", "/api/v1/session", None),
    ],
)
@pytest.mark.parametrize("csrf", [None, "", "wrong"])
def test_mutations_reject_missing_or_invalid_csrf(
    client: TestClient,
    method: str,
    path: str,
    payload: dict[str, str] | None,
    csrf: str | None,
) -> None:
    session_id, _ = login(client)
    headers = {"X-CSRF-Token": csrf} if csrf else {}
    response = client.request(
        method,
        path,
        json=payload,
        headers=headers,
        cookies={"vantage_session": session_id},
    )
    assert response.status_code == 403
    assert response.json()["code"] == "csrf_invalid"


def test_scope_rotation_invalidates_previous_session(client: TestClient) -> None:
    old_session, csrf = login(client)
    response = client.put(
        "/api/v1/scope",
        json={"project_id": "project-alpha", "region": "RegionOne"},
        headers={"X-CSRF-Token": csrf},
        cookies={"vantage_session": old_session},
    )
    assert response.status_code == 200
    new_session = response.cookies["vantage_session"]
    assert new_session != old_session
    stale = client.get("/api/v1/session", cookies={"vantage_session": old_session})
    assert stale.status_code == 401
    current = client.get("/api/v1/session", cookies={"vantage_session": new_session})
    assert current.json()["active_scope"]["project"]["id"] == "project-alpha"


def test_locale_update_rotates_session_and_csrf(client: TestClient) -> None:
    old_session, old_csrf = login(client)
    response = client.patch(
        "/api/v1/session",
        json={"locale": "ko"},
        headers={"X-CSRF-Token": old_csrf},
        cookies={"vantage_session": old_session},
    )
    assert response.status_code == 200
    assert response.json()["locale"] == "ko"
    assert response.cookies["vantage_session"] != old_session
    assert response.headers["X-CSRF-Token"] != old_csrf
    assert client.get(
        "/api/v1/session", cookies={"vantage_session": old_session}
    ).status_code == 401


def test_users_and_project_scopes_are_isolated(client: TestClient) -> None:
    alice_session, alice_csrf = login(client, "alice")
    client.cookies.clear()
    limited_session, limited_csrf = login(client, "limited")
    alice_projects = client.get(
        "/api/v1/projects", cookies={"vantage_session": alice_session}
    ).json()["items"]
    limited_projects = client.get(
        "/api/v1/projects", cookies={"vantage_session": limited_session}
    ).json()["items"]
    assert [item["id"] for item in alice_projects] == ["project-alpha", "project-beta"]
    assert [item["id"] for item in limited_projects] == ["project-alpha"]

    forbidden = client.put(
        "/api/v1/scope",
        json={"project_id": "project-beta", "region": "RegionOne"},
        headers={"X-CSRF-Token": limited_csrf},
        cookies={"vantage_session": limited_session},
    )
    assert forbidden.status_code == 403
    assert forbidden.json()["code"] == "scope_forbidden"

    cross_user_csrf = client.put(
        "/api/v1/scope",
        json={"project_id": "project-alpha", "region": "RegionOne"},
        headers={"X-CSRF-Token": alice_csrf},
        cookies={"vantage_session": limited_session},
    )
    assert cross_user_csrf.status_code == 403
    assert cross_user_csrf.json()["code"] == "csrf_invalid"


def test_scope_switch_does_not_retain_previous_project(client: TestClient) -> None:
    first_session, first_csrf = login(client)
    alpha = client.put(
        "/api/v1/scope",
        json={"project_id": "project-alpha", "region": "RegionOne"},
        headers={"X-CSRF-Token": first_csrf},
        cookies={"vantage_session": first_session},
    )
    alpha_session = alpha.cookies["vantage_session"]
    beta = client.put(
        "/api/v1/scope",
        json={"project_id": "project-beta", "region": "RegionTwo"},
        headers={"X-CSRF-Token": alpha.headers["X-CSRF-Token"]},
        cookies={"vantage_session": alpha_session},
    )
    assert beta.status_code == 200
    assert beta.json()["active_scope"] == {
        "project": {
            "id": "project-beta",
            "name": "Beta",
            "domain_id": "default",
            "enabled": True,
        },
        "region": "RegionTwo",
    }
    assert client.get(
        "/api/v1/session", cookies={"vantage_session": alpha_session}
    ).status_code == 401


def test_logout_invalidates_session(client: TestClient) -> None:
    session_id, csrf = login(client)
    response = client.delete(
        "/api/v1/session",
        headers={"X-CSRF-Token": csrf},
        cookies={"vantage_session": session_id},
    )
    assert response.status_code == 204
    assert (
        client.get("/api/v1/session", cookies={"vantage_session": session_id}).status_code
        == 401
    )


def test_logout_is_idempotent_without_a_session(client: TestClient) -> None:
    response = client.delete("/api/v1/session")
    assert response.status_code == 204


def test_invalid_request_uses_problem_contract(client: TestClient) -> None:
    session_id, _ = login(client)
    response = client.get(
        "/api/v1/projects?page=0",
        cookies={"vantage_session": session_id},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "invalid_request"
    assert response.json()["trace_id"] == response.headers["X-Trace-ID"]


def test_project_pagination_and_filter_are_bounded(client: TestClient) -> None:
    session_id, _ = login(client)
    response = client.get(
        "/api/v1/projects?limit=10&page=1&name=beta",
        cookies={"vantage_session": session_id},
    )
    assert response.status_code == 200
    assert [item["name"] for item in response.json()["items"]] == ["Beta"]
    assert response.json()["page"]["size"] == 10


def test_navigable_project_pages_are_a_bounded_window() -> None:
    assert _navigable_pages(1, 1000) == [1, 2, 3, 4, 5, 1000]
    assert _navigable_pages(500, 1000) == [1, 499, 500, 501, 1000]
    assert _navigable_pages(1000, 1000) == [1, 996, 997, 998, 999, 1000]


def test_failed_logins_are_rate_limited_without_identity_detail() -> None:
    settings = Settings(
        cookie_secure=True,
        login_attempt_limit=2,
        login_attempt_window_seconds=60,
    )
    with TestClient(create_app(settings), base_url="https://testserver") as test_client:
        payload = {"username": "alice", "password": "wrong", "domain": "default"}
        first = test_client.post("/api/v1/session/login", json=payload)
        second = test_client.post("/api/v1/session/login", json=payload)
        blocked = test_client.post("/api/v1/session/login", json=payload)
        assert first.status_code == second.status_code == 401
        assert blocked.status_code == 429
        assert blocked.headers["Retry-After"] == "60"
        assert "60 seconds" in blocked.json()["detail"]
        assert "alice" not in blocked.text


def test_failed_logins_are_rate_limited_without_user_enumeration() -> None:
    settings = Settings(login_attempt_limit=2, login_attempt_window_seconds=60)
    app = create_app(settings)
    with TestClient(app, base_url="https://testserver") as test_client:
        bodies = []
        for _ in range(2):
            response = test_client.post(
                "/api/v1/session/login",
                json={"username": "alice", "password": "wrong", "domain": "default"},
            )
            assert response.status_code == 401
            bodies.append(response.json())
        blocked = test_client.post(
            "/api/v1/session/login",
            json={"username": "alice", "password": "vantage", "domain": "default"},
        )
    assert bodies[0]["detail"] == bodies[1]["detail"]
    assert blocked.status_code == 429
    assert blocked.json()["code"] == "authentication_rate_limited"


def test_identity_outage_does_not_consume_credential_failure_budget() -> None:
    adapter = FailingLoginAdapter(AdapterError(status_code=503, request_id="req-identity"))
    settings = Settings(login_attempt_limit=1, login_attempt_window_seconds=60)
    with TestClient(create_app(settings, adapter=adapter), base_url="https://testserver") as client:
        responses = [
            client.post(
                "/api/v1/session/login",
                json={"username": "alice", "password": "vantage", "domain": "default"},
            )
            for _ in range(2)
        ]
    assert [response.status_code for response in responses] == [503, 503]
    assert all(response.json()["openstack_request_id"] == "req-identity" for response in responses)


def test_authentication_failure_preserves_upstream_request_id() -> None:
    adapter = FailingLoginAdapter(AuthenticationError(request_id="req-auth"))
    with TestClient(
        create_app(Settings(cookie_secure=True), adapter=adapter),
        base_url="https://testserver",
    ) as client:
        response = client.post(
            "/api/v1/session/login",
            json={"username": "alice", "password": "wrong", "domain": "default"},
        )
    assert response.status_code == 401
    assert response.json()["openstack_request_id"] == "req-auth"


def test_successful_reauthentication_invalidates_previous_session(client: TestClient) -> None:
    previous_session, _ = login(client, "alice")
    replacement = client.post(
        "/api/v1/session/login",
        json={"username": "limited", "password": "vantage", "domain": "default"},
    )
    assert replacement.status_code == 201
    assert replacement.cookies["vantage_session"] != previous_session
    stale = client.get(
        "/api/v1/session",
        cookies={"vantage_session": previous_session},
    )
    assert stale.status_code == 401


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "code"),
    [
        (401, 401, "unauthenticated"),
        (403, 403, "scope_forbidden"),
        (404, 404, "scope_unavailable"),
        (409, 409, "scope_failed"),
        (429, 429, "identity_rate_limited"),
        (503, 503, "identity_unavailable"),
    ],
)
def test_scope_preserves_authoritative_upstream_status(
    upstream_status: int, expected_status: int, code: str
) -> None:
    adapter = FailingScopeAdapter(
        ScopeError(status_code=upstream_status, request_id="req-scope")
    )
    with TestClient(
        create_app(Settings(cookie_secure=True), adapter=adapter),
        base_url="https://testserver",
    ) as client:
        session_id, csrf = login(client)
        response = client.put(
            "/api/v1/scope",
            json={"project_id": "project-alpha", "region": "RegionOne"},
            headers={"X-CSRF-Token": csrf},
            cookies={"vantage_session": session_id},
        )
        assert response.status_code == expected_status
        assert response.json()["code"] == code
        assert response.json()["openstack_request_id"] == "req-scope"
        if upstream_status == 401:
            assert client.get(
                "/api/v1/session", cookies={"vantage_session": session_id}
            ).status_code == 401


def test_static_frontend_is_same_origin(client: TestClient) -> None:
    response = client.get("/login")
    if response.status_code == 404:
        pytest.skip("frontend build is not present; run npm run build first")
    assert response.status_code == 200
    assert 'src="/assets/' in response.text
    assert "vantage_session" not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    script_path = re.search(r'src="(/assets/[^"]+)"', response.text)
    assert script_path is not None
    asset = client.get(script_path.group(1))
    assert asset.status_code == 200
    assert asset.headers["Cache-Control"] == "public, max-age=31536000, immutable"


@pytest.mark.asyncio
async def test_atomic_rotation_cannot_create_two_successor_sessions() -> None:
    store = MemorySessionStore()
    record = new_session(
        user=User(id="user-alice", name="alice", domain_id="default"),
        projects=(Project(id="alpha", name="Alpha"),),
        regions=("RegionOne",),
        auth_context={"token": "server-only"},
        ttl_seconds=3600,
    )
    await store.create(record)
    first = rotated_session(record)
    second = rotated_session(record)
    assert await store.rotate(record.id, first) is True
    assert await store.rotate(record.id, second) is False
    assert await store.get(first.id) == first
    assert await store.get(second.id) is None


@pytest.mark.asyncio
async def test_store_rejects_expired_record() -> None:
    store = MemorySessionStore()
    record = new_session(
        user=User(id="user-alice", name="alice"),
        projects=(),
        regions=(),
        auth_context={},
        ttl_seconds=3600,
    )
    expired = rotated_session(record, expires_at=datetime.now(UTC) - timedelta(seconds=1))
    await store.create(expired)
    assert await store.get(expired.id) is None


@pytest.mark.asyncio
async def test_login_attempt_reservations_are_atomic() -> None:
    limiter = LoginRateLimiter(limit=2, window_seconds=60)
    reservations = await asyncio.gather(*(limiter.reserve("same-user") for _ in range(8)))
    granted = [reservation for reservation in reservations if reservation is not None]
    assert len(granted) == 2
    await limiter.release("same-user", granted[0])
    assert await limiter.reserve("same-user") is not None
