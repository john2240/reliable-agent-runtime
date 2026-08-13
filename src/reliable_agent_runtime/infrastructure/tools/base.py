"""Pydantic-backed typed tool adapter base class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import cast

from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from reliable_agent_runtime.domain.enums import VerificationOutcome
from reliable_agent_runtime.domain.errors import (
    CompensationNotSupportedError,
    ToolInputValidationError,
)
from reliable_agent_runtime.domain.models import (
    CheckResult,
    ToolContext,
    ToolResult,
    ToolSpec,
    VerificationResult,
)
from reliable_agent_runtime.domain.types import JsonObject


class PydanticTool[InputT: BaseModel, OutputT: BaseModel](ABC):
    """Keep validation at the adapter boundary and domain data JSON-safe."""

    input_model: type[InputT]
    output_model: type[OutputT]

    def __init__(self, spec: ToolSpec) -> None:
        self._spec = spec

    @property
    def spec(self) -> ToolSpec:
        return self._spec

    @property
    def input_schema(self) -> JsonObject:
        return cast(JsonObject, self.input_model.model_json_schema())

    @property
    def output_schema(self) -> JsonObject:
        return cast(JsonObject, self.output_model.model_json_schema())

    @property
    def supports_compensation(self) -> bool:
        return False

    async def validate_arguments(self, arguments: JsonObject) -> JsonObject:
        try:
            value = self.input_model.model_validate(arguments)
        except PydanticValidationError as exc:
            raise ToolInputValidationError(
                f"invalid arguments for tool {self.spec.name!r}",
                details={"errors": cast(object, exc.errors(include_url=False))},
            ) from exc
        return cast(JsonObject, value.model_dump(mode="json"))

    async def check_preconditions(
        self,
        context: ToolContext,
        arguments: JsonObject,
    ) -> CheckResult:
        value = self.input_model.model_validate(arguments)
        return await self.check_typed_preconditions(context, value)

    async def execute(
        self,
        context: ToolContext,
        arguments: JsonObject,
    ) -> ToolResult:
        value = self.input_model.model_validate(arguments)
        output = await self.execute_typed(context, value)
        return ToolResult(output=cast(JsonObject, output.model_dump(mode="json")))

    async def verify(
        self,
        context: ToolContext,
        arguments: JsonObject,
        result: ToolResult | None,
    ) -> VerificationResult:
        value = self.input_model.model_validate(arguments)
        return await self.verify_typed(context, value, result)

    async def compensate(
        self,
        context: ToolContext,
        arguments: JsonObject,
        result: ToolResult,
    ) -> ToolResult:
        del context, arguments, result
        raise CompensationNotSupportedError(
            f"tool {self.spec.name!r} does not support compensation",
        )

    async def check_typed_preconditions(
        self,
        context: ToolContext,
        arguments: InputT,
    ) -> CheckResult:
        del context, arguments
        return CheckResult.success()

    async def verify_typed(
        self,
        context: ToolContext,
        arguments: InputT,
        result: ToolResult | None,
    ) -> VerificationResult:
        del context, arguments
        if result is None:
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE,
                details="tool adapter cannot verify execution without a result",
            )
        return VerificationResult.confirmed(observed_output=result.output)

    @abstractmethod
    async def execute_typed(self, context: ToolContext, arguments: InputT) -> OutputT:
        """Execute using validated, typed arguments."""
