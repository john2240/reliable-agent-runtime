"""Run-level orchestration for reliable long-horizon agent execution."""

from __future__ import annotations

from dataclasses import dataclass

from reliable_agent_runtime.application.events import EventFactory
from reliable_agent_runtime.application.execution.approvals import ApprovalCoordinator
from reliable_agent_runtime.application.execution.compensation import CompensationCoordinator
from reliable_agent_runtime.application.execution.journal import RunJournal
from reliable_agent_runtime.application.execution.steps import (
    StepExecutionKind,
    StepExecutor,
)
from reliable_agent_runtime.application.ports import RunLockManager, RuntimeStore
from reliable_agent_runtime.domain.enums import EventType, RunStatus, StepStatus
from reliable_agent_runtime.domain.errors import InvalidRunStateError
from reliable_agent_runtime.domain.models import AgentRun, ErrorInfo, PlanStep


@dataclass(frozen=True, slots=True)
class ExecutionEngine:
    """Coordinate a run while delegating specialized execution concerns.

    The orchestrator owns only aggregate lifecycle and dependency traversal.
    Tool invocation, approval, compensation, and persistence versioning live in
    cohesive collaborators behind explicit interfaces.
    """

    store: RuntimeStore
    locks: RunLockManager
    journal: RunJournal
    approvals: ApprovalCoordinator
    steps: StepExecutor
    compensation: CompensationCoordinator
    events: EventFactory

    async def execute(self, run_id: str) -> AgentRun:
        """Run or resume an aggregate until it terminates or needs approval."""

        async with self.locks.lock(run_id):
            run = await self.store.get_run(run_id)
            self._ensure_executable(run)
            if run.status is RunStatus.SUCCEEDED:
                return run

            if run.status is RunStatus.WAITING_APPROVAL:
                if await self.approvals.pending_for_run(run) is not None:
                    return run

            await self._mark_started_or_resumed(run)
            for step in run.plan.topological_steps():
                state = run.step_states[step.id]
                if state.status in {StepStatus.SUCCEEDED, StepStatus.COMPENSATED}:
                    continue
                if state.status is StepStatus.FAILED:
                    return await self._finish_failed_run(
                        run,
                        failed_step=step,
                        error=state.error or self._previous_failure(step),
                    )

                unmet = self._unmet_dependencies(run, step)
                if unmet:
                    error = ErrorInfo(
                        code="dependency_not_satisfied",
                        message=f"step {step.id!r} has unmet dependencies",
                        details={"dependencies": unmet},
                    )
                    outcome = await self.steps.fail(run, step, error)
                    return await self._finish_failed_run(
                        run,
                        failed_step=step,
                        error=outcome.error or error,
                    )

                outcome = await self.steps.execute(run, step)
                if outcome.kind is StepExecutionKind.WAITING_APPROVAL:
                    return run
                if outcome.kind is StepExecutionKind.FAILED:
                    return await self._finish_failed_run(
                        run,
                        failed_step=step,
                        error=outcome.error or self._previous_failure(step),
                    )

            return await self._finish_succeeded_run(run)

    def _ensure_executable(self, run: AgentRun) -> None:
        if not run.status.is_terminal:
            return
        if run.status is RunStatus.SUCCEEDED:
            return
        raise InvalidRunStateError(
            f"run {run.id!r} is already terminal",
            details={"run_id": run.id, "status": run.status.value},
        )

    async def _mark_started_or_resumed(self, run: AgentRun) -> None:
        if run.status is RunStatus.SUCCEEDED:
            return
        event_type = (
            EventType.RUN_STARTED
            if run.status is RunStatus.PENDING
            else EventType.RUN_RESUMED
        )
        run.status = RunStatus.RUNNING
        await self.journal.save(
            run,
            events=(
                self.events.create(run_id=run.id, event_type=event_type),
            ),
        )

    async def _finish_succeeded_run(self, run: AgentRun) -> AgentRun:
        result_steps = run.plan.terminal_steps()
        run.status = RunStatus.SUCCEEDED
        if len(result_steps) == 1:
            run.result = run.step_states[result_steps[0].id].output or {}
        else:
            run.result = {
                "steps": {
                    step.id: run.step_states[step.id].output or {}
                    for step in result_steps
                },
            }
        run.error = None
        await self.journal.save(
            run,
            events=(
                self.events.create(
                    run_id=run.id,
                    event_type=EventType.RUN_SUCCEEDED,
                    payload={
                        "result_step_ids": [step.id for step in result_steps],
                    },
                ),
            ),
        )
        return run

    async def _finish_failed_run(
        self,
        run: AgentRun,
        *,
        failed_step: PlanStep,
        error: ErrorInfo,
    ) -> AgentRun:
        compensation = None
        if run.plan.compensate_on_failure:
            compensation = await self.compensation.compensate(
                run,
                failed_step=failed_step,
            )

        fully_compensated = bool(compensation and compensation.fully_compensated)
        run.status = (
            RunStatus.FAILED_COMPENSATED if fully_compensated else RunStatus.FAILED
        )
        run.error = error
        compensation_payload = (
            {
                "candidates": compensation.candidates,
                "compensated": compensation.compensated,
                "unsupported": compensation.unsupported,
                "failed": compensation.failed,
            }
            if compensation
            else None
        )
        await self.journal.save(
            run,
            events=(
                self.events.create(
                    run_id=run.id,
                    step_id=failed_step.id,
                    event_type=EventType.RUN_FAILED,
                    payload={
                        "error_code": error.code,
                        "failed_step_id": failed_step.id,
                        "fully_compensated": fully_compensated,
                        "compensation": compensation_payload,
                    },
                ),
            ),
        )
        return run

    @staticmethod
    def _unmet_dependencies(run: AgentRun, step: PlanStep) -> list[str]:
        return [
            dependency
            for dependency in step.depends_on
            if run.step_states[dependency].status is not StepStatus.SUCCEEDED
        ]

    @staticmethod
    def _previous_failure(step: PlanStep) -> ErrorInfo:
        return ErrorInfo(
            code="step_failed",
            message=f"step {step.id!r} previously failed",
        )
