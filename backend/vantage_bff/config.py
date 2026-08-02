from __future__ import annotations

import os
from dataclasses import dataclass


def _boolean(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    adapter: str = "fake"
    session_ttl_seconds: int = 3600
    cookie_secure: bool = True
    cookie_name: str = "vantage_session"
    auth_url: str | None = None
    interface: str = "public"
    default_region: str = "RegionOne"
    request_timeout_seconds: int = 15
    quota_source_timeout_seconds: float = 3.0
    login_attempt_limit: int = 5
    login_attempt_window_seconds: int = 60

    def __post_init__(self) -> None:
        positive_values = {
            "session_ttl_seconds": self.session_ttl_seconds,
            "request_timeout_seconds": self.request_timeout_seconds,
            "quota_source_timeout_seconds": self.quota_source_timeout_seconds,
            "login_attempt_limit": self.login_attempt_limit,
            "login_attempt_window_seconds": self.login_attempt_window_seconds,
        }
        invalid = [name for name, value in positive_values.items() if value <= 0]
        if invalid:
            raise ValueError(f"Settings must be positive: {', '.join(invalid)}")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            adapter=os.getenv("VANTAGE_ADAPTER", "fake"),
            session_ttl_seconds=int(os.getenv("VANTAGE_SESSION_TTL_SECONDS", "3600")),
            cookie_secure=_boolean("VANTAGE_COOKIE_SECURE", True),
            auth_url=os.getenv("VANTAGE_OS_AUTH_URL"),
            interface=os.getenv("VANTAGE_OS_INTERFACE", "public"),
            default_region=os.getenv("VANTAGE_OS_REGION", "RegionOne"),
            request_timeout_seconds=int(os.getenv("VANTAGE_OS_TIMEOUT_SECONDS", "15")),
            quota_source_timeout_seconds=float(
                os.getenv("VANTAGE_QUOTA_SOURCE_TIMEOUT_SECONDS", "3")
            ),
            login_attempt_limit=int(os.getenv("VANTAGE_LOGIN_ATTEMPT_LIMIT", "5")),
            login_attempt_window_seconds=int(
                os.getenv("VANTAGE_LOGIN_ATTEMPT_WINDOW_SECONDS", "60")
            ),
        )
