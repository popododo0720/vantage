from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol, TypeVar

_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class CacheKey:
    user_id: str
    project_id: str
    region: str
    policy_scope: str
    service: str
    resource: str
    query: tuple[tuple[str, str], ...] = ()

    def digest(self) -> str:
        payload = json.dumps(
            {
                "user": self.user_id,
                "project": self.project_id,
                "region": self.region,
                "policy_scope": self.policy_scope,
                "service": self.service,
                "resource": self.resource,
                "query": self.query,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        return hashlib.sha256(payload).hexdigest()


class JsonCache(Protocol):
    async def get(self, key: CacheKey) -> Mapping[str, Any] | None: ...
    async def set(self, key: CacheKey, value: Mapping[str, Any], ttl_seconds: int) -> None: ...
    async def invalidate_policy_scope(self, policy_scope: str) -> None: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...


@dataclass(slots=True)
class _Entry:
    value: dict[str, Any]
    expires_at: float
    touched_at: float
    policy_scope: str


class MemoryJsonCache:
    def __init__(self, max_entries: int, clock: Callable[[], float] = monotonic) -> None:
        if max_entries <= 0:
            raise ValueError("Cache capacity must be positive")
        self._max_entries = max_entries
        self._clock = clock
        self._entries: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: CacheKey) -> Mapping[str, Any] | None:
        async with self._lock:
            now = self._clock()
            entry = self._entries.get(key.digest())
            if entry is None:
                return None
            if entry.expires_at <= now:
                self._entries.pop(key.digest(), None)
                return None
            entry.touched_at = now
            return dict(entry.value)

    async def set(self, key: CacheKey, value: Mapping[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Cache TTL must be positive")
        async with self._lock:
            digest = key.digest()
            if digest not in self._entries and len(self._entries) >= self._max_entries:
                oldest = min(self._entries, key=lambda item: self._entries[item].touched_at)
                self._entries.pop(oldest, None)
            now = self._clock()
            self._entries[digest] = _Entry(
                value=dict(value),
                expires_at=now + ttl_seconds,
                touched_at=now,
                policy_scope=key.policy_scope,
            )

    async def invalidate_policy_scope(self, policy_scope: str) -> None:
        async with self._lock:
            for digest, entry in tuple(self._entries.items()):
                if entry.policy_scope == policy_scope:
                    self._entries.pop(digest, None)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        return None


class CoalescingCache:
    """Coalesce identical misses in one worker while the backing cache shares results."""

    def __init__(self, backend: JsonCache) -> None:
        self._backend = backend
        self._inflight: dict[str, asyncio.Future[Mapping[str, Any]]] = {}
        self._lock = asyncio.Lock()

    async def get_or_load(
        self,
        key: CacheKey,
        loader: Callable[[], Awaitable[Mapping[str, Any]]],
        ttl_seconds: int,
    ) -> tuple[Mapping[str, Any], bool, bool]:
        cached = await self._backend.get(key)
        if cached is not None:
            return cached, True, False
        digest = key.digest()
        async with self._lock:
            task = self._inflight.get(digest)
            coalesced = task is not None
            if task is None:
                async def load_and_store() -> Mapping[str, Any]:
                    value = await loader()
                    await self._backend.set(key, value, ttl_seconds)
                    return value

                task = asyncio.ensure_future(load_and_store())
                self._inflight[digest] = task
                task.add_done_callback(lambda completed: self._completed(digest, completed))
        try:
            value = await asyncio.shield(task)
            return value, False, coalesced
        finally:
            if task.done():
                await self._forget(digest, task)

    async def _forget(
        self, digest: str, task: asyncio.Future[Mapping[str, Any]]
    ) -> None:
        async with self._lock:
            if self._inflight.get(digest) is task:
                self._inflight.pop(digest, None)

    def _completed(self, digest: str, task: asyncio.Future[Mapping[str, Any]]) -> None:
        if self._inflight.get(digest) is task:
            self._inflight.pop(digest, None)

    async def invalidate_policy_scope(self, policy_scope: str) -> None:
        await self._backend.invalidate_policy_scope(policy_scope)

    async def ping(self) -> bool:
        return await self._backend.ping()

    async def close(self) -> None:
        await self._backend.close()
