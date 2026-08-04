from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from vantage_bff.cache import CoalescingCache, MemoryJsonCache
from vantage_bff.config import Settings
from vantage_bff.cursors import CursorStore, MemoryCursorStore
from vantage_bff.operations import MemoryOperationStore, OperationStore
from vantage_bff.rate_limit import LoginLimiter, LoginRateLimiter
from vantage_bff.sessions import MemorySessionStore, SessionStore


@dataclass(slots=True)
class PlatformResources:
    sessions: SessionStore
    cursors: CursorStore
    operations: OperationStore
    login_limiter: LoginLimiter
    quota_cache: CoalescingCache
    shared_dependency: Any | None = None

    async def ready(self) -> bool:
        if self.shared_dependency is None:
            return True
        return bool(await self.shared_dependency.ping())

    async def close(self) -> None:
        await self.quota_cache.close()
        if self.shared_dependency is not None:
            await self.shared_dependency.close()


def build_platform(settings: Settings) -> PlatformResources:
    if settings.store_backend == "memory":
        return PlatformResources(
            sessions=MemorySessionStore(),
            cursors=MemoryCursorStore(
                settings.instance_cursor_ttl_seconds,
                settings.instance_cursor_max_chains,
                settings.instance_cursor_max_pages,
            ),
            operations=MemoryOperationStore(
                terminal_ttl_seconds=settings.operation_terminal_ttl_seconds,
                max_records=settings.operation_max_records,
            ),
            login_limiter=LoginRateLimiter(
                settings.login_attempt_limit,
                settings.login_attempt_window_seconds,
            ),
            quota_cache=CoalescingCache(MemoryJsonCache(settings.quota_cache_max_entries)),
        )

    if settings.redis_url is None:  # guarded by Settings, keeps narrowing explicit
        raise RuntimeError("Redis URL is required")
    from vantage_bff.redis_backend import (
        RedisCursorStore,
        RedisJsonCache,
        RedisLoginRateLimiter,
        RedisOperationStore,
        RedisResources,
        RedisSessionStore,
        create_redis,
    )

    redis = create_redis(settings.redis_url)
    prefix = settings.redis_key_prefix
    shared = RedisResources(redis)
    return PlatformResources(
        sessions=RedisSessionStore(redis, prefix),
        cursors=RedisCursorStore(
            redis,
            prefix,
            settings.instance_cursor_ttl_seconds,
            settings.instance_cursor_max_pages,
        ),
        operations=RedisOperationStore(redis, prefix, settings.operation_terminal_ttl_seconds),
        login_limiter=RedisLoginRateLimiter(
            redis,
            prefix,
            settings.login_attempt_limit,
            settings.login_attempt_window_seconds,
        ),
        quota_cache=CoalescingCache(RedisJsonCache(redis, prefix)),
        shared_dependency=shared,
    )
