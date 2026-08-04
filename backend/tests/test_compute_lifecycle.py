from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

from fastapi.testclient import TestClient
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.app import create_app
from vantage_bff.compute_models import RemoteConsoleResult
from vantage_bff.config import Settings


class RecordingAdapter(FakeOpenStackAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.created_payloads: list[dict[str, Any]] = []

    async def create_instances(
        self, auth_context: dict[str, Any], project_id: str, region: str, payload: dict[str, Any]
    ):  # type: ignore[no-untyped-def]
        self.created_payloads.append(payload)
        return await super().create_instances(auth_context, project_id, region, payload)

    async def create_console(
        self, auth_context: dict[str, Any], project_id: str, region: str, instance_id: str
    ) -> RemoteConsoleResult:
        await self.get_instance(auth_context, project_id, region, instance_id)
        return RemoteConsoleResult(url="https://console.invalid/novnc/one-time-secret")


@contextmanager
def scoped_client(adapter: FakeOpenStackAdapter) -> Iterator[tuple[TestClient, str]]:
    with TestClient(
        create_app(Settings(cookie_secure=True), adapter=adapter),
        base_url="https://testserver",
    ) as client:
        login = client.post(
            "/api/v1/session/login",
            json={"username": "alice", "password": "vantage", "domain": "default"},
        )
        scope = client.put(
            "/api/v1/scope",
            json={"project_id": "project-alpha", "region": "RegionOne"},
            headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
        )
        yield client, scope.headers["X-CSRF-Token"]


def create_payload(name: str = "api-01") -> dict[str, Any]:
    return {
        "name": name,
        "description": "API server",
        "count": 2,
        "boot_source": {
            "type": "image",
            "image_id": "0c17b588-1d6e-4f71-ac7d-6f3116f35a3d",
            "create_boot_volume": True,
            "volume_size_gib": 20,
        },
        "flavor_id": "m1.small",
        "availability_zone": "nova",
        "networks": [
            {
                "network_id": "3469304f-6110-4f33-94fe-7d0d28427682",
                "subnet_id": "3cd0c0cc-0325-485d-bb46-57eddf20213a",
            }
        ],
        "security_group_ids": ["bd195c78-eda9-45ff-8f0e-3c098a960b85"],
        "keypair_name": "alpha-key-01",
        "metadata": {"role": "api"},
        "config_drive": True,
        "user_data": "#cloud-config\npassword: secret",
    }


def test_create_is_csrf_protected_idempotent_and_does_not_expose_user_data() -> None:
    adapter = RecordingAdapter()
    with scoped_client(adapter) as (client, csrf):
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "create-api-01"}
        first = client.post("/api/v1/instances", json=create_payload(), headers=headers)
        assert first.status_code == 202
        operation_id = first.json()["id"]
        completed = client.get(f"/api/v1/operations/{operation_id}")
        assert completed.json()["status"] == "succeeded"
        assert completed.json()["openstack_request_ids"]
        assert "cloud-config" not in completed.text
        assert "password" not in completed.text
        assert adapter.created_payloads[0]["user_data"].startswith("#cloud-config")

        replay = client.post("/api/v1/instances", json=create_payload(), headers=headers)
        assert replay.status_code == 202
        assert replay.json()["id"] == operation_id
        assert len(adapter.created_payloads) == 1

        conflict = client.post("/api/v1/instances", json=create_payload("api-02"), headers=headers)
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "idempotency_conflict"


def test_lifecycle_action_surface_and_operation_scope_isolation() -> None:
    with scoped_client(FakeOpenStackAdapter()) as (client, csrf):
        instance_id = client.get("/api/v1/instances?limit=10&page=1").json()["items"][0]["id"]
        for index, action in enumerate(
            (
                "start",
                "stop",
                "soft_reboot",
                "hard_reboot",
                "pause",
                "unpause",
                "suspend",
                "resume",
                "shelve",
                "unshelve",
                "rescue",
                "unrescue",
                "lock",
                "unlock",
            )
        ):
            response = client.post(
                f"/api/v1/instances/{instance_id}/actions",
                json={"action": action},
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"action-{index}"},
            )
            assert response.status_code == 202
            operation_id = response.json()["id"]
            assert client.get(f"/api/v1/operations/{operation_id}").json()["status"] == "succeeded"

        login = client.post(
            "/api/v1/session/login",
            json={"username": "limited", "password": "vantage", "domain": "default"},
        )
        other_scope = client.put(
            "/api/v1/scope",
            json={"project_id": "project-alpha", "region": "RegionOne"},
            headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
        )
        assert other_scope.status_code == 200
        assert client.get(f"/api/v1/operations/{operation_id}").status_code == 404


def test_resize_rebuild_snapshot_update_delete_and_preview() -> None:
    with scoped_client(FakeOpenStackAdapter()) as (client, csrf):
        instance_id = client.get("/api/v1/instances?limit=10&page=1").json()["items"][0]["id"]
        routes = (
            (
                "PATCH",
                f"/api/v1/instances/{instance_id}",
                {"name": "renamed", "description": "updated", "metadata": {"owner": "ops"}},
            ),
            ("POST", f"/api/v1/instances/{instance_id}/resize", {"flavor_id": "m1.large"}),
            ("POST", f"/api/v1/instances/{instance_id}/resize/confirm", None),
            ("POST", f"/api/v1/instances/{instance_id}/resize/revert", None),
            (
                "POST",
                f"/api/v1/instances/{instance_id}/rebuild",
                {"image_id": "0c17b588-1d6e-4f71-ac7d-6f3116f35a3d"},
            ),
            ("POST", f"/api/v1/instances/{instance_id}/snapshot", {"name": "snap-1"}),
        )
        preview = client.get(f"/api/v1/instances/{instance_id}/delete-preview")
        assert preview.status_code == 200
        assert preview.json()["network_contract"].endswith("/interfaces")
        for index, (method, path, payload) in enumerate(routes):
            response = client.request(
                method,
                path,
                json=payload,
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"mutation-{index}"},
            )
            assert response.status_code == 202

        detail = client.get(f"/api/v1/instances/{instance_id}")
        assert detail.status_code == 200
        assert detail.json()["name"] == "renamed"
        assert detail.json()["description"] == "updated"
        assert detail.json()["metadata"] == {"owner": "ops"}

        deleted = client.delete(
            f"/api/v1/instances/{instance_id}",
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "delete-one"},
        )
        assert deleted.status_code == 202


def test_console_url_is_returned_once_and_never_enters_operation_store() -> None:
    with scoped_client(RecordingAdapter()) as (client, csrf):
        instance_id = client.get("/api/v1/instances?limit=10&page=1").json()["items"][0]["id"]
        response = client.post(
            f"/api/v1/instances/{instance_id}/console",
            json={"protocol": "vnc", "type": "novnc"},
            headers={"X-CSRF-Token": csrf},
        )
        assert response.status_code == 201
        assert response.json()["url"].endswith("one-time-secret")
        assert response.headers["cache-control"] == "no-store"
        assert client.app.state.operations._records == {}


def test_image_and_flavor_policy_mutations_are_tracked_without_keypair_mutation() -> None:
    with scoped_client(FakeOpenStackAdapter()) as (client, csrf):
        cases = (
            ("POST", "/api/v1/images", {"name": "ubuntu", "disk_format": "qcow2"}),
            (
                "POST",
                "/api/v1/flavors",
                {"name": "m1.web", "vcpus": 2, "ram_mib": 2048, "disk_gib": 20},
            ),
        )
        for index, (method, path, payload) in enumerate(cases):
            response = client.request(
                method,
                path,
                json=payload,
                headers={"X-CSRF-Token": csrf, "Idempotency-Key": f"admin-{index}"},
            )
            assert response.status_code == 202
            assert response.json()["target"]["resource_type"] in {"image", "flavor"}
        schema = client.app.openapi()
        assert "post" not in schema["paths"]["/api/v1/keypairs"]
        assert UUID(client.get("/api/v1/images?limit=10&page=1").json()["items"][0]["id"])
