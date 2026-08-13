"""In-process run locking.

Optimistic database versions remain the final concurrency guard. This adapter
only avoids duplicate work inside one application process.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass


@dataclass(slots=True)
class _LockEntry:
    lock: asyncio.Lock
    users: int = 0


class InMemoryRunLockManager:
    """Reference-counted per-run asyncio locks."""

    def __init__(self) -> None:
        self._entries: dict[str, _LockEntry] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, run_id: str) -> AsyncIterator[None]:
        async with self._guard:
            entry = self._entries.setdefault(run_id, _LockEntry(lock=asyncio.Lock()))
            entry.users += 1

        try:
            async with entry.lock:
                yield
        finally:
            async with self._guard:
                entry.users -= 1
                if entry.users == 0 and not entry.lock.locked():
                    self._entries.pop(run_id, None)
