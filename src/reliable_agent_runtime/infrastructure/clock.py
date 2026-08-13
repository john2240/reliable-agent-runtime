"""Clock adapters."""

from datetime import UTC, datetime


class SystemClock:
    """Production wall clock."""

    @staticmethod
    def now() -> datetime:
        return datetime.now(tz=UTC)
