from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vantage_bff.adapters.base import AdapterError
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.app import create_app
from vantage_bff.config import Settings
from vantage_bff.storage.base import StorageListResult
from vantage_bff.storage.fake import FakeStorageAdapter
from vantage_bff.storage.models import StorageResourceKind


class RecordingStorageAdapter(FakeStorageAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, Any]] = []
        self.failure: AdapterError | None = None

    async def list_resources(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        kind: StorageResourceKind,
        *,
        limit: int,
        marker: str | None,
        filters: dict[str, str],
        sort: str,
        direction: str,
        all_projects: bool = False,
    ) -> StorageListResult:
        self.calls.append(
            {
                "project_id": project_id,
                "region": region,
                "kind": kind,
                "limit": limit,
                "marker": marker,
                "filters": filters,
                "sort": sort,
                "direction": direction,
                "all_projects": all_projects,
            }
        )
        if self.failure:
            raise self.failure
        return await super().list_resources(
            auth_context,
            project_id,
            region,
            kind,
            limit=limit,
            marker=marker,
            filters=filters,
            sort=sort,
            direction=direction,
            all_projects=all_projects,
        )


@contextmanager
def client_for(storage: FakeStorageAdapter | None = None) -> Iterator[TestClient]:
    app = create_app(
        Settings(cookie_secure=True),
        adapter=FakeOpenStackAdapter(),
        storage_adapter=storage or FakeStorageAdapter(),
    )
    with TestClient(app, base_url="https://testserver") as client:
        yield client


def login_and_scope(client: TestClient, project: str = "project-alpha") -> str:
    login = client.post(
        "/api/v1/session/login",
        json={"username": "alice", "password": "vantage", "domain": "default"},
    )
    assert login.status_code == 201
    scoped = client.put(
        "/api/v1/scope",
        json={"project_id": project, "region": "RegionOne"},
        headers={"X-CSRF-Token": login.headers["X-CSRF-Token"]},
    )
    assert scoped.status_code == 200
    return scoped.headers["X-CSRF-Token"]


@pytest.mark.parametrize(
    "path",
    [
        "/volumes",
        "/volume-snapshots",
        "/volume-backups",
        "/admin/storage/volume-types",
        "/admin/storage/qos-specs",
        "/admin/storage/pools",
        "/admin/storage/services",
    ],
)
def test_storage_collections_require_authentication_and_scope(path: str) -> None:
    with client_for() as client:
        unauthenticated = client.get(f"/api/v1{path}")
        login = client.post(
            "/api/v1/session/login",
            json={"username": "alice", "password": "vantage", "domain": "default"},
        )
        unscoped = client.get(f"/api/v1{path}")
    assert login.status_code == 201
    assert unauthenticated.status_code == 401
    assert unscoped.status_code == 409


@pytest.mark.parametrize("limit", [10, 25, 50, 100])
def test_volume_pagination_is_server_side_and_discrete(limit: int) -> None:
    storage = RecordingStorageAdapter()
    with client_for(storage) as client:
        login_and_scope(client)
        response = client.get(
            "/api/v1/volumes",
            params={"limit": limit, "name": "alpha", "status": "available"},
        )
    assert response.status_code == 200
    assert response.json()["page"]["size"] == limit
    assert response.json()["page"]["total_items"] is None
    assert storage.calls[0]["limit"] == limit + 1
    assert storage.calls[0]["filters"] == {"name": "alpha", "status": "available"}
    assert response.headers["X-OpenStack-Request-ID"].startswith("req-")


def test_numbered_cursor_chain_and_scope_rotation_prevent_leakage() -> None:
    with client_for() as client:
        csrf = login_and_scope(client)
        first = client.get("/api/v1/volumes?limit=10")
        third = client.get("/api/v1/volumes?limit=10&page=3")
        second = client.get("/api/v1/volumes?limit=10&page=2")
        switched = client.put(
            "/api/v1/scope",
            json={"project_id": "project-beta", "region": "RegionOne"},
            headers={"X-CSRF-Token": csrf},
        )
        stale = client.get("/api/v1/volumes?limit=10&page=2")
    assert first.status_code == 200
    assert first.json()["page"]["has_next"] is True
    assert third.status_code == 409
    assert second.status_code == 200
    assert switched.status_code == 200
    assert stale.status_code == 409


def test_create_requires_csrf_and_idempotency_and_deduplicates() -> None:
    payload = {"size_gib": 10, "name": "data", "metadata": {"owner": "alice"}}
    with client_for() as client:
        csrf = login_and_scope(client)
        no_csrf = client.post(
            "/api/v1/volumes", json=payload, headers={"Idempotency-Key": "create-1"}
        )
        no_key = client.post("/api/v1/volumes", json=payload, headers={"X-CSRF-Token": csrf})
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "create-1"}
        created = client.post("/api/v1/volumes", json=payload, headers=headers)
        replayed = client.post("/api/v1/volumes", json=payload, headers=headers)
        conflict = client.post("/api/v1/volumes", json={**payload, "size_gib": 20}, headers=headers)
    assert no_csrf.status_code == 403
    assert no_key.status_code == 400
    assert created.status_code == 202
    assert created.json()["status"] == "succeeded"
    assert replayed.json()["id"] == created.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"


def test_operation_is_isolated_by_user_project_and_region() -> None:
    with client_for() as client:
        csrf = login_and_scope(client)
        created = client.post(
            "/api/v1/volumes",
            json={"size_gib": 10, "name": "isolated"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "isolated-create"},
        )
        operation_id = created.json()["id"]
        visible = client.get(f"/api/v1/operations/{operation_id}")
        switched = client.put(
            "/api/v1/scope",
            json={"project_id": "project-beta", "region": "RegionOne"},
            headers={"X-CSRF-Token": csrf},
        )
        hidden = client.get(f"/api/v1/operations/{operation_id}")
    assert visible.status_code == 200
    assert switched.status_code == 200
    assert hidden.status_code == 404


def test_delete_and_force_delete_require_exact_confirmation() -> None:
    with client_for() as client:
        csrf = login_and_scope(client)
        volume = client.get("/api/v1/volumes?limit=10&status=in-use").json()["items"][0]
        headers = {"X-CSRF-Token": csrf, "Idempotency-Key": "delete-attached"}
        mismatch = client.delete(
            f"/api/v1/volumes/{volume['id']}", params={"confirmation": "wrong"}, headers=headers
        )
        conflict = client.delete(
            f"/api/v1/volumes/{volume['id']}",
            params={"confirmation": volume["id"]},
            headers=headers,
        )
        forced = client.post(
            f"/api/v1/volumes/{volume['id']}/actions",
            json={"action": "force_delete", "confirmation": volume["id"], "force": True},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "force-delete-attached"},
        )
    assert mismatch.status_code == 422
    assert conflict.status_code == 409
    assert conflict.json()["openstack_request_id"].startswith("req-")
    assert forced.status_code == 202


@pytest.mark.parametrize("status", [403, 409])
def test_cinder_policy_and_conflict_are_preserved(status: int) -> None:
    storage = RecordingStorageAdapter()
    storage.failure = AdapterError(status_code=status, request_id=f"req-{status}")
    with client_for(storage) as client:
        login_and_scope(client)
        response = client.get("/api/v1/volumes")
    assert response.status_code == status
    assert response.json()["openstack_request_id"] == f"req-{status}"
    assert response.json()["code"] in {"storage_forbidden", "storage_conflict"}


def test_backup_source_is_exclusive_and_admin_collections_are_policy_driven() -> None:
    storage = RecordingStorageAdapter()
    with client_for(storage) as client:
        csrf = login_and_scope(client)
        invalid = client.post(
            "/api/v1/volume-backups",
            json={"volume_id": "vol", "snapshot_id": "snap"},
            headers={"X-CSRF-Token": csrf, "Idempotency-Key": "bad-backup"},
        )
        types = client.get("/api/v1/admin/storage/volume-types")
    assert invalid.status_code == 422
    assert types.status_code == 200
    assert storage.calls[-1]["all_projects"] is True
    assert storage.calls[-1]["kind"] is StorageResourceKind.VOLUME_TYPE
