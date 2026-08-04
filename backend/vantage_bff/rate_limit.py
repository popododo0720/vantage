from __future__ import annotations

import asyncio
import secrets
from collections import defaultdict, deque
from collections.abc import Callable
from time import monotonic
from typing import Protocol


class LoginLimiter(Protocol):
    async def reserve(self, key: str) -> str | None: ...
    async def release(self, key: str, reservation: str) -> None: ...
    async def succeeded(self, key: str) -> None: ...


class LoginRateLimiter:
    """Small per-process limiter for the authentication boundary.

    Deployments with multiple BFF processes must replace this with a shared,
    atomic implementation. The key is deliberately ephemeral and never logged.
    """

    def __init__(
        self,
        limit: int,
        window_seconds: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._clock = clock
        self._attempts: dict[str, deque[tuple[float, str]]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def reserve(self, key: str) -> str | None:
        async with self._lock:
            attempts = self._active_attempts(key)
            if len(attempts) >= self._limit:
                return None
            reservation = secrets.token_urlsafe(16)
            attempts.append((self._clock(), reservation))
            return reservation

    async def release(self, key: str, reservation: str) -> None:
        async with self._lock:
            attempts = self._active_attempts(key)
            remaining = deque(item for item in attempts if item[1] != reservation)
            if remaining:
                self._attempts[key] = remaining
            else:
                self._attempts.pop(key, None)

    async def succeeded(self, key: str) -> None:
        async with self._lock:
            self._attempts.pop(key, None)

    def _active_attempts(self, key: str) -> deque[tuple[float, str]]:
        attempts = self._attempts[key]
        threshold = self._clock() - self._window_seconds
        while attempts and attempts[0][0] <= threshold:
            attempts.popleft()
        return attempts
