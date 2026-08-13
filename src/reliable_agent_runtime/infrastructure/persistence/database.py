"""Database engine and lifecycle management."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from reliable_agent_runtime.infrastructure.persistence.models import Base


class Database:
    """Own the SQLAlchemy engine and short-lived session factory."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._ensure_sqlite_directory(url)

        engine_kwargs: dict[str, object] = {
            "pool_pre_ping": True,
            "future": True,
        }
        if url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if ":memory:" in url:
                engine_kwargs["poolclass"] = StaticPool

        self.engine: Engine = create_engine(url, **engine_kwargs)
        self.sessions = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )
        if url.startswith("sqlite"):
            self._configure_sqlite(self.engine)

    async def initialize(self) -> None:
        await asyncio.to_thread(Base.metadata.create_all, self.engine)

    async def close(self) -> None:
        await asyncio.to_thread(self.engine.dispose)

    async def ping(self) -> bool:
        def _ping() -> bool:
            with self.engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            return True

        try:
            return await asyncio.to_thread(_ping)
        except Exception:
            return False

    @staticmethod
    def _ensure_sqlite_directory(url: str) -> None:
        prefix = "sqlite+pysqlite:///"
        if not url.startswith(prefix) or ":memory:" in url:
            return
        path = Path(url.removeprefix(prefix))
        if path.parent != Path("."):
            path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _configure_sqlite(engine: Engine) -> None:
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(
            dbapi_connection: Any,
            connection_record: Any,
        ) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            if ":memory:" not in str(engine.url):
                cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()
