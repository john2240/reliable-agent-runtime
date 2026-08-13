"""Pytest fixtures."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio

from reliable_agent_runtime.bootstrap import AppContainer, build_container
from reliable_agent_runtime.settings import Settings


@pytest_asyncio.fixture
async def container(tmp_path: Path) -> AsyncIterator[AppContainer]:
    runtime = build_container(
        Settings(database_url=f"sqlite+pysqlite:///{tmp_path / 'runtime.db'}"),
    )
    await runtime.initialize()
    try:
        yield runtime
    finally:
        await runtime.close()
