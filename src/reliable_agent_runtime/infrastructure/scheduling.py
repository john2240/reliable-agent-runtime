"""Scheduling adapters."""

from __future__ import annotations

import asyncio


class AsyncioSleeper:
    """Production retry delay backed by the event loop."""

    @staticmethod
    async def sleep(seconds: float) -> None:
        await asyncio.sleep(seconds)
