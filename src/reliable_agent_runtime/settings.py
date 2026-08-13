"""Environment-backed application settings without global side effects."""

from __future__ import annotations

import os
from dataclasses import dataclass


def _as_bool(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime configuration loaded explicitly at the composition root."""

    app_name: str = "Reliable Agent Runtime"
    environment: str = "development"
    database_url: str = "sqlite+pysqlite:///./data/reliable_agent_runtime.db"
    api_key: str | None = None
    log_level: str = "INFO"
    cors_origins: tuple[str, ...] = ()
    demo_refund_unknown_outcome_once: bool = False

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        origins = tuple(
            origin.strip()
            for origin in os.getenv("RAR_CORS_ORIGINS", "").split(",")
            if origin.strip()
        )
        return cls(
            app_name=os.getenv("RAR_APP_NAME", defaults.app_name),
            environment=os.getenv("RAR_ENVIRONMENT", defaults.environment),
            database_url=os.getenv("RAR_DATABASE_URL", defaults.database_url),
            api_key=os.getenv("RAR_API_KEY") or None,
            log_level=os.getenv("RAR_LOG_LEVEL", defaults.log_level).upper(),
            cors_origins=origins,
            demo_refund_unknown_outcome_once=_as_bool(
                os.getenv("RAR_DEMO_REFUND_UNKNOWN_OUTCOME_ONCE"),
            ),
        )
