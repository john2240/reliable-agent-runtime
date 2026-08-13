"""Deterministic reliability acceptance scenarios for the demo adapters."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from reliable_agent_runtime.api.schemas import CreateRunRequest
from reliable_agent_runtime.bootstrap import build_container
from reliable_agent_runtime.domain.enums import ApprovalDecision, RunStatus
from reliable_agent_runtime.domain.errors import IdempotencyConflictError
from reliable_agent_runtime.settings import Settings


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    name: str
    passed: bool
    elapsed_ms: float
    evidence: dict[str, object]


def load_request() -> CreateRunRequest:
    payload = json.loads(Path("examples/retail_refund_plan.json").read_text())
    return CreateRunRequest.model_validate(payload)


async def unknown_outcome_recovery(root: Path) -> ScenarioResult:
    started = time.perf_counter()
    request = load_request()
    container = build_container(
        Settings(
            database_url=f"sqlite+pysqlite:///{root / 'unknown.db'}",
            demo_refund_unknown_outcome_once=True,
        ),
    )
    await container.initialize()
    try:
        created = await container.run_service.create_run(
            objective=request.objective,
            plan=request.plan.to_domain(),
            input_data=request.input,
            actor=request.actor,
        )
        waiting = await container.execution_engine.execute(created.run.id)
        approval = (await container.run_service.list_approvals(waiting.id))[0]
        await container.run_service.decide_approval(
            approval_id=approval.id,
            decision=ApprovalDecision.APPROVE,
            actor="acceptance-manager",
            reason="verified order and refund policy",
        )
        completed = await container.execution_engine.execute(waiting.id)
        events = await container.run_service.list_events(completed.id)
        recovery_events = [
            event for event in events if event.event_type.value == "tool.outcome_recovered"
        ]
        refund_count = await container.retail_system.refund_count()
        passed = (
            waiting.status is RunStatus.WAITING_APPROVAL
            and completed.status is RunStatus.SUCCEEDED
            and refund_count == 1
            and len(recovery_events) == 1
        )
        evidence: dict[str, object] = {
            "waiting_status": waiting.status.value,
            "final_status": completed.status.value,
            "refund_count": refund_count,
            "outcome_recovery_events": len(recovery_events),
        }
    finally:
        await container.close()
    return ScenarioResult(
        name="unknown_outcome_recovery_without_duplicate_refund",
        passed=passed,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        evidence=evidence,
    )


async def denied_approval_compensation(root: Path) -> ScenarioResult:
    started = time.perf_counter()
    request = load_request()
    container = build_container(
        Settings(database_url=f"sqlite+pysqlite:///{root / 'denied.db'}"),
    )
    await container.initialize()
    try:
        created = await container.run_service.create_run(
            objective=request.objective,
            plan=request.plan.to_domain(),
            input_data=request.input,
            actor=request.actor,
        )
        waiting = await container.execution_engine.execute(created.run.id)
        approval = (await container.run_service.list_approvals(waiting.id))[0]
        await container.run_service.decide_approval(
            approval_id=approval.id,
            decision=ApprovalDecision.DENY,
            actor="acceptance-manager",
            reason="refund not authorized",
        )
        failed = await container.execution_engine.execute(waiting.id)
        ticket = await container.retail_system.get_ticket("tic-1001")
        refund_count = await container.retail_system.refund_count()
        passed = (
            failed.status is RunStatus.FAILED_COMPENSATED
            and ticket is not None
            and ticket["status"] == "open"
            and refund_count == 0
        )
        evidence: dict[str, object] = {
            "final_status": failed.status.value,
            "ticket_status": ticket["status"] if ticket else None,
            "refund_count": refund_count,
        }
    finally:
        await container.close()
    return ScenarioResult(
        name="denied_approval_compensates_prior_write",
        passed=passed,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        evidence=evidence,
    )


async def create_idempotency(root: Path) -> ScenarioResult:
    started = time.perf_counter()
    request = load_request()
    container = build_container(
        Settings(database_url=f"sqlite+pysqlite:///{root / 'idempotency.db'}"),
    )
    await container.initialize()
    try:
        first = await container.run_service.create_run(
            objective=request.objective,
            plan=request.plan.to_domain(),
            input_data=request.input,
            actor=request.actor,
            idempotency_key="acceptance-create",
        )
        replay = await container.run_service.create_run(
            objective=request.objective,
            plan=request.plan.to_domain(),
            input_data=request.input,
            actor=request.actor,
            idempotency_key="acceptance-create",
        )
        conflict_detected = False
        try:
            await container.run_service.create_run(
                objective="different objective",
                plan=request.plan.to_domain(),
                input_data=request.input,
                actor=request.actor,
                idempotency_key="acceptance-create",
            )
        except IdempotencyConflictError:
            conflict_detected = True

        passed = (
            first.created
            and not replay.created
            and first.run.id == replay.run.id
            and conflict_detected
        )
        evidence: dict[str, object] = {
            "same_resource_on_replay": first.run.id == replay.run.id,
            "replay_created": replay.created,
            "payload_conflict_detected": conflict_detected,
        }
    finally:
        await container.close()
    return ScenarioResult(
        name="create_run_idempotency",
        passed=passed,
        elapsed_ms=round((time.perf_counter() - started) * 1000, 2),
        evidence=evidence,
    )


async def run_all() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="rar-acceptance-") as directory:
        root = Path(directory)
        scenarios = [
            await unknown_outcome_recovery(root),
            await denied_approval_compensation(root),
            await create_idempotency(root),
        ]
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "passed": all(scenario.passed for scenario in scenarios),
        "scenario_count": len(scenarios),
        "scenarios": [asdict(scenario) for scenario in scenarios],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = asyncio.run(run_all())
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
