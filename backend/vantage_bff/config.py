from __future__ import annotations

import os
from dataclasses import dataclass


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str = "development"
    adapter: str = "fake"
    store_backend: str = "memory"
    redis_url: str | None = None
    redis_key_prefix: str = "vantage"
    session_ttl_seconds: int = 3600
    cookie_secure: bool = True
    cookie_name: str = "vantage_session"
    auth_url: str | None = None
    interface: str = "public"
    default_region: str = "RegionOne"
    request_timeout_seconds: int = 15
    identity_source_timeout_seconds: float = 2.0
    scope_source_timeout_seconds: float = 1.0
    quota_source_timeout_seconds: float = 3.0
    instance_source_timeout_seconds: float = 3.0
    provisioning_source_timeout_seconds: float = 3.0
    openstack_sdk_thread_capacity: int = 8
    openstack_connection_cache_size: int = 256
    instance_cursor_ttl_seconds: int = 300
    instance_cursor_max_chains: int = 256
    instance_cursor_max_pages: int = 1000
    operation_terminal_ttl_seconds: int = 86400
    operation_max_records: int = 4096
    login_attempt_limit: int = 5
    login_attempt_window_seconds: int = 60
    quota_cache_ttl_seconds: int = 10
    quota_cache_max_entries: int = 2048
    shutdown_grace_seconds: float = 10.0
    metrics_enabled: bool = True

    def __post_init__(self) -> None:
        positive_values = {
            "session_ttl_seconds": self.session_ttl_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
            "identity_source_timeout_seconds": self.identity_source_timeout_seconds,
            "scope_source_timeout_seconds": self.scope_source_timeout_seconds,
            "quota_source_timeout_seconds": self.quota_source_timeout_seconds,
            "instance_source_timeout_seconds": self.instance_source_timeout_seconds,
            "provisioning_source_timeout_seconds": self.provisioning_source_timeout_seconds,
            "openstack_sdk_thread_capacity": self.openstack_sdk_thread_capacity,
            "openstack_connection_cache_size": self.openstack_connection_cache_size,
            "instance_cursor_ttl_seconds": self.instance_cursor_ttl_seconds,
            "instance_cursor_max_chains": self.instance_cursor_max_chains,
            "instance_cursor_max_pages": self.instance_cursor_max_pages,
            "operation_terminal_ttl_seconds": self.operation_terminal_ttl_seconds,
            "operation_max_records": self.operation_max_records,
            "login_attempt_limit": self.login_attempt_limit,
            "login_attempt_window_seconds": self.login_attempt_window_seconds,
            "quota_cache_ttl_seconds": self.quota_cache_ttl_seconds,
            "quota_cache_max_entries": self.quota_cache_max_entries,
            "shutdown_grace_seconds": self.shutdown_grace_seconds,
        }
        invalid = [name for name, value in positive_values.items() if value <= 0]
        if invalid:
            raise ValueError(f"Settings must be positive: {', '.join(invalid)}")
        if self.environment not in {"development", "test", "production"}:
            raise ValueError("environment must be development, test, or production")
        if self.store_backend not in {"memory", "redis"}:
            raise ValueError("store_backend must be memory or redis")
        if self.store_backend == "redis" and not self.redis_url:
            raise ValueError("VANTAGE_REDIS_URL is required when VANTAGE_STORE_BACKEND=redis")
        if self.environment == "production" and self.store_backend != "redis":
            raise ValueError("Production requires VANTAGE_STORE_BACKEND=redis")
        if self.environment == "production" and self.adapter != "openstack":
            raise ValueError("Production requires VANTAGE_ADAPTER=openstack")
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("Production requires secure session cookies")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            environment=os.getenv("VANTAGE_ENVIRONMENT", "development"),
            adapter=os.getenv("VANTAGE_ADAPTER", "fake"),
            store_backend=os.getenv("VANTAGE_STORE_BACKEND", "memory"),
            redis_url=os.getenv("VANTAGE_REDIS_URL"),
            redis_key_prefix=os.getenv("VANTAGE_REDIS_KEY_PREFIX", "vantage"),
            session_ttl_seconds=int(os.getenv("VANTAGE_SESSION_TTL_SECONDS", "3600")),
            cookie_secure=_boolean("VANTAGE_COOKIE_SECURE", True),
            auth_url=os.getenv("VANTAGE_OS_AUTH_URL"),
            interface=os.getenv("VANTAGE_OS_INTERFACE", "public"),
            default_region=os.getenv("VANTAGE_OS_REGION", "RegionOne"),
            request_timeout_seconds=int(os.getenv("VANTAGE_OS_TIMEOUT_SECONDS", "15")),
            identity_source_timeout_seconds=float(
                os.getenv("VANTAGE_IDENTITY_SOURCE_TIMEOUT_SECONDS", "2")
            ),
            scope_source_timeout_seconds=float(
                os.getenv("VANTAGE_SCOPE_SOURCE_TIMEOUT_SECONDS", "1")
            ),
            quota_source_timeout_seconds=float(
                os.getenv("VANTAGE_QUOTA_SOURCE_TIMEOUT_SECONDS", "3")
            ),
            instance_source_timeout_seconds=float(
                os.getenv("VANTAGE_INSTANCE_SOURCE_TIMEOUT_SECONDS", "3")
            ),
            provisioning_source_timeout_seconds=float(
                os.getenv("VANTAGE_PROVISIONING_SOURCE_TIMEOUT_SECONDS", "3")
            ),
            openstack_sdk_thread_capacity=int(
                os.getenv("VANTAGE_OPENSTACK_SDK_THREAD_CAPACITY", "8")
            ),
            openstack_connection_cache_size=int(
                os.getenv("VANTAGE_OPENSTACK_CONNECTION_CACHE_SIZE", "256")
            ),
            instance_cursor_ttl_seconds=int(
                os.getenv("VANTAGE_INSTANCE_CURSOR_TTL_SECONDS", "300")
            ),
            instance_cursor_max_chains=int(os.getenv("VANTAGE_INSTANCE_CURSOR_MAX_CHAINS", "256")),
            instance_cursor_max_pages=int(os.getenv("VANTAGE_INSTANCE_CURSOR_MAX_PAGES", "1000")),
            operation_terminal_ttl_seconds=int(
                os.getenv("VANTAGE_OPERATION_TERMINAL_TTL_SECONDS", "86400")
            ),
            operation_max_records=int(os.getenv("VANTAGE_OPERATION_MAX_RECORDS", "4096")),
            login_attempt_limit=int(os.getenv("VANTAGE_LOGIN_ATTEMPT_LIMIT", "5")),
            login_attempt_window_seconds=int(
                os.getenv("VANTAGE_LOGIN_ATTEMPT_WINDOW_SECONDS", "60")
            ),
            quota_cache_ttl_seconds=int(os.getenv("VANTAGE_QUOTA_CACHE_TTL_SECONDS", "10")),
            quota_cache_max_entries=int(os.getenv("VANTAGE_QUOTA_CACHE_MAX_ENTRIES", "2048")),
            shutdown_grace_seconds=float(os.getenv("VANTAGE_SHUTDOWN_GRACE_SECONDS", "10")),
            metrics_enabled=_boolean("VANTAGE_METRICS_ENABLED", True),
        )
