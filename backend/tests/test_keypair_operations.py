from __future__ import annotations

import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from vantage_bff.adapters.base import AdapterError, KeyPairCreateResult, MutationResult
from vantage_bff.adapters.fake import FakeOpenStackAdapter
from vantage_bff.adapters.openstack_sdk import OpenStackSdkAdapter
from vantage_bff.app import create_app
from vantage_bff.config import Settings
from vantage_bff.models import KeyPairType
from vantage_bff.operations import (
    MemoryOperationStore,
    OperationScope,
    OperationStatus,
    OperationTarget,
    operation_fingerprint,
)

PUBLIC_KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIVantageTestKey alice@example"


class RecordingKeyPairAdapter(FakeOpenStackAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.create_calls: list[dict[str, Any]] = []
        self.delete_calls: list[dict[str, Any]] = []
        self.create_failure: AdapterError | None = None
        self.delete_failure: AdapterError | None = None

    async def create_keypair(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        name: str,
        key_type: KeyPairType,
        public_key: str | None,
    ) -> KeyPairCreateResult:
        self.create_calls.append(
            {
                "project_id": project_id,
                "region": region,
                "name": name,
                "key_type": key_type,
                "public_key": public_key,
            }
        )
        if self.create_failure is not None:
            raise self.create_failure
        return await super().create_keypair(
            auth_context,
            project_id,
            region,
            name=name,
            key_type=key_type,
            public_key=public_key,
        )

    async def delete_keypair(
        self,
        auth_context: dict[str, Any],
        project_id: str,
        region: str,
        *,
        name: str,
    ) -> MutationResult:
        self.delete_calls.append(
            {
                "project_id": project_id,
                "region": region,
                "name": name,
            }
        )
        if self.delete_failure is not None:
            raise self.delete_failure
        return await super().delete_keypair(
            auth_context,
            project_id,
            region,
            name=name,
        )


def operation_store() -> MemoryOperationStore:
    return MemoryOperationStore(terminal_ttl_seconds=3600, max_records=100)


@contextmanager
def client_for(
    adapter: FakeOpenStackAdapter,
    *,
    store: MemoryOperationStore | None = None,
) -> Iterator[TestClient]:
    with TestClient(
        create_app(
            Settings(cookie_secure=True),
            adapter=adapter,
            operation_store=store,
        ),
        base_url="https://testserver",
    ) as client:
        yield client


def login(client: TestClient, username: str = "alice") -> str:
    response = client.post(
        "/api/v1/session/login",
        json={"username": username, "password": "vantage", "domain": "default"},
    )
    assert response.status_code == 201
    return response.headers["X-CSRF-Token"]


def select_scope(
    client: TestClient,
    csrf_token: str,
    project_id: str = "project-alpha",
    region: str = "RegionOne",
) -> str:
    response = client.put(
        "/api/v1/scope",
        json={"project_id": project_id, "region": region},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert response.status_code == 200
    return response.headers["X-CSRF-Token"]


def mutation_headers(csrf_token: str, key: str = "0123456789abcdef") -> dict[str, str]:
    return {
        "X-CSRF-Token": csrf_token,
        "Idempotency-Key": key,
    }


def test_keypair_mutations_require_session_scope_csrf_and_idempotency() -> None:
    payload = {"name": "ops-import", "public_key": PUBLIC_KEY}
    with client_for(FakeOpenStackAdapter()) as client:
        unauthenticated = client.post(
            "/api/v1/keypairs",
            json=payload,
            headers={"Idempotency-Key": "0123456789abcdef"},
        )
        csrf = login(client)
        unscoped = client.post(
            "/api/v1/keypairs",
            json=payload,
            headers=mutation_headers(csrf),
        )
        csrf = select_scope(client, csrf)
        missing_csrf = client.post(
            "/api/v1/keypairs",
            json=payload,
            headers={"Idempotency-Key": "0123456789abcdef"},
        )
        missing_idempotency = client.post(
            "/api/v1/keypairs",
            json=payload,
            headers={"X-CSRF-Token": csrf},
        )

    assert unauthenticated.status_code == 401
    assert unscoped.status_code == 409
    assert unscoped.json()["code"] == "active_scope_required"
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["code"] == "csrf_invalid"
    assert missing_idempotency.status_code == 422
    assert missing_idempotency.json()["code"] == "invalid_request"


@pytest.mark.parametrize(
    ("idempotency_key", "expected_status"),
    [("x" * 15, 422), ("x" * 16, 202), ("x" * 255, 202), ("x" * 256, 422)],
)
def test_idempotency_key_length_boundaries(
    idempotency_key: str,
    expected_status: int,
) -> None:
    with client_for(FakeOpenStackAdapter()) as client:
        csrf = select_scope(client, login(client))
        response = client.post(
            "/api/v1/keypairs",
            json={"name": f"boundary-{len(idempotency_key)}", "public_key": PUBLIC_KEY},
            headers=mutation_headers(csrf, idempotency_key),
        )

    assert response.status_code == expected_status


def test_generated_keypair_in_progress_replay_does_not_call_nova() -> None:
    adapter = RecordingKeyPairAdapter()
    store = operation_store()
    payload = {
        "name": "pending-generated",
        "type": "ssh",
        "mode": "generate",
        "public_key": None,
    }
    asyncio.run(
        store.begin(
            scope=OperationScope("user-alice", "project-alpha", "RegionOne"),
            idempotency_key="pending-generate-01",
            fingerprint=operation_fingerprint("keypair.generate", payload),
            kind="keypair.generate",
            target=OperationTarget(resource_type="keypair", resource_name="pending-generated"),
            trace_id="trace-original",
        )
    )

    with client_for(adapter, store=store) as client:
        csrf = select_scope(client, login(client))
        replayed = client.post(
            "/api/v1/keypairs",
            json={"name": "pending-generated", "mode": "generate"},
            headers=mutation_headers(csrf, "pending-generate-01"),
        )

    assert replayed.status_code == 409
    assert replayed.json()["code"] == "operation_in_progress"
    assert adapter.create_calls == []


def test_import_is_idempotent_persistent_and_user_project_region_scoped() -> None:
    adapter = RecordingKeyPairAdapter()
    store = operation_store()
    with client_for(adapter, store=store) as client:
        csrf = select_scope(client, login(client))
        headers = mutation_headers(csrf)
        payload = {"name": "ops-import", "public_key": PUBLIC_KEY}

        created = client.post("/api/v1/keypairs", json=payload, headers=headers)
        replayed = client.post("/api/v1/keypairs", json=payload, headers=headers)
        conflict = client.post(
            "/api/v1/keypairs",
            json={"name": "different-name", "public_key": PUBLIC_KEY},
            headers=headers,
        )
        listed = client.get("/api/v1/keypairs", params={"limit": 100})
        operation_id = created.json()["id"]
        operation = client.get(f"/api/v1/operations/{operation_id}")
        csrf = select_scope(client, csrf, "project-beta")
        hidden_project = client.get(f"/api/v1/operations/{operation_id}")
        select_scope(client, csrf, "project-alpha", "RegionTwo")
        hidden_region = client.get(f"/api/v1/operations/{operation_id}")

    with client_for(adapter, store=store) as other_user:
        select_scope(other_user, login(other_user, "bob"))
        hidden_user = other_user.get(f"/api/v1/operations/{operation_id}")

    assert created.status_code == 202
    assert created.json()["kind"] == "keypair.import"
    assert created.json()["status"] == "succeeded"
    assert created.json()["target"]["resource_name"] == "ops-import"
    assert created.headers["X-OpenStack-Request-ID"].startswith("req-")
    assert replayed.status_code == 202
    assert replayed.json()["id"] == operation_id
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "idempotency_conflict"
    assert len(adapter.create_calls) == 1
    assert adapter.create_calls[0]["public_key"] == PUBLIC_KEY
    assert any(item["name"] == "ops-import" for item in listed.json()["items"])
    assert operation.status_code == 200
    assert operation.json() == created.json()
    for hidden in (hidden_project, hidden_region, hidden_user):
        assert hidden.status_code == 404
        assert hidden.json()["code"] == "operation_not_found"


def test_generated_private_key_is_returned_once_and_never_stored() -> None:
    store = operation_store()
    with client_for(FakeOpenStackAdapter(), store=store) as client:
        csrf = select_scope(client, login(client))
        headers = mutation_headers(csrf, "generate-keypair-0001")
        payload = {"name": "generated-key", "mode": "generate", "type": "ssh"}

        created = client.post("/api/v1/keypairs", json=payload, headers=headers)
        replayed = client.post("/api/v1/keypairs", json=payload, headers=headers)

    assert created.status_code == 201
    private_key = created.json()["private_key"]
    assert private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----")
    assert replayed.status_code == 409
    assert replayed.json()["code"] == "one_time_secret_unavailable"
    assert private_key not in repr(store._records)
    assert private_key not in repr(store._idempotency)
    snapshot = next(iter(store._records.values())).snapshot
    assert snapshot.status is OperationStatus.SUCCEEDED
    assert snapshot.target.resource_name == "generated-key"


def test_delete_is_idempotent_and_removes_keypair() -> None:
    adapter = RecordingKeyPairAdapter()
    keypair_name = "team/key #1"
    with client_for(adapter) as client:
        csrf = select_scope(client, login(client))
        imported = client.post(
            "/api/v1/keypairs",
            json={"name": keypair_name, "public_key": PUBLIC_KEY},
            headers=mutation_headers(csrf, "import-delete-me-01"),
        )
        headers = mutation_headers(csrf, "delete-delete-me-01")
        encoded_path = "/api/v1/keypairs/team%2Fkey%20%231"
        deleted = client.delete(encoded_path, headers=headers)
        replayed = client.delete(encoded_path, headers=headers)
        listed = client.get("/api/v1/keypairs", params={"limit": 100})

    assert imported.status_code == 202
    assert deleted.status_code == 202
    assert deleted.json()["kind"] == "keypair.delete"
    assert deleted.json()["status"] == "succeeded"
    assert replayed.json()["id"] == deleted.json()["id"]
    assert len(adapter.delete_calls) == 1
    assert adapter.delete_calls[0]["name"] == keypair_name
    assert all(item["name"] != keypair_name for item in listed.json()["items"])


@pytest.mark.parametrize(
    "payload",
    [
        {"name": "missing-public-key"},
        {"name": "generate-with-public", "mode": "generate", "public_key": PUBLIC_KEY},
        {"name": "too-long", "public_key": "x" * 16385},
    ],
)
def test_keypair_mode_contract_rejects_invalid_payloads(payload: dict[str, Any]) -> None:
    with client_for(FakeOpenStackAdapter()) as client:
        csrf = select_scope(client, login(client))
        response = client.post(
            "/api/v1/keypairs",
            json=payload,
            headers=mutation_headers(csrf),
        )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_request"


def test_failed_mutation_is_recorded_and_replayed_without_retry() -> None:
    adapter = RecordingKeyPairAdapter()
    adapter.create_failure = AdapterError(status_code=403, request_id="req-policy")
    store = operation_store()
    with client_for(adapter, store=store) as client:
        csrf = select_scope(client, login(client))
        headers = mutation_headers(csrf)
        payload = {"name": "denied-key", "public_key": PUBLIC_KEY}
        failed = client.post("/api/v1/keypairs", json=payload, headers=headers)
        replayed = client.post("/api/v1/keypairs", json=payload, headers=headers)

    assert failed.status_code == 403
    assert failed.json()["code"] == "keypair_forbidden"
    assert failed.json()["openstack_request_id"] == "req-policy"
    assert replayed.status_code == 403
    assert replayed.json()["code"] == "keypair_forbidden"
    assert len(adapter.create_calls) == 1
    snapshot = next(iter(store._records.values())).snapshot
    assert snapshot.status is OperationStatus.FAILED
    assert snapshot.openstack_request_ids == ("req-policy",)
    assert snapshot.problem is not None
    assert snapshot.problem.code == "keypair_forbidden"


class MutationResponse:
    def __init__(self, body: dict[str, Any] | None = None) -> None:
        self._body = body or {}
        self.headers = {"x-openstack-request-id": "req-upstream-keypair"}

    def json(self) -> dict[str, Any]:
        return self._body


class MutationSession:
    def __init__(self, body: dict[str, Any] | None = None) -> None:
        self.body = body
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def post(self, path: str, **kwargs: Any) -> MutationResponse:
        self.calls.append(("post", path, kwargs))
        return MutationResponse(self.body)

    def delete(self, path: str, **kwargs: Any) -> MutationResponse:
        self.calls.append(("delete", path, kwargs))
        return MutationResponse()


def sdk_adapter_for(
    monkeypatch: pytest.MonkeyPatch,
    session: MutationSession,
) -> OpenStackSdkAdapter:
    adapter = OpenStackSdkAdapter(
        "https://keystone",
        "public",
        "RegionOne",
        5,
        provisioning_timeout_seconds=2.5,
    )
    connection = SimpleNamespace(compute=session)
    monkeypatch.setattr(adapter, "_project_connection", lambda *_args, **_kwargs: connection)
    monkeypatch.setattr("openstack.exceptions.raise_from_response", lambda _response: None)
    monkeypatch.setattr(
        "openstack.utils.pick_microversion",
        lambda _session, required: required,
    )
    return adapter


def test_sdk_import_uses_nova_292_and_preserves_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MutationSession(
        {
            "keypair": {
                "name": "imported-key",
                "type": "ssh",
                "public_key": PUBLIC_KEY,
                "fingerprint": "SHA256:test",
            }
        }
    )
    adapter = sdk_adapter_for(monkeypatch, session)

    result = adapter._create_keypair(
        {"scoped_token": "token"},
        "project-alpha",
        "RegionOne",
        name="imported-key",
        key_type=KeyPairType.SSH,
        public_key=PUBLIC_KEY,
    )

    method, path, kwargs = session.calls[0]
    assert method == "post"
    assert path == "/os-keypairs"
    assert kwargs["microversion"] == "2.92"
    assert kwargs["json"] == {
        "keypair": {
            "name": "imported-key",
            "type": "ssh",
            "public_key": PUBLIC_KEY,
        }
    }
    assert result.private_key is None
    assert result.openstack_request_id == "req-upstream-keypair"


def test_sdk_compatibility_generation_and_encoded_delete_use_nova_210(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    private_key = "-----BEGIN OPENSSH PRIVATE KEY-----\none-time\n-----END OPENSSH PRIVATE KEY-----"
    session = MutationSession(
        {
            "keypair": {
                "name": "generated-key",
                "type": "ssh",
                "public_key": PUBLIC_KEY,
                "private_key": private_key,
            }
        }
    )
    adapter = sdk_adapter_for(monkeypatch, session)

    created = adapter._create_keypair(
        {"scoped_token": "token"},
        "project-alpha",
        "RegionOne",
        name="generated-key",
        key_type=KeyPairType.SSH,
        public_key=None,
    )
    deleted = adapter._delete_keypair(
        {"scoped_token": "token"},
        "project-alpha",
        "RegionOne",
        name="team/key #1",
    )

    create_call, delete_call = session.calls
    assert create_call[2]["microversion"] == "2.10"
    assert "public_key" not in create_call[2]["json"]["keypair"]
    assert created.private_key == private_key
    assert delete_call[0] == "delete"
    assert delete_call[1] == "/os-keypairs/team%2Fkey%20%231"
    assert delete_call[2]["microversion"] == "2.10"
    assert deleted.openstack_request_id == "req-upstream-keypair"
