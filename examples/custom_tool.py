"""Minimal example of a typed, verifiable tool adapter."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from reliable_agent_runtime.domain.enums import ToolEffect, VerificationOutcome
from reliable_agent_runtime.domain.models import (
    ToolContext,
    ToolResult,
    ToolSpec,
    VerificationResult,
)
from reliable_agent_runtime.infrastructure.tools.base import PydanticTool


class CreateCaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=500)


class CreateCaseOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    status: str


class CaseGateway:
    """Example external-system gateway with provider-side idempotency."""

    def __init__(self) -> None:
        self._by_key: dict[str, CreateCaseOutput] = {}

    async def create(
        self,
        *,
        idempotency_key: str,
        customer_id: str,
        summary: str,
    ) -> CreateCaseOutput:
        del customer_id, summary
        return self._by_key.setdefault(
            idempotency_key,
            CreateCaseOutput(case_id=f"case_{len(self._by_key) + 1}", status="open"),
        )

    async def find_by_key(self, idempotency_key: str) -> CreateCaseOutput | None:
        return self._by_key.get(idempotency_key)


class CreateCaseTool(PydanticTool[CreateCaseInput, CreateCaseOutput]):
    """A write tool that can recover after response loss."""

    input_model = CreateCaseInput
    output_model = CreateCaseOutput

    def __init__(self, gateway: CaseGateway) -> None:
        super().__init__(
            ToolSpec(
                name="crm.create_case",
                description="Create a customer support case.",
                effect=ToolEffect.WRITE,
                idempotent=True,
                tags=("crm", "write"),
            ),
        )
        self._gateway = gateway

    async def execute_typed(
        self,
        context: ToolContext,
        arguments: CreateCaseInput,
    ) -> CreateCaseOutput:
        return await self._gateway.create(
            idempotency_key=context.idempotency_key,
            customer_id=arguments.customer_id,
            summary=arguments.summary,
        )

    async def verify_typed(
        self,
        context: ToolContext,
        arguments: CreateCaseInput,
        result: ToolResult | None,
    ) -> VerificationResult:
        del arguments, result
        observed = await self._gateway.find_by_key(context.idempotency_key)
        if observed is None:
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED_NOT_APPLIED,
                details="no case exists for the idempotency key",
            )
        return VerificationResult.confirmed(observed_output=observed.model_dump())
