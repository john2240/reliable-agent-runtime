"""Typed tool adapters that expose the retail service to the runtime."""

from reliable_agent_runtime.domain.enums import ToolEffect, VerificationOutcome
from reliable_agent_runtime.domain.errors import PermanentToolError
from reliable_agent_runtime.domain.models import (
    CheckResult,
    ToolContext,
    ToolResult,
    ToolSpec,
    VerificationResult,
)
from reliable_agent_runtime.domain.types import JsonObject
from reliable_agent_runtime.infrastructure.tools.base import PydanticTool
from reliable_agent_runtime.infrastructure.tools.retail.schemas import (
    EmailOutput,
    GetOrderInput,
    IssueRefundInput,
    OrderOutput,
    RefundOutput,
    SendEmailInput,
    TicketOutput,
    UpdateTicketInput,
)
from reliable_agent_runtime.infrastructure.tools.retail.system import RetailSystem


class GetOrderTool(PydanticTool[GetOrderInput, OrderOutput]):
    input_model = GetOrderInput
    output_model = OrderOutput

    def __init__(self, system: RetailSystem) -> None:
        super().__init__(
            ToolSpec(
                name="retail.get_order",
                description="Read the current order state.",
                effect=ToolEffect.READ,
                idempotent=True,
                tags=("retail", "read"),
            ),
        )
        self._system = system

    async def execute_typed(
        self,
        context: ToolContext,
        arguments: GetOrderInput,
    ) -> OrderOutput:
        del context
        order = await self._system.get_order(arguments.order_id)
        if order is None:
            raise PermanentToolError(
                f"order {arguments.order_id!r} does not exist",
                details={"order_id": arguments.order_id},
            )
        return OrderOutput.model_validate(order)


class UpdateTicketTool(PydanticTool[UpdateTicketInput, TicketOutput]):
    input_model = UpdateTicketInput
    output_model = TicketOutput

    def __init__(self, system: RetailSystem) -> None:
        super().__init__(
            ToolSpec(
                name="retail.update_ticket",
                description="Update a support ticket; the change can be compensated.",
                effect=ToolEffect.WRITE,
                idempotent=True,
                tags=("retail", "write", "compensatable"),
            ),
        )
        self._system = system

    @property
    def supports_compensation(self) -> bool:
        return True

    async def check_typed_preconditions(
        self,
        context: ToolContext,
        arguments: UpdateTicketInput,
    ) -> CheckResult:
        del context
        ticket = await self._system.get_ticket(arguments.ticket_id)
        if ticket is None:
            return CheckResult(
                passed=False,
                reason=f"ticket {arguments.ticket_id!r} does not exist",
                details={"ticket_id": arguments.ticket_id},
            )
        return CheckResult.success()

    async def execute_typed(
        self,
        context: ToolContext,
        arguments: UpdateTicketInput,
    ) -> TicketOutput:
        output = await self._system.update_ticket(
            idempotency_key=context.idempotency_key,
            ticket_id=arguments.ticket_id,
            status=arguments.status,
            note=arguments.note,
        )
        return TicketOutput.model_validate(output)

    async def verify_typed(
        self,
        context: ToolContext,
        arguments: UpdateTicketInput,
        result: ToolResult | None,
    ) -> VerificationResult:
        del arguments, result
        observed = await self._system.get_ticket_change(context.idempotency_key)
        if observed is None:
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED_NOT_APPLIED,
                details="ticket change was not applied",
            )
        return VerificationResult.confirmed(
            details="ticket change exists for the idempotency key",
            observed_output=observed,
        )

    async def compensate(
        self,
        context: ToolContext,
        arguments: JsonObject,
        result: ToolResult,
    ) -> ToolResult:
        del context, arguments
        change_id = result.output.get("change_id")
        if not isinstance(change_id, str):
            raise PermanentToolError("ticket result is missing change_id")
        restored = await self._system.compensate_ticket_change(change_id)
        return ToolResult(output=restored, metadata={"compensated": True})


class IssueRefundTool(PydanticTool[IssueRefundInput, RefundOutput]):
    input_model = IssueRefundInput
    output_model = RefundOutput

    def __init__(self, system: RetailSystem) -> None:
        super().__init__(
            ToolSpec(
                name="retail.issue_refund",
                description=(
                    "Issue an irreversible refund with provider-side idempotency and "
                    "postcondition verification."
                ),
                effect=ToolEffect.IRREVERSIBLE,
                idempotent=True,
                timeout_seconds=5.0,
                max_attempts=3,
                tags=("retail", "payment", "irreversible"),
            ),
        )
        self._system = system

    async def check_typed_preconditions(
        self,
        context: ToolContext,
        arguments: IssueRefundInput,
    ) -> CheckResult:
        return await self._system.check_refund_preconditions(
            idempotency_key=context.idempotency_key,
            order_id=arguments.order_id,
            amount_cents=arguments.amount_cents,
        )

    async def execute_typed(
        self,
        context: ToolContext,
        arguments: IssueRefundInput,
    ) -> RefundOutput:
        refund = await self._system.issue_refund(
            idempotency_key=context.idempotency_key,
            order_id=arguments.order_id,
            amount_cents=arguments.amount_cents,
        )
        return RefundOutput.model_validate(refund)

    async def verify_typed(
        self,
        context: ToolContext,
        arguments: IssueRefundInput,
        result: ToolResult | None,
    ) -> VerificationResult:
        del arguments, result
        observed = await self._system.get_refund_by_key(context.idempotency_key)
        if observed is None:
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED_NOT_APPLIED,
                details="no refund exists for the idempotency key",
            )
        return VerificationResult.confirmed(
            details="refund exists for the idempotency key",
            observed_output=observed,
        )


class SendEmailTool(PydanticTool[SendEmailInput, EmailOutput]):
    input_model = SendEmailInput
    output_model = EmailOutput

    def __init__(self, system: RetailSystem) -> None:
        super().__init__(
            ToolSpec(
                name="retail.send_email",
                description="Send an idempotent customer notification.",
                effect=ToolEffect.WRITE,
                idempotent=True,
                tags=("retail", "notification"),
            ),
        )
        self._system = system

    async def execute_typed(
        self,
        context: ToolContext,
        arguments: SendEmailInput,
    ) -> EmailOutput:
        output = await self._system.send_email(
            idempotency_key=context.idempotency_key,
            to=arguments.to,
            subject=arguments.subject,
            body=arguments.body,
        )
        return EmailOutput.model_validate(output)

    async def verify_typed(
        self,
        context: ToolContext,
        arguments: SendEmailInput,
        result: ToolResult | None,
    ) -> VerificationResult:
        del arguments, result
        observed = await self._system.get_email_by_key(context.idempotency_key)
        if observed is None:
            return VerificationResult(
                outcome=VerificationOutcome.CONFIRMED_NOT_APPLIED,
                details="email was not sent for the idempotency key",
            )
        return VerificationResult.confirmed(
            details="email exists for the idempotency key",
            observed_output=observed,
        )


def build_retail_tools(system: RetailSystem) -> tuple[PydanticTool, ...]:
    """Build the demo tool set in a stable order."""

    return (
        GetOrderTool(system),
        UpdateTicketTool(system),
        IssueRefundTool(system),
        SendEmailTool(system),
    )
