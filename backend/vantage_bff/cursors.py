from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic


@dataclass(frozen=True, slots=True)
class CursorKey:
    scope_namespace: str
    resource: str
    query: tuple[tuple[str, str | None], ...]


@dataclass(frozen=True, slots=True)
class CursorLease:
    key: CursorKey
    generation: int
    page: int
    marker: str | None


@dataclass(slots=True)
class _CursorChain:
    generation: int
    markers: dict[int, str | None]
    expires_at: float
    touched_at: float


@dataclass(slots=True)
class _PendingReset:
    generation: int
    expires_at: float
    touched_at: float


class MemoryCursorStore:
    """Bounded, short-lived marker chains for one-based browser pagination."""

    def __init__(
        self,
        ttl_seconds: int,
        max_chains: int,
        max_pages: int,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if min(ttl_seconds, max_chains, max_pages) <= 0:
            raise ValueError("Cursor store limits must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_chains = max_chains
        self._max_pages = max_pages
        self._clock = clock
        self._chains: dict[CursorKey, _CursorChain] = {}
        self._pending_resets: dict[CursorKey, _PendingReset] = {}
        self._generation = 0
        self._lock = asyncio.Lock()

    async def acquire(self, key: CursorKey, page: int) -> CursorLease | None:
        async with self._lock:
            now = self._clock()
            self._purge_expired(now)
            if page < 1 or page > self._max_pages:
                return None
            if page == 1:
                self._generation += 1
                if key not in self._pending_resets:
                    self._evict_oldest_pending_if_full()
                pending = _PendingReset(
                    generation=self._generation,
                    expires_at=now + self._ttl_seconds,
                    touched_at=now,
                )
                self._pending_resets[key] = pending
                return CursorLease(
                    key=key,
                    generation=pending.generation,
                    page=page,
                    marker=None,
                )
            else:
                chain = self._chains.get(key)
                if chain is None or page not in chain.markers:
                    return None
                self._touch(chain, now)
            return CursorLease(
                key=key,
                generation=chain.generation,
                page=page,
                marker=chain.markers[page],
            )

    async def complete(
        self,
        lease: CursorLease,
        next_marker: str | None,
    ) -> tuple[int, ...] | None:
        async with self._lock:
            now = self._clock()
            self._purge_expired(now)
            if lease.page == 1:
                pending = self._pending_resets.get(lease.key)
                if pending is None or pending.generation != lease.generation:
                    return None
                if lease.key not in self._chains:
                    self._evict_oldest_if_full()
                markers: dict[int, str | None] = {1: None}
                if next_marker is not None and self._max_pages > 1:
                    markers[2] = next_marker
                self._chains[lease.key] = _CursorChain(
                    generation=lease.generation,
                    markers=markers,
                    expires_at=now + self._ttl_seconds,
                    touched_at=now,
                )
                self._pending_resets.pop(lease.key, None)
                return tuple(sorted(markers))

            chain = self._chains.get(lease.key)
            if chain is None or chain.generation != lease.generation:
                return None

            last_page_to_keep = lease.page
            if next_marker is not None and lease.page < self._max_pages:
                last_page_to_keep = lease.page + 1
                chain.markers[last_page_to_keep] = next_marker
            for page in tuple(chain.markers):
                if page > last_page_to_keep:
                    chain.markers.pop(page, None)
            self._touch(chain, now)
            return tuple(sorted(chain.markers))

    async def abandon(self, lease: CursorLease) -> None:
        if lease.page != 1:
            return
        async with self._lock:
            pending = self._pending_resets.get(lease.key)
            if pending is not None and pending.generation == lease.generation:
                self._pending_resets.pop(lease.key, None)

    async def invalidate(self, key: CursorKey) -> None:
        async with self._lock:
            self._chains.pop(key, None)
            self._pending_resets.pop(key, None)

    async def invalidate_namespace(self, scope_namespace: str) -> None:
        async with self._lock:
            for key in tuple(self._chains):
                if key.scope_namespace == scope_namespace:
                    self._chains.pop(key, None)
            for key in tuple(self._pending_resets):
                if key.scope_namespace == scope_namespace:
                    self._pending_resets.pop(key, None)

    def _purge_expired(self, now: float) -> None:
        for key, chain in tuple(self._chains.items()):
            if chain.expires_at <= now:
                self._chains.pop(key, None)
        for key, pending in tuple(self._pending_resets.items()):
            if pending.expires_at <= now:
                self._pending_resets.pop(key, None)

    def _evict_oldest_if_full(self) -> None:
        if len(self._chains) < self._max_chains:
            return
        oldest = min(self._chains, key=lambda key: self._chains[key].touched_at)
        self._chains.pop(oldest, None)

    def _evict_oldest_pending_if_full(self) -> None:
        if len(self._pending_resets) < self._max_chains:
            return
        oldest = min(
            self._pending_resets,
            key=lambda key: self._pending_resets[key].touched_at,
        )
        self._pending_resets.pop(oldest, None)

    def _touch(self, chain: _CursorChain, now: float) -> None:
        chain.touched_at = now
        chain.expires_at = now + self._ttl_seconds
