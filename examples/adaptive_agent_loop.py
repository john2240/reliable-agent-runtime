"""Demonstrate adaptive planning without freezing a complete DAG up front.

The planner in this example is deterministic so the demo works without an API
key. A real LLM planner can emit the same ``ActionProposal`` objects after each
structured observation.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from reliable_agent_runtime.bootstrap import build_container
from reliable_agent_runtime.domain.enums import ApprovalDecision, RunStatus
from reliable_agent_runtime.domain.types import JsonObject
from reliable_agent_runtime.settings import Settings


@dataclass(frozen=True, slots=True)
class ActionProposal:
    id: str
    tool: str
    arguments: JsonObject
    description: str


@dataclass(slots=True)
class PlannerState:
    observations: dict[str, JsonObject] = field(default_factory=dict)


class RefundPlanner:
    """Small adaptive planner whose next action depends on fresh observations."""

    def next_action(self, state: PlannerState) -> ActionProposal | None:
        order = state.observations.get("read_order")
        if order is None:
            return ActionProposal(
                id="read_order",
                tool="retail.get_order",
                arguments={"order_id": "ord-1001"},
                description="Read fresh order state before proposing a mutation.",
            )

        if not bool(order["refundable"]):
            return None

        if "update_ticket" not in state.observations:
            return ActionProposal(
                id="update_ticket",
                tool="retail.update_ticket",
                arguments={
                    "ticket_id": "tic-1001",
                    "status": "processing",
                    "note": f"Refund processing for {order['order_id']}",
                },
                description="Record that the refund workflow has started.",
            )

        if "refund_order" not in state.observations:
            return ActionProposal(
                id="refund_order",
                tool="retail.issue_refund",
                arguments={
                    "order_id": str(order["order_id"]),
                    "amount_cents": int(order["total_cents"]),
                    "reason": "customer_request",
                },
                description="Issue the approved refund using fresh order data.",
            )

        if "notify_customer" not in state.observations:
            refund = state.observations["refund_order"]
            return ActionProposal(
                id="notify_customer",
                tool="retail.send_email",
                arguments={
                    "to": str(order["customer_email"]),
                    "subject": "Refund issued",
                    "body": f"Refund {refund['refund_id']} was issued.",
                },
                description="Notify the customer only after refund verification.",
            )

        return None


async def execute_proposal(
    *,
    container: Any,
    proposal: ActionProposal,
) -> JsonObject:
    result = await container.action_service.execute_action(
        objective="Refund an eligible order and notify the customer.",
        action_id=proposal.id,
        tool_name=proposal.tool,
        arguments=proposal.arguments,
        actor="adaptive-demo-agent",
        description=proposal.description,
        idempotency_key=f"adaptive-demo:{proposal.id}",
    )
    run = result.run

    if run.status is RunStatus.WAITING_APPROVAL:
        approval = (await container.run_service.list_approvals(run.id))[0]
        await container.run_service.decide_approval(
            approval_id=approval.id,
            decision=ApprovalDecision.APPROVE,
            actor="demo-manager",
            reason="order and refund policy verified",
        )
        run = await container.execution_engine.execute(run.id)

    if run.status is not RunStatus.SUCCEEDED or run.result is None:
        error = run.error.message if run.error else "unknown action failure"
        raise RuntimeError(f"action {proposal.id!r} failed: {error}")
    return run.result


async def main() -> None:
    database = Path("data/adaptive-demo.db")
    database.parent.mkdir(exist_ok=True)
    database.unlink(missing_ok=True)
    container = build_container(
        Settings(
            database_url=f"sqlite+pysqlite:///{database}",
            demo_refund_unknown_outcome_once=True,
        ),
    )
    await container.initialize()
    planner = RefundPlanner()
    state = PlannerState()

    try:
        for turn in range(1, 9):
            proposal = planner.next_action(state)
            if proposal is None:
                break
            output = await execute_proposal(container=container, proposal=proposal)
            state.observations[proposal.id] = output
            print(f"turn {turn}: {proposal.tool} -> {output}")
        else:
            raise RuntimeError("planner exceeded the configured turn limit")

        print(f"refunds created: {await container.retail_system.refund_count()}")
        print("adaptive workflow completed")
    finally:
        await container.close()


if __name__ == "__main__":
    asyncio.run(main())
