from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from vantage_bff.app import create_app
from vantage_bff.config import Settings
from vantage_bff.operations import (
    IdempotencyConflictError,
    InvalidOperationTransitionError,
    MemoryOperationStore,
    OperationCapacityError,
    OperationProblem,
    OperationScope,
    OperationStatus,
    OperationTarget,
    operation_fingerprint,
)


class ManualTime:
    def __init__(self) -> None:
        self.monotonic = 100.0
        self.wall = datetime(2026, 1, 1, tzinfo=UTC)

    def clock(self) -> float:
        return self.monotonic

    def now(self) -> datetime:
        return self.wall

    def advance(self, seconds: int) -> None:
        self.monotonic += seconds
        self.wall += timedelta(seconds=seconds)


SCOPE = OperationScope(user_id="user-1", project_id="project-1", region="RegionOne")
TARGET = OperationTarget(resource_type="instance", resource_name="api-01")


def make_store(
    time: ManualTime,
    *,
    terminal_ttl_seconds: int = 60,
    max_records: int = 8,
) -> MemoryOperationStore:
    return MemoryOperationStore(
        terminal_ttl_seconds=terminal_ttl_seconds,
        max_records=max_records,
        clock=time.clock,
        now=time.now,
    )


def test_app_uses_the_injected_operation_store() -> None:
    time = ManualTime()
    store = make_store(time)

    with TestClient(
        create_app(Settings(cookie_secure=True), operation_store=store),
        base_url="https://testserver",
    ) as client:
        assert client.app.state.operations is store


@pytest.mark.asyncio
async def test_same_key_and_payload_replays_exact_operation() -> None:
    time = ManualTime()
    store = make_store(time)
    fingerprint = operation_fingerprint("instance.create", {"name": "api-01", "count": 1})

    first = await store.begin(
        scope=SCOPE,
        idempotency_key="launch-1",
        fingerprint=fingerprint,
        kind="instance.create",
        target=TARGET,
        trace_id="trace-1",
    )
    replay = await store.begin(
        scope=SCOPE,
        idempotency_key=" launch-1 ",
        fingerprint=fingerprint,
        kind="instance.create",
        target=TARGET,
        trace_id="trace-2",
    )

    assert first.replayed is False
    assert replay.replayed is True
    assert replay.operation == first.operation


@pytest.mark.asyncio
async def test_same_key_with_different_request_conflicts() -> None:
    time = ManualTime()
    store = make_store(time)
    await store.begin(
        scope=SCOPE,
        idempotency_key="launch-1",
        fingerprint=operation_fingerprint("instance.create", {"name": "api-01"}),
        kind="instance.create",
        target=TARGET,
        trace_id="trace-1",
    )

    with pytest.raises(IdempotencyConflictError):
        await store.begin(
            scope=SCOPE,
            idempotency_key="launch-1",
            fingerprint=operation_fingerprint("instance.create", {"name": "api-02"}),
            kind="instance.create",
            target=OperationTarget(resource_type="instance", resource_name="api-02"),
            trace_id="trace-2",
        )


@pytest.mark.asyncio
async def test_idempotency_is_scoped_to_user_project_and_region() -> None:
    time = ManualTime()
    store = make_store(time)
    fingerprint = operation_fingerprint("instance.create", {"name": "api-01"})
    scopes = (
        SCOPE,
        OperationScope(user_id="user-2", project_id="project-1", region="RegionOne"),
        OperationScope(user_id="user-1", project_id="project-2", region="RegionOne"),
        OperationScope(user_id="user-1", project_id="project-1", region="RegionTwo"),
    )

    results = [
        await store.begin(
            scope=scope,
            idempotency_key="launch-1",
            fingerprint=fingerprint,
            kind="instance.create",
            target=TARGET,
            trace_id=f"trace-{index}",
        )
        for index, scope in enumerate(scopes)
    ]

    assert len({result.operation.id for result in results}) == len(scopes)
    assert all(result.replayed is False for result in results)


@pytest.mark.asyncio
async def test_operation_visibility_and_terminal_transition() -> None:
    time = ManualTime()
    store = make_store(time)
    begun = await store.begin(
        scope=SCOPE,
        idempotency_key="launch-1",
        fingerprint=operation_fingerprint("instance.create", {"name": "api-01"}),
        kind="instance.create",
        target=TARGET,
        trace_id="trace-1",
    )

    running = await store.mark_running(SCOPE, begun.operation.id)
    assert running is not None
    assert running.status is OperationStatus.RUNNING

    time.advance(2)
    created_target = OperationTarget(
        resource_type="instance",
        resource_id="server-1",
        resource_name="api-01",
    )
    succeeded = await store.succeed(
        SCOPE,
        begun.operation.id,
        target=created_target,
        openstack_request_ids=("req-1", "req-1", "req-2"),
    )
    assert succeeded is not None
    assert succeeded.status is OperationStatus.SUCCEEDED
    assert succeeded.target == created_target
    assert succeeded.openstack_request_ids == ("req-1", "req-2")
    assert succeeded.updated_at == time.wall

    other_scope = OperationScope("user-2", "project-1", "RegionOne")
    assert await store.get(other_scope, begun.operation.id) is None
    with pytest.raises(InvalidOperationTransitionError):
        await store.cancel(SCOPE, begun.operation.id)


@pytest.mark.asyncio
async def test_failure_deduplicates_and_preserves_upstream_request_ids() -> None:
    time = ManualTime()
    store = make_store(time)
    begun = await store.begin(
        scope=SCOPE,
        idempotency_key="launch-1",
        fingerprint=operation_fingerprint("instance.create", {"name": "api-01"}),
        kind="instance.create",
        target=TARGET,
        trace_id="trace-1",
    )
    problem = OperationProblem(
        status=403,
        code="instance_create_forbidden",
        title="Launch denied",
        detail="Nova policy denied the request",
        openstack_request_id="req-policy",
    )

    failed = await store.fail(
        SCOPE,
        begun.operation.id,
        problem=problem,
        openstack_request_ids=("req-create", "req-policy"),
    )

    assert failed is not None
    assert failed.status is OperationStatus.FAILED
    assert failed.problem == problem
    assert failed.openstack_request_ids == ("req-create", "req-policy")


@pytest.mark.asyncio
async def test_terminal_records_expire_and_allow_key_reuse() -> None:
    time = ManualTime()
    store = make_store(time, terminal_ttl_seconds=10, max_records=1)
    fingerprint = operation_fingerprint("instance.create", {"name": "api-01"})
    begun = await store.begin(
        scope=SCOPE,
        idempotency_key="launch-1",
        fingerprint=fingerprint,
        kind="instance.create",
        target=TARGET,
        trace_id="trace-1",
    )
    await store.succeed(SCOPE, begun.operation.id)
    time.advance(11)

    replacement = await store.begin(
        scope=SCOPE,
        idempotency_key="launch-1",
        fingerprint=fingerprint,
        kind="instance.create",
        target=TARGET,
        trace_id="trace-2",
    )

    assert replacement.operation.id != begun.operation.id
    assert await store.get(SCOPE, begun.operation.id) is None


@pytest.mark.asyncio
async def test_capacity_never_evicts_live_idempotency_records() -> None:
    time = ManualTime()
    store = make_store(time, max_records=1)
    first = await store.begin(
        scope=SCOPE,
        idempotency_key="launch-1",
        fingerprint=operation_fingerprint("instance.create", {"name": "api-01"}),
        kind="instance.create",
        target=TARGET,
        trace_id="trace-1",
    )

    with pytest.raises(OperationCapacityError):
        await store.begin(
            scope=SCOPE,
            idempotency_key="launch-2",
            fingerprint=operation_fingerprint("instance.create", {"name": "api-02"}),
            kind="instance.create",
            target=OperationTarget(resource_type="instance", resource_name="api-02"),
            trace_id="trace-2",
        )

    await store.cancel(SCOPE, first.operation.id)
    with pytest.raises(OperationCapacityError):
        await store.begin(
            scope=SCOPE,
            idempotency_key="launch-2",
            fingerprint=operation_fingerprint("instance.create", {"name": "api-02"}),
            kind="instance.create",
            target=OperationTarget(resource_type="instance", resource_name="api-02"),
            trace_id="trace-2",
        )


@pytest.mark.asyncio
async def test_concurrent_duplicate_submission_creates_one_operation() -> None:
    time = ManualTime()
    store = make_store(time)
    fingerprint = operation_fingerprint("instance.create", {"name": "api-01"})

    async def submit() -> str:
        result = await store.begin(
            scope=SCOPE,
            idempotency_key="launch-1",
            fingerprint=fingerprint,
            kind="instance.create",
            target=TARGET,
            trace_id="trace-1",
        )
        return str(result.operation.id)

    operation_ids = await asyncio.gather(*(submit() for _ in range(20)))
    assert len(set(operation_ids)) == 1


def test_fingerprint_is_canonical_and_kind_sensitive() -> None:
    left = operation_fingerprint(
        "instance.create",
        {"metadata": {"b": "2", "a": "1"}, "count": 1},
    )
    right = operation_fingerprint(
        "instance.create",
        {"count": 1, "metadata": {"a": "1", "b": "2"}},
    )
    other_kind = operation_fingerprint(
        "instance.delete",
        {"count": 1, "metadata": {"a": "1", "b": "2"}},
    )

    assert left == right
    assert left != other_kind


@pytest.mark.asyncio
async def test_operation_store_never_retains_request_secret_values() -> None:
    time = ManualTime()
    store = make_store(time)
    secret = "private-value-that-must-not-enter-operation-state"
    fingerprint = operation_fingerprint(
        "instance.create",
        {"name": "api-01", "admin_password": secret, "user_data": secret},
    )

    result = await store.begin(
        scope=SCOPE,
        idempotency_key="launch-secret",
        fingerprint=fingerprint,
        kind="instance.create",
        target=TARGET,
        trace_id="trace-secret",
    )

    assert secret not in repr(store._records)
    assert secret not in repr(result.operation)
