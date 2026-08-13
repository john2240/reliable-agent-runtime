"""Safe, non-evaluating template resolution for plan arguments."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from reliable_agent_runtime.domain.errors import TemplateResolutionError
from reliable_agent_runtime.domain.types import JsonObject, JsonValue

_FULL_TEMPLATE: Final[re.Pattern[str]] = re.compile(r"^\$\{([a-zA-Z0-9_.-]+)}$")
_INLINE_TEMPLATE: Final[re.Pattern[str]] = re.compile(r"\$\{([a-zA-Z0-9_.-]+)}")


@dataclass(frozen=True, slots=True)
class TemplateResolver:
    """Resolve `${input.x}` and `${steps.id.output.y}` without `eval`."""

    def resolve(self, value: JsonValue, context: JsonObject) -> JsonValue:
        """Recursively resolve templates while preserving native JSON types."""

        if isinstance(value, dict):
            return {key: self.resolve(item, context) for key, item in value.items()}
        if isinstance(value, list):
            return [self.resolve(item, context) for item in value]
        if not isinstance(value, str):
            return value

        full_match = _FULL_TEMPLATE.fullmatch(value)
        if full_match:
            return self._lookup(full_match.group(1), context)

        def replace(match: re.Match[str]) -> str:
            resolved = self._lookup(match.group(1), context)
            if isinstance(resolved, (dict, list)):
                raise TemplateResolutionError(
                    "object and array values cannot be interpolated into strings",
                    details={"path": match.group(1)},
                )
            return "" if resolved is None else str(resolved)

        return _INLINE_TEMPLATE.sub(replace, value)

    def resolve_arguments(self, arguments: JsonObject, context: JsonObject) -> JsonObject:
        """Resolve a step argument object and assert the result remains an object."""

        resolved = self.resolve(arguments, context)
        if not isinstance(resolved, dict):
            raise TemplateResolutionError("resolved arguments must be a JSON object")
        return resolved

    @staticmethod
    def _lookup(path: str, context: JsonObject) -> JsonValue:
        current: JsonValue = context
        for segment in path.split("."):
            if not isinstance(current, dict) or segment not in current:
                raise TemplateResolutionError(
                    f"template path {path!r} does not exist",
                    details={"path": path, "missing_segment": segment},
                )
            current = current[segment]
        return current
