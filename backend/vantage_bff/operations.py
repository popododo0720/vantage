from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from time import monotonic
from typing import Any, Protocol
from uuid import UUID, uuid4


class OperationStatus(StrEnum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


_TERMINAL_STATUSES = {
    OperationStatus.SUCCEEDED,
    OperationStatus.FAILED,
    OperationStatus.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class OperationScope:
    user_id: str
    project_id: str
    region: str


@dataclass(frozen=True, slots=True)
class OperationTarget:
    resource_type: str
    resource_id: str | None = None
    resource_name: str | None = None


@dataclass(frozen=True, slots=True)
class OperationProblem:
    status: int
    code: str
    title: str
    detail: str
    openstack_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class OperationSnapshot:
    id: UUID
    kind: str
    status: OperationStatus
    submitted_at: datetime
    updated_at: datetime
    target: OperationTarget
    trace_id: str
    openstack_request_ids: tuple[str, ...] = ()
    problem: OperationProblem | None = None


@dataclass(frozen=True, slots=True)
class BeginOperationResult:
    operation: OperationSnapshot
    replayed: bool


@dataclass(frozen=True, slots=True)
class _IdempotencyKey:
    scope: OperationScope
    value: str


@dataclass(slots=True)
class _OperationRecord:
    scope: OperationScope
    idempotency_key: _IdempotencyKey
    fingerprint: str
    snapshot: OperationSnapshot
    expires_at: float | None = None


class IdempotencyConflictError(Exception):
    pass


class OperationCapacityError(Exception):
    pass


class InvalidOperationTransitionError(Exception):
    pass


class OperationStore(Protocol):
    async def begin(
        self,
        *,
        scope: OperationScope,
        idempotency_key: str,
        fingerprint: str,
        kind: str,
        target: OperationTarget,
        trace_id: str,
    ) -> BeginOperationResult: ...

    async def get(
        self,
        scope: OperationScope,
        operation_id: UUID,
    ) -> OperationSnapshot | None: ...

    async def mark_running(
        self,
        scope: OperationScope,
        operation_id: UUID,
    ) -> OperationSnapshot | None: ...

    async def succeed(
        self,
        scope: OperationScope,
        operation_id: UUID,
        *,
        target: OperationTarget | None = None,
        openstack_request_ids: Sequence[str] = (),
    ) -> OperationSnapshot | None: ...

    async def fail(
        self,
        scope: OperationScope,
        operation_id: UUID,
        *,
        problem: OperationProblem,
        openstack_request_ids: Sequence[str] = (),
    ) -> OperationSnapshot | None: ...

    async def cancel(
        self,
        scope: OperationScope,
        operation_id: UUID,
    ) -> OperationSnapshot | None: ...


def operation_fingerprint(kind: str, payload: Mapping[str, Any]) -> str:
    """Hash canonical request data without retaining request or secret values."""

    canonical = json.dumps(
        {"kind": kind, "payload": payload},
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class MemoryOperationStore:
    """Bounded in-memory operation state; production stores can implement the protocol."""

    def __init__(
        self,
        *,
        terminal_ttl_seconds: int,
        max_records: int,
        clock: Callable[[], float] = monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if terminal_ttl_seconds <= 0 or max_records <= 0:
            raise ValueError("Operation store limits must be positive")
        self._terminal_ttl_seconds = terminal_ttl_seconds
        self._max_records = max_records
        self._clock = clock
        self._now = now or (lambda: datetime.now(UTC))
        self._records: dict[UUID, _OperationRecord] = {}
        self._idempotency: dict[_IdempotencyKey, UUID] = {}
        self._lock = asyncio.Lock()

    async def begin(
        self,
        *,
        scope: OperationScope,
        idempotency_key: str,
        fingerprint: str,
        kind: str,
        target: OperationTarget,
        trace_id: str,
    ) -> BeginOperationResult:
        normalized_key = idempotency_key.strip()
        if not normalized_key:
            raise ValueError("Idempotency key must not be empty")
        if not fingerprint:
            raise ValueError("Operation fingerprint must not be empty")

        async with self._lock:
            self._purge_expired(self._clock())
            key = _IdempotencyKey(scope=scope, value=normalized_key)
            existing_id = self._idempotency.get(key)
            if existing_id is not None:
                existing = self._records.get(existing_id)
                if existing is None:
                    self._idempotency.pop(key, None)
                else:
                    if existing.fingerprint != fingerprint:
                        raise IdempotencyConflictError
                    return BeginOperationResult(existing.snapshot, replayed=True)

            self._ensure_capacity()
            timestamp = self._utc_now()
            snapshot = OperationSnapshot(
                id=uuid4(),
                kind=kind,
                status=OperationStatus.ACCEPTED,
                submitted_at=timestamp,
                updated_at=timestamp,
                target=target,
                trace_id=trace_id,
            )
            self._records[snapshot.id] = _OperationRecord(
                scope=scope,
                idempotency_key=key,
                fingerprint=fingerprint,
                snapshot=snapshot,
            )
            self._idempotency[key] = snapshot.id
            return BeginOperationResult(snapshot, replayed=False)

    async def get(
        self,
        scope: OperationScope,
        operation_id: UUID,
    ) -> OperationSnapshot | None:
        async with self._lock:
            self._purge_expired(self._clock())
            record = self._visible_record(scope, operation_id)
            return record.snapshot if record is not None else None

    async def mark_running(
        self,
        scope: OperationScope,
        operation_id: UUID,
    ) -> OperationSnapshot | None:
        return await self._transition(
            scope,
            operation_id,
            status=OperationStatus.RUNNING,
            allowed_from={OperationStatus.ACCEPTED},
        )

    async def succeed(
        self,
        scope: OperationScope,
        operation_id: UUID,
        *,
        target: OperationTarget | None = None,
        openstack_request_ids: Sequence[str] = (),
    ) -> OperationSnapshot | None:
        return await self._transition(
            scope,
            operation_id,
            status=OperationStatus.SUCCEEDED,
            allowed_from={OperationStatus.ACCEPTED, OperationStatus.RUNNING},
            target=target,
            openstack_request_ids=openstack_request_ids,
        )

    async def fail(
        self,
        scope: OperationScope,
        operation_id: UUID,
        *,
        problem: OperationProblem,
        openstack_request_ids: Sequence[str] = (),
    ) -> OperationSnapshot | None:
        return await self._transition(
            scope,
            operation_id,
            status=OperationStatus.FAILED,
            allowed_from={OperationStatus.ACCEPTED, OperationStatus.RUNNING},
            problem=problem,
            openstack_request_ids=openstack_request_ids,
        )

    async def cancel(
        self,
        scope: OperationScope,
        operation_id: UUID,
    ) -> OperationSnapshot | None:
        return await self._transition(
            scope,
            operation_id,
            status=OperationStatus.CANCELLED,
            allowed_from={OperationStatus.ACCEPTED, OperationStatus.RUNNING},
        )

    async def _transition(
        self,
        scope: OperationScope,
        operation_id: UUID,
        *,
        status: OperationStatus,
        allowed_from: set[OperationStatus],
        target: OperationTarget | None = None,
        problem: OperationProblem | None = None,
        openstack_request_ids: Sequence[str] = (),
    ) -> OperationSnapshot | None:
        async with self._lock:
            now = self._clock()
            self._purge_expired(now)
            record = self._visible_record(scope, operation_id)
            if record is None:
                return None
            if record.snapshot.status not in allowed_from:
                raise InvalidOperationTransitionError(
                    f"Cannot transition {record.snapshot.status} to {status}"
                )
            request_ids = _merged_request_ids(
                record.snapshot.openstack_request_ids,
                openstack_request_ids,
                problem.openstack_request_id if problem is not None else None,
            )
            record.snapshot = replace(
                record.snapshot,
                status=status,
                updated_at=self._utc_now(),
                target=target or record.snapshot.target,
                openstack_request_ids=request_ids,
                problem=problem,
            )
            if status in _TERMINAL_STATUSES:
                record.expires_at = now + self._terminal_ttl_seconds
            return record.snapshot

    def _visible_record(
        self,
        scope: OperationScope,
        operation_id: UUID,
    ) -> _OperationRecord | None:
        record = self._records.get(operation_id)
        if record is None or record.scope != scope:
            return None
        return record

    def _purge_expired(self, now: float) -> None:
        for operation_id, record in tuple(self._records.items()):
            if record.expires_at is not None and record.expires_at <= now:
                self._delete(operation_id, record)

    def _ensure_capacity(self) -> None:
        if len(self._records) < self._max_records:
            return
        # Evicting a live idempotency record would permit a duplicate mutation.
        raise OperationCapacityError

    def _delete(self, operation_id: UUID, record: _OperationRecord) -> None:
        self._records.pop(operation_id, None)
        if self._idempotency.get(record.idempotency_key) == operation_id:
            self._idempotency.pop(record.idempotency_key, None)

    def _utc_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None:
            raise ValueError("Operation timestamps must be timezone-aware")
        return value.astimezone(UTC)


def _merged_request_ids(
    current: Sequence[str],
    additional: Sequence[str],
    problem_request_id: str | None,
) -> tuple[str, ...]:
    values = [*current, *additional]
    if problem_request_id is not None:
        values.append(problem_request_id)
    return tuple(dict.fromkeys(value for value in values if value))
