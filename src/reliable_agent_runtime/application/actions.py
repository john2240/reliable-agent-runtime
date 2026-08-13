"""Convenience use case for adaptive agents that propose one action at a time."""

from __future__ import annotations

from dataclasses import dataclass

from reliable_agent_runtime.application.engine import ExecutionEngine
from reliable_agent_runtime.application.service import RunService
from reliable_agent_runtime.domain.models import AgentRun, ExecutionPlan, PlanStep
from reliable_agent_runtime.domain.types import JsonObject


@dataclass(frozen=True, slots=True)
class ExecuteActionResult:
    """Return the action run and whether the durable resource was newly created."""

    run: AgentRun
    created: bool


@dataclass(frozen=True, slots=True)
class ActionService:
    """Execute a planner-proposed action through the normal reliable run path.

    Adaptive agents do not need to freeze an entire long-horizon plan. They can
    submit one action (or use the regular run API for a short multi-step phase),
    inspect the structured outcome, and then decide what to do next.
    """

    runs: RunService
    engine: ExecutionEngine

    async def execute_action(
        self,
        *,
        objective: str,
        action_id: str,
        tool_name: str,
        arguments: JsonObject,
        actor: str,
        description: str | None = None,
        idempotency_key: str | None = None,
    ) -> ExecuteActionResult:
        plan = ExecutionPlan(
            id="adaptive_action",
            name=f"Execute adaptive action {action_id}",
            compensate_on_failure=False,
            steps=(
                PlanStep(
                    id=action_id,
                    tool_name=tool_name,
                    arguments=arguments,
                    description=description,
                ),
            ),
        )
        created = await self.runs.create_run(
            objective=objective,
            plan=plan,
            input_data={},
            actor=actor,
            idempotency_key=idempotency_key,
        )

        # Replaying an idempotent request for a terminal action should return
        # the existing durable result rather than trying to execute it again.
        if created.run.status.is_terminal:
            return ExecuteActionResult(run=created.run, created=created.created)

        run = await self.engine.execute(created.run.id)
        return ExecuteActionResult(run=run, created=created.created)
