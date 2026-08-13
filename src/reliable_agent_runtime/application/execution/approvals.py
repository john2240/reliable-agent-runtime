"""Human approval coordination for sensitive tool calls."""

from __future__ import annotations

from dataclasses import dataclass

from reliable_agent_runtime.application.events import EventFactory
from reliable_agent_runtime.application.execution.journal import RunJournal
from reliable_agent_runtime.application.ports import Clock, IdGenerator, RuntimeStore, Tool
from reliable_agent_runtime.domain.enums import ApprovalStatus, EventType, RunStatus, StepStatus
from reliable_agent_runtime.domain.errors import InvalidRunStateError
from reliable_agent_runtime.domain.models import AgentRun, Approval, PlanStep
from reliable_agent_runtime.domain.types import JsonObject


@dataclass(frozen=True, slots=True)
class ApprovalCoordinator:
    """Create, load, and surface approval gates without executing tools."""

    store: RuntimeStore
    journal: RunJournal
    clock: Clock
    ids: IdGenerator
    events: EventFactory

    async def get_or_create(
        self,
        *,
        run: AgentRun,
        step: PlanStep,
        tool: Tool,
        arguments: JsonObject,
        reason: str,
    ) -> Approval:
        state = run.step_states[step.id]
        if state.approval_id:
            approval = await self.store.get_approval(state.approval_id)
            if approval.status is ApprovalStatus.APPROVED:
                state.status = StepStatus.PENDING
                return approval
            if approval.status is ApprovalStatus.DENIED:
                return approval
            run.status = RunStatus.WAITING_APPROVAL
            state.status = StepStatus.WAITING_APPROVAL
            return approval

        if state.call_id is None:
            raise InvalidRunStateError(
                "a call id must be assigned before approval is requested",
                details={"run_id": run.id, "step_id": step.id},
            )

        approval = Approval(
            id=self.ids.new("apr"),
            run_id=run.id,
            step_id=step.id,
            tool_name=tool.spec.name,
            call_id=state.call_id,
            reason=reason,
            arguments=arguments,
            status=ApprovalStatus.PENDING,
            requested_at=self.clock.now(),
        )
        state.approval_id = approval.id
        state.status = StepStatus.WAITING_APPROVAL
        run.status = RunStatus.WAITING_APPROVAL
        await self.journal.save(
            run,
            approvals=(approval,),
            events=(
                self.events.create(
                    run_id=run.id,
                    step_id=step.id,
                    event_type=EventType.APPROVAL_REQUIRED,
                    payload={
                        "approval_id": approval.id,
                        "tool_name": tool.spec.name,
                        "reason": reason,
                        "effect": tool.spec.effect.value,
                    },
                ),
            ),
        )
        return approval

    async def get(self, approval_id: str) -> Approval:
        """Load an approval through the coordinator boundary."""

        return await self.store.get_approval(approval_id)

    async def pending_for_run(self, run: AgentRun) -> Approval | None:
        """Return the first pending approval in stable plan order."""

        for step in run.plan.topological_steps():
            state = run.step_states[step.id]
            if state.status is not StepStatus.WAITING_APPROVAL:
                continue
            if not state.approval_id:
                raise InvalidRunStateError(
                    "a waiting step is missing its approval id",
                    details={"run_id": run.id, "step_id": step.id},
                )
            approval = await self.store.get_approval(state.approval_id)
            if approval.status is ApprovalStatus.PENDING:
                return approval
        return None
