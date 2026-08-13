from __future__ import annotations

import pytest

from reliable_agent_runtime.domain.errors import ToolNotFoundError
from reliable_agent_runtime.infrastructure.tools.registry import InMemoryToolRegistry
from reliable_agent_runtime.infrastructure.tools.retail import GetOrderTool, RetailSystem


def test_registry_rejects_duplicate_tool_names() -> None:
    system = RetailSystem()
    tool = GetOrderTool(system)
    registry = InMemoryToolRegistry((tool,))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(GetOrderTool(system))


def test_registry_raises_typed_not_found_error() -> None:
    registry = InMemoryToolRegistry()

    with pytest.raises(ToolNotFoundError):
        registry.get("missing.tool")
