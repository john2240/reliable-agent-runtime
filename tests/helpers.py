"""Shared test builders."""

from reliable_agent_runtime.domain.models import ExecutionPlan, PlanStep


def refund_plan(*, include_notification: bool = True) -> ExecutionPlan:
    steps = [
        PlanStep(
            id="read_order",
            tool_name="retail.get_order",
            arguments={"order_id": "${input.order_id}"},
        ),
        PlanStep(
            id="update_ticket",
            tool_name="retail.update_ticket",
            depends_on=("read_order",),
            arguments={
                "ticket_id": "${input.ticket_id}",
                "status": "processing",
                "note": "Refund processing for ${steps.read_order.output.order_id}",
            },
        ),
        PlanStep(
            id="refund",
            tool_name="retail.issue_refund",
            depends_on=("read_order", "update_ticket"),
            arguments={
                "order_id": "${input.order_id}",
                "amount_cents": "${steps.read_order.output.total_cents}",
                "reason": "customer_request",
            },
        ),
    ]
    if include_notification:
        steps.append(
            PlanStep(
                id="notify",
                tool_name="retail.send_email",
                depends_on=("refund",),
                arguments={
                    "to": "${steps.read_order.output.customer_email}",
                    "subject": "Refund issued",
                    "body": "Refund ${steps.refund.output.refund_id} was issued.",
                },
            ),
        )
    return ExecutionPlan(
        id="refund_order",
        name="Refund an eligible order and update support state",
        steps=tuple(steps),
        compensate_on_failure=True,
    )


def refund_api_payload() -> dict:
    plan = refund_plan()
    return {
        "objective": "Refund an eligible order and notify the customer.",
        "actor": "test-user",
        "input": {"order_id": "ord-1001", "ticket_id": "tic-1001"},
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "compensate_on_failure": plan.compensate_on_failure,
            "steps": [
                {
                    "id": step.id,
                    "tool": step.tool_name,
                    "arguments": step.arguments,
                    "depends_on": list(step.depends_on),
                    "description": step.description,
                }
                for step in plan.steps
            ],
        },
    }
