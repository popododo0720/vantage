from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from fastapi.testclient import TestClient
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.admin.models import AdminScopeType, QuotaUpdate, RoleAssignmentCreate
from vantage_bff.admin.openstack import change_role, list_resources, reset_quotas, update_quotas
from vantage_bff.app import create_app
from vantage_bff.config import Settings
from vantage_bff.models import QuotaService


@contextmanager
def client_for(adapter: FakeOpenStackAdapter | None = None) -> Iterator[TestClient]:
    app = create_app(Settings(cookie_secure=False), adapter=adapter or FakeOpenStackAdapter())
    with TestClient(app) as client:
        yield client


def login(client: TestClient, username: str = "alice") -> str:
    response = client.post(
        "/api/v1/session/login",
        json={"username": username, "password": "vantage", "domain": "default"},
    )
    assert response.status_code == 201
    return response.headers["X-CSRF-Token"]


def select_system_scope(client: TestClient, csrf: str) -> str:
    response = client.put(
        "/api/v1/admin/scope",
        headers={"X-CSRF-Token": csrf},
        json={"type": "system", "id": "all"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["active_scope"] == {"type": "system", "id": "all", "name": "System"}
    return response.headers["X-CSRF-Token"]


def wait_for_operation(client: TestClient, operation_id: str) -> dict[str, Any]:
    for _ in range(50):
        response = client.get(f"/api/v1/admin/operations/{operation_id}")
        assert response.status_code == 200, response.text
        body = response.json()
        if body["status"] in {"succeeded", "failed", "cancelled"}:
            return body
        time.sleep(0.01)
    raise AssertionError("operation did not finish")


def test_admin_workspace_is_discovered_by_policy_not_a_browser_role_guess() -> None:
    with client_for() as client:
        login(client)
        assert client.get("/api/v1/session").json()["admin_available"] is True
        response = client.get("/api/v1/admin/session")
        assert response.status_code == 200
        assert response.json()["available_scopes"] == [
            {"type": "system", "id": "all", "name": "System"},
            {"type": "domain", "id": "default", "name": "default"},
            {"type": "project", "id": "project-alpha", "name": "Alpha"},
        ]

    with client_for() as client:
        login(client, "limited")
        assert client.get("/api/v1/session").json()["admin_available"] is False
        denied = client.get("/api/v1/admin/session")
        assert denied.status_code == 403
        assert denied.json()["code"] == "admin_workspace_forbidden"


def test_admin_projects_are_server_filtered_and_cursor_paginated() -> None:
    with client_for() as client:
        csrf = select_system_scope(client, login(client))
        del csrf
        first = client.get("/api/v1/admin/identity/projects?limit=10&page=1")
        assert first.status_code == 200
        assert len(first.json()["items"]) == 10
        assert first.json()["page"]["has_next"] is True
        assert "X-OpenStack-Request-ID" in first.headers

        second = client.get("/api/v1/admin/identity/projects?limit=10&page=2")
        assert second.status_code == 200
        assert second.json()["page"]["number"] == 2
        assert {item["id"] for item in first.json()["items"]}.isdisjoint(
            item["id"] for item in second.json()["items"]
        )

        filtered = client.get("/api/v1/admin/identity/projects?name=Alpha&limit=25&page=1")
        assert [item["id"] for item in filtered.json()["items"]] == ["project-alpha"]


def test_identity_mutations_require_confirmation_and_are_auditable() -> None:
    with client_for() as client:
        csrf = select_system_scope(client, login(client))
        payload = {
            "name": "payments",
            "description": "Payments project",
            "domain_id": "default",
            "enabled": True,
        }
        rejected = client.post(
            "/api/v1/admin/identity/projects",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "create-payments"},
            json=payload,
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "confirmation_mismatch"

        accepted = client.post(
            "/api/v1/admin/identity/projects",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "create-payments",
                "X-Confirm-Target": "payments",
            },
            json=payload,
        )
        assert accepted.status_code == 202
        operation = wait_for_operation(client, accepted.json()["operation_id"])
        assert operation["status"] == "succeeded"
        assert operation["target_name"] == "payments"
        assert operation["openstack_request_ids"]

        replay = client.post(
            "/api/v1/admin/identity/projects",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "create-payments",
                "X-Confirm-Target": "payments",
            },
            json=payload,
        )
        assert replay.status_code == 202
        assert replay.json()["replayed"] is True
        assert replay.json()["operation_id"] == accepted.json()["operation_id"]


def test_project_quota_update_reset_and_compute_user_quota() -> None:
    with client_for() as client:
        csrf = select_system_scope(client, login(client))
        initial = client.get("/api/v1/admin/projects/project-alpha/quotas")
        assert initial.status_code == 200
        assert {item["service"] for item in initial.json()["quotas"]} == {
            "compute", "network", "storage"
        }

        updated = client.put(
            "/api/v1/admin/projects/project-alpha/quotas/compute",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "quota-compute-update",
                "X-Confirm-Target": "project-alpha",
            },
            json={"values": {"instances": 120}, "user_id": "user-01"},
        )
        assert updated.status_code == 202
        assert wait_for_operation(client, updated.json()["operation_id"])["status"] == "succeeded"
        user_quota = client.get(
            "/api/v1/admin/projects/project-alpha/quotas?service=compute&user_id=user-01"
        )
        assert next(
            item for item in user_quota.json()["quotas"] if item["resource"] == "instances"
        )["limit"] == 120

        reset = client.request(
            "DELETE",
            "/api/v1/admin/projects/project-alpha/quotas/compute?user_id=user-01",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "quota-compute-reset"},
            json={"confirm": "project-alpha"},
        )
        assert reset.status_code == 202
        assert wait_for_operation(client, reset.json()["operation_id"])["status"] == "succeeded"


def test_admin_scope_isolation_hides_operations_after_scope_switch() -> None:
    with client_for() as client:
        csrf = select_system_scope(client, login(client))
        accepted = client.post(
            "/api/v1/admin/identity/groups",
            headers={
                "X-CSRF-Token": csrf,
                "Idempotency-Key": "create-ops",
                "X-Confirm-Target": "ops",
            },
            json={"name": "ops", "domain_id": "default"},
        )
        operation_id = accepted.json()["operation_id"]
        wait_for_operation(client, operation_id)

        switched = client.put(
            "/api/v1/admin/scope",
            headers={"X-CSRF-Token": csrf},
            json={"type": "domain", "id": "default"},
        )
        assert switched.status_code == 200
        assert client.get(f"/api/v1/admin/operations/{operation_id}").status_code == 404


def test_admin_can_establish_an_authoritative_project_context() -> None:
    with client_for() as client:
        csrf = select_system_scope(client, login(client))
        switched = client.put(
            "/api/v1/admin/scope",
            headers={"X-CSRF-Token": csrf},
            json={"type": "project", "id": "project-alpha"},
        )
        assert switched.status_code == 200
        assert switched.json()["active_scope"] == {
            "type": "project", "id": "project-alpha", "name": "Alpha"
        }
        assert switched.headers["X-CSRF-Token"] != csrf
        projects = client.get("/api/v1/admin/identity/projects?limit=10&page=1")
        assert projects.status_code == 200


def test_sdk_identity_list_uses_bounded_server_query_and_next_link() -> None:
    response = Mock()
    response.status_code = 200
    response.headers = {"X-OpenStack-Request-ID": "req-keystone"}
    response.json.return_value = {
        "projects": [{"id": "project-1", "name": "One", "enabled": True}],
        "links": {"next": "https://keystone.example/v3/projects?limit=10&marker=project-1"},
    }
    identity = Mock()
    identity.get.return_value = response
    result = list_resources(
        SimpleNamespace(identity=identity),
        "projects",
        limit=10,
        cursor=None,
        name="One",
        filters={"domain_id": "default"},
        request_id="req-global",
    )

    identity.get.assert_called_once_with(
        "/projects", params={"limit": 10, "name": "One", "domain_id": "default"}
    )
    assert result.items[0].id == "project-1"
    assert result.openstack_request_id == "req-keystone"
    assert result.next_cursor is not None and "marker=project-1" in result.next_cursor


def test_sdk_role_assignment_calls_scope_specific_proxy_contract() -> None:
    identity = Mock()
    payload = RoleAssignmentCreate(
        role_id="role-admin",
        actor_type="user",
        actor_id="user-alice",
        scope_type=AdminScopeType.PROJECT,
        scope_id="project-alpha",
        inherited=True,
    )
    result = change_role(
        SimpleNamespace(identity=identity), payload, revoke=False, request_id="req-role"
    )

    identity.assign_project_role_to_user.assert_called_once_with(
        "project-alpha", "user-alice", "role-admin", inherited=True
    )
    assert result.resource is not None
    assert result.openstack_request_ids == ["req-role"]


def test_sdk_quota_update_and_reset_keep_user_scope_compute_only() -> None:
    compute = Mock()
    connection = SimpleNamespace(compute=compute, network=Mock(), block_storage=Mock())
    update_quotas(
        connection,
        "project-alpha",
        QuotaService.COMPUTE,
        QuotaUpdate(values={"instances": 40}, user_id="user-alice"),
        "req-quota-update",
    )
    reset_quotas(
        connection,
        "project-alpha",
        QuotaService.COMPUTE,
        "user-alice",
        "req-quota-reset",
    )

    compute.update_quota_set.assert_called_once_with(
        "project-alpha", instances=40, user="user-alice"
    )
    compute.revert_quota_set.assert_called_once_with(
        "project-alpha", user_id="user-alice"
    )
