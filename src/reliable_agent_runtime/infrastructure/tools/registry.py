"""Concrete in-memory tool registry."""

from __future__ import annotations

from reliable_agent_runtime.application.ports import Tool
from reliable_agent_runtime.domain.errors import ToolNotFoundError


class InMemoryToolRegistry:
    """Register immutable tool adapters by unique name."""

    def __init__(self, tools: tuple[Tool, ...] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> None:
        if tool.spec.name in self._tools:
            raise ValueError(f"tool {tool.spec.name!r} is already registered")
        self._tools[tool.spec.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(
                f"tool {name!r} is not registered",
                details={"tool_name": name},
            ) from exc

    def list(self) -> tuple[Tool, ...]:
        return tuple(self._tools[name] for name in sorted(self._tools))
