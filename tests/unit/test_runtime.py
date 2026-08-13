from __future__ import annotations

from pathlib import Path

import pytest

from reliable_agent_runtime.bootstrap import build_container
from reliable_agent_runtime.domain.enums import ApprovalDecision, RunStatus, StepStatus
from reliable_agent_runtime.domain.errors import IdempotencyConflictError
from reliable_agent_runtime.domain.models import ExecutionPlan, PlanStep
from reliable_agent_runtime.settings import Settings
from tests.helpers import refund_plan


@pytest.mark.asyncio
async def test_irreversible_step_pauses_for_approval(container) -> None:
    created = await container.run_service.create_run(
        objective="Refund the order.",
        plan=refund_plan(include_notification=False),
        input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
        actor="tester",
    )

    run = await container.execution_engine.execute(created.run.id)

    assert run.status is RunStatus.WAITING_APPROVAL
    assert run.step_states["read_order"].status is StepStatus.SUCCEEDED
    assert run.step_states["update_ticket"].status is StepStatus.SUCCEEDED
    assert run.step_states["refund"].status is StepStatus.WAITING_APPROVAL
    approvals = await container.run_service.list_approvals(run.id)
    assert len(approvals) == 1
    assert approvals[0].tool_name == "retail.issue_refund"


@pytest.mark.asyncio
async def test_unknown_outcome_is_verified_without_duplicate_refund(tmp_path: Path) -> None:
    container = build_container(
        Settings(
            database_url=f"sqlite+pysqlite:///{tmp_path / 'unknown-outcome.db'}",
            demo_refund_unknown_outcome_once=True,
        ),
    )
    await container.initialize()
    try:
        created = await container.run_service.create_run(
            objective="Refund and notify.",
            plan=refund_plan(),
            input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
            actor="tester",
        )
        waiting = await container.execution_engine.execute(created.run.id)
        approval = (await container.run_service.list_approvals(waiting.id))[0]
        await container.run_service.decide_approval(
            approval_id=approval.id,
            decision=ApprovalDecision.APPROVE,
            actor="manager",
            reason="policy checked",
        )

        completed = await container.execution_engine.execute(waiting.id)

        assert completed.status is RunStatus.SUCCEEDED
        assert await container.retail_system.refund_count() == 1
        events = await container.run_service.list_events(completed.id)
        assert any(event.event_type.value == "tool.outcome_recovered" for event in events)
    finally:
        await container.close()


@pytest.mark.asyncio
async def test_denied_approval_compensates_previous_write(container) -> None:
    created = await container.run_service.create_run(
        objective="Refund the order.",
        plan=refund_plan(include_notification=False),
        input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
        actor="tester",
    )
    waiting = await container.execution_engine.execute(created.run.id)
    approval = (await container.run_service.list_approvals(waiting.id))[0]
    await container.run_service.decide_approval(
        approval_id=approval.id,
        decision=ApprovalDecision.DENY,
        actor="manager",
        reason="refund is not authorized",
    )

    failed = await container.execution_engine.execute(waiting.id)

    assert failed.status is RunStatus.FAILED_COMPENSATED
    assert failed.step_states["update_ticket"].status is StepStatus.COMPENSATED
    ticket = await container.retail_system.get_ticket("tic-1001")
    assert ticket is not None
    assert ticket["status"] == "open"
    assert await container.retail_system.refund_count() == 0


@pytest.mark.asyncio
async def test_create_run_idempotency_detects_payload_conflict(container) -> None:
    first = await container.run_service.create_run(
        objective="First objective",
        plan=refund_plan(include_notification=False),
        input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
        actor="tester",
        idempotency_key="same-key",
    )
    replay = await container.run_service.create_run(
        objective="First objective",
        plan=refund_plan(include_notification=False),
        input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
        actor="tester",
        idempotency_key="same-key",
    )

    assert replay.created is False
    assert replay.run.id == first.run.id

    with pytest.raises(IdempotencyConflictError):
        await container.run_service.create_run(
            objective="Different objective",
            plan=refund_plan(include_notification=False),
            input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
            actor="tester",
            idempotency_key="same-key",
        )


@pytest.mark.asyncio
async def test_unknown_tool_is_recorded_as_run_failure(container) -> None:
    plan = ExecutionPlan(
        id="unknown_tool_plan",
        name="Unknown tool plan",
        steps=(
            PlanStep(id="missing", tool_name="missing.tool", arguments={}),
        ),
    )
    created = await container.run_service.create_run(
        objective="Call an unknown tool.",
        plan=plan,
        input_data={},
        actor="tester",
    )

    failed = await container.execution_engine.execute(created.run.id)

    assert failed.status is RunStatus.FAILED
    assert failed.error is not None
    assert failed.error.code == "tool_not_found"


@pytest.mark.asyncio
async def test_precondition_failure_compensates_prior_write(container) -> None:
    plan = refund_plan(include_notification=False)
    invalid_steps = tuple(
        PlanStep(
            id=step.id,
            tool_name=step.tool_name,
            arguments=(
                {**step.arguments, "amount_cents": 1}
                if step.id == "refund"
                else step.arguments
            ),
            depends_on=step.depends_on,
            description=step.description,
        )
        for step in plan.steps
    )
    invalid_plan = ExecutionPlan(
        id="refund_wrong_amount",
        name="Refund with a stale amount",
        steps=invalid_steps,
    )
    created = await container.run_service.create_run(
        objective="Refund with an invalid amount.",
        plan=invalid_plan,
        input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
        actor="tester",
    )

    failed = await container.execution_engine.execute(created.run.id)

    assert failed.status is RunStatus.FAILED_COMPENSATED
    assert failed.error is not None
    assert failed.error.code == "precondition_failed"
    assert failed.step_states["update_ticket"].status is StepStatus.COMPENSATED
    ticket = await container.retail_system.get_ticket("tic-1001")
    assert ticket is not None
    assert ticket["status"] == "open"
    assert await container.retail_system.refund_count() == 0


@pytest.mark.asyncio
async def test_reexecuting_succeeded_run_is_observationally_idempotent(container) -> None:
    created = await container.run_service.create_run(
        objective="Refund the order.",
        plan=refund_plan(include_notification=False),
        input_data={"order_id": "ord-1001", "ticket_id": "tic-1001"},
        actor="tester",
    )
    waiting = await container.execution_engine.execute(created.run.id)
    approval = (await container.run_service.list_approvals(waiting.id))[0]
    await container.run_service.decide_approval(
        approval_id=approval.id,
        decision=ApprovalDecision.APPROVE,
        actor="manager",
        reason="approved",
    )
    completed = await container.execution_engine.execute(waiting.id)
    version = completed.version
    events_before = await container.run_service.list_events(completed.id)

    replay = await container.execution_engine.execute(completed.id)
    events_after = await container.run_service.list_events(completed.id)

    assert replay.status is RunStatus.SUCCEEDED
    assert replay.version == version
    assert events_after == events_before
    assert await container.retail_system.refund_count() == 1
