"""Run the complete approval and unknown-outcome recovery demo in-process."""

from __future__ import annotations

import asyncio
from pathlib import Path

from reliable_agent_runtime.bootstrap import build_container
from reliable_agent_runtime.domain.enums import ApprovalDecision
from reliable_agent_runtime.domain.models import ExecutionPlan, PlanStep
from reliable_agent_runtime.settings import Settings


def refund_plan() -> ExecutionPlan:
    return ExecutionPlan(
        id="refund_order",
        name="Reliable retail refund",
        steps=(
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
        ),
    )


async def main() -> None:
    database = Path("data/demo.db")
    database.parent.mkdir(exist_ok=True)
    database.unlink(missing_ok=True)
    container = build_container(
        Settings(
            database_url=f"sqlite+pysqlite:///{database}",
            demo_refund_unknown_outcome_once=True,
        ),
    )
    await container.initialize()
    try:
        created = await container.run_service.create_run(
            objective="Refund the order and notify the customer.",
            plan=refund_plan(),
            input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
            actor="demo-user",
            idempotency_key="refund-demo",
        )
        waiting = await container.execution_engine.execute(created.run.id)
        print(f"after first execution: {waiting.status}")

        approval = (await container.run_service.list_approvals(waiting.id))[0]
        await container.run_service.decide_approval(
            approval_id=approval.id,
            decision=ApprovalDecision.APPROVE,
            actor="demo-manager",
            reason="order and policy checked",
        )
        completed = await container.execution_engine.execute(waiting.id)
        events = await container.run_service.list_events(completed.id)

        print(f"final status: {completed.status}")
        print(f"refunds created: {await container.retail_system.refund_count()}")
        print("events:")
        for event in events:
            print(f"  {event.sequence:02d}  {event.event_type}")
    finally:
        await container.close()


if __name__ == "__main__":
    asyncio.run(main())
