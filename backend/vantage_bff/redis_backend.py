from __future__ import annotations

import hashlib
import json
import secrets
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from vantage_bff.cache import CacheKey
from vantage_bff.cursors import CursorKey, CursorLease
from vantage_bff.models import Project, Scope, User
from vantage_bff.operations import (
    BeginOperationResult,
    IdempotencyConflictError,
    InvalidOperationTransitionError,
    OperationProblem,
    OperationScope,
    OperationSnapshot,
    OperationStatus,
    OperationTarget,
)
from vantage_bff.sessions import SessionRecord


def create_redis(url: str) -> Any:
    try:
        from redis.asyncio import Redis
    except ImportError as exc:  # pragma: no cover - configuration boundary
        raise RuntimeError("Install vantage-bff[platform] to use Redis stores") from exc
    return Redis.from_url(
        url,
        encoding="utf-8",
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )


class RedisSessionStore:
    def __init__(self, redis: Any, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    async def create(self, record: SessionRecord) -> None:
        ttl = max(1, int((record.expires_at - datetime.now(UTC)).total_seconds()))
        await self._redis.set(self._key(record.id), _session_json(record), ex=ttl)

    async def get(self, session_id: str) -> SessionRecord | None:
        payload = await self._redis.get(self._key(session_id))
        if payload is None:
            return None
        try:
            record = _session_from_json(payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            await self.delete(session_id)
            return None
        if record.expires_at <= datetime.now(UTC):
            await self.delete(session_id)
            return None
        return record

    async def delete(self, session_id: str) -> None:
        await self._redis.delete(self._key(session_id))

    async def rotate(self, old_id: str, record: SessionRecord) -> bool:
        ttl_ms = max(1, int((record.expires_at - datetime.now(UTC)).total_seconds() * 1000))
        script = """
        if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
        redis.call('DEL', KEYS[1])
        redis.call('PSETEX', KEYS[2], ARGV[1], ARGV[2])
        return 1
        """
        result = await self._redis.eval(
            script, 2, self._key(old_id), self._key(record.id), ttl_ms, _session_json(record)
        )
        return bool(result)

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}:session:{_digest(session_id)}"


class RedisCursorStore:
    def __init__(self, redis: Any, prefix: str, ttl_seconds: int, max_pages: int) -> None:
        self._redis = redis
        self._prefix = prefix
        self._ttl = ttl_seconds
        self._max_pages = max_pages

    async def acquire(self, key: CursorKey, page: int) -> CursorLease | None:
        if page < 1 or page > self._max_pages:
            return None
        redis_key = self._key(key)
        if page == 1:
            generation = secrets.randbits(63)
            payload = json.dumps({"generation": generation, "markers": {"1": None}})
            await self._redis.set(redis_key, payload, ex=self._ttl)
            await self._index(key, redis_key)
            return CursorLease(key=key, generation=generation, page=1, marker=None)
        payload = await self._redis.get(redis_key)
        if payload is None:
            return None
        chain = _json_object(payload)
        marker = cast(dict[str, Any], chain.get("markers", {})).get(str(page), _MISSING)
        if marker is _MISSING:
            return None
        await self._redis.expire(redis_key, self._ttl)
        return CursorLease(
            key=key,
            generation=int(chain["generation"]),
            page=page,
            marker=cast(str | None, marker),
        )

    async def complete(self, lease: CursorLease, next_marker: str | None) -> tuple[int, ...] | None:
        redis_key = self._key(lease.key)
        for _ in range(4):
            async with self._redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(redis_key)
                    payload = await pipe.get(redis_key)
                    if payload is None:
                        return None
                    chain = _json_object(payload)
                    if int(chain["generation"]) != lease.generation:
                        return None
                    markers = cast(dict[str, str | None], chain["markers"])
                    last = lease.page
                    if next_marker is not None and lease.page < self._max_pages:
                        last += 1
                        markers[str(last)] = next_marker
                    for page in tuple(markers):
                        if int(page) > last:
                            markers.pop(page, None)
                    pipe.multi()
                    pipe.set(redis_key, json.dumps(chain, separators=(",", ":")), ex=self._ttl)
                    await pipe.execute()
                    return tuple(sorted(int(page) for page in markers))
                except Exception as exc:
                    if exc.__class__.__name__ != "WatchError":
                        raise
        return None

    async def abandon(self, lease: CursorLease) -> None:
        if lease.page != 1:
            return
        payload = await self._redis.get(self._key(lease.key))
        if payload is not None and int(_json_object(payload)["generation"]) == lease.generation:
            await self._redis.delete(self._key(lease.key))

    async def invalidate(self, key: CursorKey) -> None:
        await self._redis.delete(self._key(key))

    async def invalidate_namespace(self, scope_namespace: str) -> None:
        index = self._index_key(scope_namespace)
        members = await self._redis.smembers(index)
        if members:
            await self._redis.delete(*members)
        await self._redis.delete(index)

    async def _index(self, key: CursorKey, redis_key: str) -> None:
        index = self._index_key(key.scope_namespace)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.sadd(index, redis_key)
            pipe.expire(index, self._ttl)
            await pipe.execute()

    def _key(self, key: CursorKey) -> str:
        raw = json.dumps(
            [key.scope_namespace, key.resource, key.query], separators=(",", ":"), sort_keys=True
        )
        return f"{self._prefix}:cursor:{_digest(raw)}"

    def _index_key(self, scope_namespace: str) -> str:
        return f"{self._prefix}:cursor-index:{_digest(scope_namespace)}"


class RedisLoginRateLimiter:
    def __init__(self, redis: Any, prefix: str, limit: int, window_seconds: int) -> None:
        self._redis = redis
        self._prefix = prefix
        self._limit = limit
        self._window = window_seconds

    async def reserve(self, key: str) -> str | None:
        reservation = secrets.token_urlsafe(16)
        now_ms = int(datetime.now(UTC).timestamp() * 1000)
        script = """
        redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', ARGV[1] - ARGV[2])
        if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then return 0 end
        redis.call('ZADD', KEYS[1], ARGV[1], ARGV[4])
        redis.call('PEXPIRE', KEYS[1], ARGV[2])
        return 1
        """
        accepted = await self._redis.eval(
            script,
            1,
            self._key(key),
            now_ms,
            self._window * 1000,
            self._limit,
            reservation,
        )
        return reservation if accepted else None

    async def release(self, key: str, reservation: str) -> None:
        await self._redis.zrem(self._key(key), reservation)

    async def succeeded(self, key: str) -> None:
        await self._redis.delete(self._key(key))

    def _key(self, value: str) -> str:
        return f"{self._prefix}:login:{_digest(value)}"


class RedisJsonCache:
    def __init__(self, redis: Any, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    async def get(self, key: CacheKey) -> Mapping[str, Any] | None:
        payload = await self._redis.get(self._key(key))
        return None if payload is None else _json_object(payload)

    async def set(self, key: CacheKey, value: Mapping[str, Any], ttl_seconds: int) -> None:
        redis_key = self._key(key)
        payload = json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False)
        index = self._index_key(key.policy_scope)
        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.set(redis_key, payload, ex=ttl_seconds)
            pipe.sadd(index, redis_key)
            pipe.expire(index, ttl_seconds)
            await pipe.execute()

    async def invalidate_policy_scope(self, policy_scope: str) -> None:
        index = self._index_key(policy_scope)
        members = await self._redis.smembers(index)
        if members:
            await self._redis.delete(*members)
        await self._redis.delete(index)

    async def ping(self) -> bool:
        return bool(await self._redis.ping())

    async def close(self) -> None:
        return None

    def _key(self, key: CacheKey) -> str:
        return f"{self._prefix}:cache:{key.digest()}"

    def _index_key(self, policy_scope: str) -> str:
        return f"{self._prefix}:cache-index:{_digest(policy_scope)}"


class RedisOperationStore:
    def __init__(self, redis: Any, prefix: str, terminal_ttl_seconds: int) -> None:
        self._redis = redis
        self._prefix = prefix
        self._ttl = terminal_ttl_seconds

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
        normalized = idempotency_key.strip()
        if not normalized or not fingerprint:
            raise ValueError("Idempotency key and fingerprint must not be empty")
        operation = OperationSnapshot(
            id=uuid4(),
            kind=kind,
            status=OperationStatus.ACCEPTED,
            submitted_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            target=target,
            trace_id=trace_id,
        )
        idem_key = self._idem_key(scope, normalized)
        op_key = self._operation_key(scope, operation.id)
        record = _operation_json(operation, fingerprint, idem_key)
        script = """
        local existing = redis.call('GET', KEYS[1])
        if existing then return existing end
        redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[3])
        redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
        return ''
        """
        existing_id = await self._redis.eval(
            script, 2, idem_key, op_key, str(operation.id), record, self._ttl
        )
        if existing_id:
            existing = await self.get(scope, UUID(str(existing_id)))
            if existing is None:
                await self._redis.delete(idem_key)
                return await self.begin(
                    scope=scope,
                    idempotency_key=normalized,
                    fingerprint=fingerprint,
                    kind=kind,
                    target=target,
                    trace_id=trace_id,
                )
            payload = await self._redis.get(self._operation_key(scope, existing.id))
            if payload is None or _json_object(payload).get("fingerprint") != fingerprint:
                raise IdempotencyConflictError
            return BeginOperationResult(existing, replayed=True)
        return BeginOperationResult(operation, replayed=False)

    async def get(self, scope: OperationScope, operation_id: UUID) -> OperationSnapshot | None:
        payload = await self._redis.get(self._operation_key(scope, operation_id))
        return None if payload is None else _operation_from_json(payload)

    async def mark_running(
        self, scope: OperationScope, operation_id: UUID
    ) -> OperationSnapshot | None:
        return await self._transition(
            scope, operation_id, OperationStatus.RUNNING, {OperationStatus.ACCEPTED}
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
            OperationStatus.SUCCEEDED,
            {OperationStatus.ACCEPTED, OperationStatus.RUNNING},
            target=target,
            request_ids=openstack_request_ids,
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
            OperationStatus.FAILED,
            {OperationStatus.ACCEPTED, OperationStatus.RUNNING},
            problem=problem,
            request_ids=openstack_request_ids,
        )

    async def cancel(self, scope: OperationScope, operation_id: UUID) -> OperationSnapshot | None:
        return await self._transition(
            scope,
            operation_id,
            OperationStatus.CANCELLED,
            {OperationStatus.ACCEPTED, OperationStatus.RUNNING},
        )

    async def _transition(
        self,
        scope: OperationScope,
        operation_id: UUID,
        status: OperationStatus,
        allowed: set[OperationStatus],
        *,
        target: OperationTarget | None = None,
        problem: OperationProblem | None = None,
        request_ids: Sequence[str] = (),
    ) -> OperationSnapshot | None:
        key = self._operation_key(scope, operation_id)
        for _ in range(4):
            async with self._redis.pipeline(transaction=True) as pipe:
                try:
                    await pipe.watch(key)
                    payload = await pipe.get(key)
                    if payload is None:
                        return None
                    raw = _json_object(payload)
                    current = _operation_from_mapping(raw)
                    if current.status not in allowed:
                        raise InvalidOperationTransitionError
                    merged = tuple(
                        dict.fromkeys(
                            [
                                *current.openstack_request_ids,
                                *request_ids,
                                *([problem.openstack_request_id] if problem else []),
                            ]
                        )
                    )
                    updated = OperationSnapshot(
                        id=current.id,
                        kind=current.kind,
                        status=status,
                        submitted_at=current.submitted_at,
                        updated_at=datetime.now(UTC),
                        target=target or current.target,
                        trace_id=current.trace_id,
                        openstack_request_ids=tuple(item for item in merged if item),
                        problem=problem,
                    )
                    pipe.multi()
                    pipe.set(
                        key,
                        _operation_json(
                            updated,
                            str(raw["fingerprint"]),
                            str(raw["idempotency_redis_key"]),
                        ),
                        ex=self._ttl,
                    )
                    pipe.expire(str(raw["idempotency_redis_key"]), self._ttl)
                    await pipe.execute()
                    return updated
                except Exception as exc:
                    if isinstance(exc, InvalidOperationTransitionError):
                        raise
                    if exc.__class__.__name__ != "WatchError":
                        raise
        return None

    def _operation_key(self, scope: OperationScope, operation_id: UUID) -> str:
        return f"{self._prefix}:operation:{_scope_digest(scope)}:{operation_id}"

    def _idem_key(self, scope: OperationScope, value: str) -> str:
        return f"{self._prefix}:idempotency:{_scope_digest(scope)}:{_digest(value)}"


class RedisResources:
    def __init__(self, redis: Any) -> None:
        self.redis = redis

    async def ping(self) -> bool:
        return bool(await self.redis.ping())

    async def close(self) -> None:
        await self.redis.aclose()


_MISSING = object()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _scope_digest(scope: OperationScope) -> str:
    return _digest(f"{scope.user_id}\0{scope.project_id}\0{scope.region}")


def _json_object(payload: str) -> dict[str, Any]:
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Stored value must be a JSON object")
    return cast(dict[str, Any], value)


def _session_json(record: SessionRecord) -> str:
    return json.dumps(
        {
            "id": record.id,
            "csrf_token": record.csrf_token,
            "scope_namespace": record.scope_namespace,
            "user": record.user.model_dump(mode="json"),
            "projects": [item.model_dump(mode="json") for item in record.projects],
            "regions": record.regions,
            "expires_at": record.expires_at.isoformat(),
            "auth_context": record.auth_context,
            "active_scope": (
                record.active_scope.model_dump(mode="json") if record.active_scope else None
            ),
            "locale": record.locale,
        },
        separators=(",", ":"),
        allow_nan=False,
    )


def _session_from_json(payload: str) -> SessionRecord:
    raw = _json_object(payload)
    active = raw.get("active_scope")
    auth_context = raw["auth_context"]
    if not isinstance(auth_context, dict):
        raise TypeError("auth_context must be an object")
    return SessionRecord(
        id=str(raw["id"]),
        csrf_token=str(raw["csrf_token"]),
        scope_namespace=str(raw["scope_namespace"]),
        user=User.model_validate(raw["user"]),
        projects=tuple(Project.model_validate(item) for item in raw["projects"]),
        regions=tuple(str(item) for item in raw["regions"]),
        expires_at=datetime.fromisoformat(str(raw["expires_at"])).astimezone(UTC),
        auth_context=cast(dict[str, Any], auth_context),
        active_scope=Scope.model_validate(active) if active is not None else None,
        locale=str(raw["locale"]),
    )


def _operation_json(
    snapshot: OperationSnapshot,
    fingerprint: str,
    idempotency_redis_key: str,
) -> str:
    return json.dumps(
        {
            "id": str(snapshot.id),
            "kind": snapshot.kind,
            "status": snapshot.status.value,
            "submitted_at": snapshot.submitted_at.isoformat(),
            "updated_at": snapshot.updated_at.isoformat(),
            "target": {
                "resource_type": snapshot.target.resource_type,
                "resource_id": snapshot.target.resource_id,
                "resource_name": snapshot.target.resource_name,
            },
            "trace_id": snapshot.trace_id,
            "openstack_request_ids": snapshot.openstack_request_ids,
            "problem": (
                {
                    "status": snapshot.problem.status,
                    "code": snapshot.problem.code,
                    "title": snapshot.problem.title,
                    "detail": snapshot.problem.detail,
                    "openstack_request_id": snapshot.problem.openstack_request_id,
                }
                if snapshot.problem
                else None
            ),
            "fingerprint": fingerprint,
            "idempotency_redis_key": idempotency_redis_key,
        },
        separators=(",", ":"),
        allow_nan=False,
    )


def _operation_from_json(payload: str) -> OperationSnapshot:
    return _operation_from_mapping(_json_object(payload))


def _operation_from_mapping(raw: Mapping[str, Any]) -> OperationSnapshot:
    target = cast(Mapping[str, Any], raw["target"])
    problem_raw = cast(Mapping[str, Any] | None, raw.get("problem"))
    return OperationSnapshot(
        id=UUID(str(raw["id"])),
        kind=str(raw["kind"]),
        status=OperationStatus(str(raw["status"])),
        submitted_at=datetime.fromisoformat(str(raw["submitted_at"])).astimezone(UTC),
        updated_at=datetime.fromisoformat(str(raw["updated_at"])).astimezone(UTC),
        target=OperationTarget(
            resource_type=str(target["resource_type"]),
            resource_id=(str(target["resource_id"]) if target.get("resource_id") else None),
            resource_name=(str(target["resource_name"]) if target.get("resource_name") else None),
        ),
        trace_id=str(raw["trace_id"]),
        openstack_request_ids=tuple(str(item) for item in raw["openstack_request_ids"]),
        problem=(
            OperationProblem(
                status=int(problem_raw["status"]),
                code=str(problem_raw["code"]),
                title=str(problem_raw["title"]),
                detail=str(problem_raw["detail"]),
                openstack_request_id=(
                    str(problem_raw["openstack_request_id"])
                    if problem_raw.get("openstack_request_id")
                    else None
                ),
            )
            if problem_raw
            else None
        ),
    )
