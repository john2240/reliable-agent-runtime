"""Best-effort compensation for completed side-effecting plan steps."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from reliable_agent_runtime.application.events import EventFactory
from reliable_agent_runtime.application.execution.journal import RunJournal
from reliable_agent_runtime.application.ports import Clock, IdGenerator, ToolRegistry
from reliable_agent_runtime.domain.enums import EventType, StepStatus, ToolEffect
from reliable_agent_runtime.domain.models import AgentRun, PlanStep, ToolContext, ToolResult


@dataclass(frozen=True, slots=True)
class CompensationResult:
    """Summary of a reverse-order compensation pass."""

    candidates: int
    compensated: int
    unsupported: int
    failed: int

    @property
    def fully_compensated(self) -> bool:
        return (
            self.candidates > 0
            and self.compensated == self.candidates
            and self.unsupported == 0
            and self.failed == 0
        )


@dataclass(frozen=True, slots=True)
class CompensationCoordinator:
    """Reverse successful writes without coupling orchestration to adapters."""

    tools: ToolRegistry
    journal: RunJournal
    clock: Clock
    ids: IdGenerator
    events: EventFactory

    async def compensate(
        self,
        run: AgentRun,
        *,
        failed_step: PlanStep,
    ) -> CompensationResult:
        ordered = run.plan.topological_steps()
        failed_index = next(
            index for index, step in enumerate(ordered) if step.id == failed_step.id
        )
        candidates = [
            step
            for step in ordered[:failed_index]
            if run.step_states[step.id].status is StepStatus.SUCCEEDED
            and self.tools.get(step.tool_name).spec.effect is not ToolEffect.READ
        ]

        compensated = 0
        unsupported = 0
        failures = 0
        for step in reversed(candidates):
            state = run.step_states[step.id]
            tool = self.tools.get(step.tool_name)
            if not tool.supports_compensation:
                unsupported += 1
                continue

            original_key = state.idempotency_key or self.ids.deterministic(
                "idem",
                f"{run.id}:{step.id}",
            )
            context = ToolContext(
                run_id=run.id,
                step_id=step.id,
                call_id=self.ids.deterministic(
                    "call",
                    f"{run.id}:{step.id}:compensate",
                ),
                idempotency_key=f"{original_key}:compensate",
                actor=run.actor,
                objective=run.objective,
                metadata={"compensation": True},
            )
            await self.journal.save(
                run,
                events=(
                    self.events.create(
                        run_id=run.id,
                        step_id=step.id,
                        event_type=EventType.STEP_COMPENSATION_STARTED,
                        payload={"tool_name": tool.spec.name},
                    ),
                ),
            )
            try:
                async with asyncio.timeout(tool.spec.timeout_seconds):
                    await tool.compensate(
                        context,
                        state.resolved_arguments or {},
                        ToolResult(
                            output=state.output or {},
                            metadata=state.output_metadata,
                        ),
                    )
            except Exception as exc:  # the audit log preserves partial rollback
                failures += 1
                await self.journal.save(
                    run,
                    events=(
                        self.events.create(
                            run_id=run.id,
                            step_id=step.id,
                            event_type=EventType.STEP_COMPENSATION_FAILED,
                            payload={
                                "tool_name": tool.spec.name,
                                "exception_type": type(exc).__name__,
                            },
                        ),
                    ),
                )
                continue

            compensated += 1
            state.status = StepStatus.COMPENSATED
            state.completed_at = self.clock.now()
            await self.journal.save(
                run,
                events=(
                    self.events.create(
                        run_id=run.id,
                        step_id=step.id,
                        event_type=EventType.STEP_COMPENSATED,
                        payload={"tool_name": tool.spec.name},
                    ),
                ),
            )

        return CompensationResult(
            candidates=len(candidates),
            compensated=compensated,
            unsupported=unsupported,
            failed=failures,
        )
