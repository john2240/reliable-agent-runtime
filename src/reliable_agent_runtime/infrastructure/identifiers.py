"""Identifier generation adapters."""

from __future__ import annotations

import uuid


class UuidIdGenerator:
    """Generate URL-safe prefixed UUID identifiers."""

    _namespace = uuid.UUID("d61fa71e-bb65-4ea0-9864-64497f49be8f")

    @staticmethod
    def new(prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def deterministic(self, prefix: str, key: str) -> str:
        value = uuid.uuid5(self._namespace, f"{prefix}:{key}")
        return f"{prefix}_{value.hex}"
