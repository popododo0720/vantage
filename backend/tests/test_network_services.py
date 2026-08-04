from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vantage_bff.app import create_app
from vantage_bff.config import Settings
from vantage_bff.network_models import ResourceKind


@contextmanager
def scoped_client(
    *, username: str = "alice", project_id: str = "project-alpha"
) -> Iterator[tuple[TestClient, str]]:
    with TestClient(create_app(Settings(cookie_secure=False))) as client:
        login = client.post(
            "/api/v1/session/login",
            json={"username": username, "password": "vantage", "domain": "default"},
        )
        assert login.status_code == 201
        selected = client.put(
            "/api/v1/scope",
            json={"project_id": project_id, "region": "RegionOne"},
            headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
        )
        assert selected.status_code == 200
        yield client, selected.headers["X-CSRF-Token"]


def operation(client: TestClient, operation_id: str) -> dict[str, Any]:
    response = client.get(f"/api/v1/network/operations/{operation_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in {"succeeded", "failed"}
    return data


def test_capabilities_cover_every_neutron_and_octavia_resource() -> None:
    with scoped_client() as (client, _csrf):
        response = client.get("/api/v1/network/capabilities")

    assert response.status_code == 200
    body = response.json()
    assert body["neutron"] is True
    assert body["octavia"] is True
    assert {item["resource_type"] for item in body["resources"]} == {
        kind.value for kind in ResourceKind
    }
    port = next(item for item in body["resources"] if item["resource_type"] == "port")
    assert {"attach_instance", "detach_instance", "add_fixed_ip", "remove_fixed_ip"} <= set(
        port["actions"]
    )
    assert next(field for field in port["fields"] if field["name"] == "host_id")["admin_only"]


@pytest.mark.parametrize("limit", [10, 25, 50, 100])
def test_network_lists_use_bounded_numbered_pagination(limit: int) -> None:
    with scoped_client() as (client, _csrf):
        first = client.get(f"/api/v1/network/resources/network?limit={limit}")
        assert first.status_code == 200
        page = first.json()["page"]
        assert page["size"] == limit
        assert len(first.json()["items"]) <= limit
        assert "marker" not in first.text
        if limit == 10:
            assert page["navigable_pages"] == [1, 2]
            second = client.get("/api/v1/network/resources/network?limit=10&page=2")
            assert second.status_code == 200
            assert second.json()["page"]["has_previous"] is True


def test_progressive_page_cannot_be_skipped() -> None:
    with scoped_client() as (client, _csrf):
        response = client.get("/api/v1/network/resources/network?limit=10&page=3")

    assert response.status_code == 409
    assert response.json()["code"] == "page_cursor_unavailable"


def test_create_replays_same_idempotent_operation_without_duplicate() -> None:
    with scoped_client() as (client, csrf):
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "network-create-1"}
        payload = {"attributes": {"name": "application-network", "mtu": 1450}}
        first = client.post("/api/v1/network/resources/network", json=payload, headers=headers)
        replay = client.post("/api/v1/network/resources/network", json=payload, headers=headers)
        result = operation(client, first.json()["id"])

        assert first.status_code == replay.status_code == 202
        assert replay.json()["id"] == first.json()["id"]
        assert result["status"] == "succeeded"
        assert result["openstack_request_ids"]


def test_idempotency_key_cannot_be_reused_for_different_payload() -> None:
    with scoped_client() as (client, csrf):
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "same-key"}
        first = client.post(
            "/api/v1/network/resources/network",
            json={"attributes": {"name": "one"}},
            headers=headers,
        )
        conflict = client.post(
            "/api/v1/network/resources/network",
            json={"attributes": {"name": "two"}},
            headers=headers,
        )

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


@pytest.mark.parametrize("csrf", [None, "wrong"])
def test_mutations_require_session_bound_csrf(csrf: str | None) -> None:
    with scoped_client() as (client, _valid_csrf):
        headers = {"Idempotency-Key": "csrf-check"}
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        response = client.post(
            "/api/v1/network/resources/network",
            json={"attributes": {"name": "blocked"}},
            headers=headers,
        )

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_invalid"


def test_project_route_separates_provider_and_shared_network_fields() -> None:
    with scoped_client() as (client, csrf):
        response = client.post(
            "/api/v1/network/resources/network",
            json={
                "attributes": {
                    "name": "provider-network",
                    "is_shared": True,
                    "is_router_external": True,
                    "provider_network_type": "vlan",
                }
            },
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "provider-create"},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "admin_scope_required"


@pytest.mark.parametrize(
    ("kind", "attributes", "code"),
    [
        ("load_balancer", {"name": "missing-vip"}, "load_balancer_vip_required"),
        (
            "pool",
            {"name": "missing-parent", "protocol": "HTTP", "lb_algorithm": "ROUND_ROBIN"},
            "pool_parent_required",
        ),
    ],
)
def test_octavia_create_requires_real_parent_contract(
    kind: str, attributes: dict[str, Any], code: str
) -> None:
    with scoped_client() as (client, csrf):
        response = client.post(
            f"/api/v1/network/resources/{kind}",
            json={"attributes": attributes},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"{kind}-parent"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == code


def test_immutable_security_group_rule_edit_is_explicit() -> None:
    with scoped_client() as (client, csrf):
        response = client.patch(
            "/api/v1/network/resources/security_group_rule/rule-id",
            json={"attributes": {"protocol": "tcp"}},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "rule-update"},
        )

    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_network_fields"


def test_octavia_resources_keep_provisioning_and_operating_status() -> None:
    with scoped_client() as (client, _csrf):
        response = client.get("/api/v1/network/resources/load_balancer")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["provisioning_status"] == "ACTIVE"
    assert item["operating_status"] == "ONLINE"
    assert "health" not in item


def test_floating_ip_disassociate_keeps_allocation() -> None:
    with scoped_client() as (client, csrf):
        listed = client.get("/api/v1/network/resources/floating_ip")
        floating_ip = listed.json()["items"][0]
        response = client.post(
            f"/api/v1/network/resources/floating_ip/{floating_ip['id']}/actions",
            json={"action": "disassociate", "parameters": {}},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "fip-disassociate"},
        )
        result = operation(client, response.json()["id"])
        detail = client.get(f"/api/v1/network/resources/floating_ip/{floating_ip['id']}")

    assert result["status"] == "succeeded"
    assert detail.status_code == 200
    assert detail.json()["attributes"]["port_id"] is None


def test_revision_conflict_is_a_failed_operation_with_request_id() -> None:
    with scoped_client() as (client, csrf):
        listed = client.get("/api/v1/network/resources/port")
        port = listed.json()["items"][0]
        response = client.patch(
            f"/api/v1/network/resources/port/{port['id']}",
            json={"attributes": {"name": "changed"}, "revision_number": 999},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "stale-port"},
        )
        result = operation(client, response.json()["id"])

    assert result["status"] == "failed"
    assert result["problem"]["status"] == 409
    assert result["problem"]["code"] == "network_resource_conflict"
    assert result["problem"]["openstack_request_id"].startswith("req-")


def test_delete_requires_exact_confirmation_and_preserves_resource_on_mismatch() -> None:
    with scoped_client() as (client, csrf):
        listed = client.get("/api/v1/network/resources/router")
        router = listed.json()["items"][0]
        response = client.post(
            f"/api/v1/network/resources/router/{router['id']}/delete",
            json={"confirmation": "wrong"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "router-delete"},
        )
        detail = client.get(f"/api/v1/network/resources/router/{router['id']}")

    assert response.status_code == 422
    assert response.json()["code"] == "delete_confirmation_mismatch"
    assert detail.status_code == 200


def test_operation_is_not_visible_after_project_switch() -> None:
    with scoped_client() as (client, csrf):
        created = client.post(
            "/api/v1/network/resources/network",
            json={"attributes": {"name": "alpha-only"}},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "alpha-create"},
        )
        operation(client, created.json()["id"])
        switched = client.put(
            "/api/v1/scope",
            json={"project_id": "project-beta", "region": "RegionOne"},
            headers={"X-CSRF-Token": csrf},
        )
        assert switched.status_code == 200
        hidden = client.get(f"/api/v1/network/operations/{created.json()['id']}")

    assert hidden.status_code == 404


def test_qos_and_nested_octavia_resources_require_parent_context() -> None:
    with scoped_client() as (client, _csrf):
        qos = client.get("/api/v1/network/resources/qos_rule")
        member = client.get("/api/v1/network/resources/member")
        rule = client.get("/api/v1/network/resources/l7_rule")

    assert qos.status_code == member.status_code == rule.status_code == 422
    assert member.json()["code"] == "parent_required"
