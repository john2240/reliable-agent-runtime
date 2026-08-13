"""Execution of one validated plan step."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from reliable_agent_runtime.application.events import EventFactory
from reliable_agent_runtime.application.execution.approvals import ApprovalCoordinator
from reliable_agent_runtime.application.execution.invocation import (
    AttemptSuccess,
    ToolInvoker,
)
from reliable_agent_runtime.application.execution.journal import RunJournal
from reliable_agent_runtime.application.ports import (
    Clock,
    IdGenerator,
    PolicyEngine,
    Sleeper,
    Tool,
    ToolRegistry,
)
from reliable_agent_runtime.application.template import TemplateResolver
from reliable_agent_runtime.domain.enums import (
    ApprovalStatus,
    EventType,
    RunStatus,
    StepStatus,
    VerificationOutcome,
)
from reliable_agent_runtime.domain.errors import PolicyViolationError, ReliableAgentError
from reliable_agent_runtime.domain.models import (
    AgentRun,
    ErrorInfo,
    PlanStep,
    RuntimeEvent,
    ToolContext,
)
from reliable_agent_runtime.domain.types import JsonObject

_MAX_BACKOFF_SECONDS: Final[float] = 5.0


class StepExecutionKind(StrEnum):
    """Application-level outcomes consumed by the run orchestrator."""

    SUCCEEDED = "succeeded"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StepExecutionOutcome:
    """Result of advancing one step as far as currently possible."""

    kind: StepExecutionKind
    error: ErrorInfo | None = None

    @classmethod
    def succeeded(cls) -> StepExecutionOutcome:
        return cls(kind=StepExecutionKind.SUCCEEDED)

    @classmethod
    def waiting_approval(cls) -> StepExecutionOutcome:
        return cls(kind=StepExecutionKind.WAITING_APPROVAL)

    @classmethod
    def failed(cls, error: ErrorInfo) -> StepExecutionOutcome:
        return cls(kind=StepExecutionKind.FAILED, error=error)


@dataclass(frozen=True, slots=True)
class StepExecutor:
    """Advance one tool step through validation, policy, and execution.

    This class owns step-level lifecycle only. Run-level dependency traversal,
    terminal status, and compensation remain in the orchestrator/coordinator,
    preserving a narrow and independently testable responsibility.
    """

    tools: ToolRegistry
    policy: PolicyEngine
    resolver: TemplateResolver
    approvals: ApprovalCoordinator
    invoker: ToolInvoker
    journal: RunJournal
    sleeper: Sleeper
    clock: Clock
    ids: IdGenerator
    events: EventFactory

    async def execute(self, run: AgentRun, step: PlanStep) -> StepExecutionOutcome:
        state = run.step_states[step.id]
        waiting_outcome = await self._resume_approval_if_needed(run, step)
        if waiting_outcome is not None:
            return waiting_outcome

        try:
            tool, arguments = await self._resolve_call(run, step)
        except ReliableAgentError as exc:
            return await self.fail(
                run,
                step,
                ErrorInfo(code=exc.code, message=exc.message, details=exc.details),
            )

        context = self._tool_context(run, step)
        if state.status is StepStatus.RUNNING and state.attempts > 0:
            recovery = await self._recover_inflight(
                run,
                step,
                tool,
                context,
                arguments,
            )
            if recovery is not None:
                return recovery

        precondition = await self.invoker.check_preconditions(tool, context, arguments)
        if not precondition.passed:
            return await self.fail(
                run,
                step,
                ErrorInfo(
                    code="precondition_failed",
                    message=precondition.reason or "tool precondition failed",
                    retryable=precondition.retryable,
                    details=precondition.details,
                ),
            )

        policy = self.policy.evaluate(run=run, tool=tool.spec, arguments=arguments)
        if not policy.allowed:
            return await self.fail(
                run,
                step,
                ErrorInfo(
                    code=PolicyViolationError.code,
                    message=policy.reason or f"tool {tool.spec.name!r} was denied by policy",
                    details={"tool_name": tool.spec.name, "step_id": step.id},
                ),
            )

        if policy.approval_required:
            approval = await self.approvals.get_or_create(
                run=run,
                step=step,
                tool=tool,
                arguments=arguments,
                reason=policy.reason or "approval required by policy",
            )
            if approval.status is ApprovalStatus.PENDING:
                return StepExecutionOutcome.waiting_approval()
            if approval.status is ApprovalStatus.DENIED:
                return await self.fail(
                    run,
                    step,
                    ErrorInfo(
                        code="approval_denied",
                        message=f"approval denied for step {step.id!r}",
                        details={"approval_id": approval.id},
                    ),
                )

        while state.attempts < tool.spec.max_attempts:
            await self._mark_attempt_started(run, step, tool)
            attempt = await self.invoker.invoke(tool, context, arguments)
            if isinstance(attempt, AttemptSuccess):
                return await self._mark_succeeded(run, step, tool, attempt)

            state.error = attempt.error
            if attempt.can_retry and state.attempts < tool.spec.max_attempts:
                await self._schedule_retry(run, step, tool, attempt.error)
                continue
            return await self.fail(run, step, attempt.error)

        return await self.fail(
            run,
            step,
            ErrorInfo(
                code="attempts_exhausted",
                message=f"tool {tool.spec.name!r} exhausted all attempts",
            ),
        )

    async def _resume_approval_if_needed(
        self,
        run: AgentRun,
        step: PlanStep,
    ) -> StepExecutionOutcome | None:
        state = run.step_states[step.id]
        if state.status is not StepStatus.WAITING_APPROVAL:
            return None
        if not state.approval_id:
            return await self.fail(
                run,
                step,
                ErrorInfo(
                    code="approval_state_invalid",
                    message=f"step {step.id!r} is waiting without an approval id",
                ),
            )

        approval = await self.approvals.get(state.approval_id)
        if approval.status is ApprovalStatus.PENDING:
            run.status = RunStatus.WAITING_APPROVAL
            return StepExecutionOutcome.waiting_approval()
        if approval.status is ApprovalStatus.DENIED:
            return await self.fail(
                run,
                step,
                ErrorInfo(
                    code="approval_denied",
                    message=f"approval denied for step {step.id!r}",
                    details={
                        "approval_id": approval.id,
                        "decided_by": approval.decided_by,
                        "reason": approval.decision_reason,
                    },
                ),
            )
        state.status = StepStatus.PENDING
        return None

    async def _resolve_call(
        self,
        run: AgentRun,
        step: PlanStep,
    ) -> tuple[Tool, JsonObject]:
        state = run.step_states[step.id]
        tool = self.tools.get(step.tool_name)
        if state.resolved_arguments is None:
            resolved = self.resolver.resolve_arguments(
                step.arguments,
                self._template_context(run),
            )
            state.resolved_arguments = await tool.validate_arguments(resolved)

        arguments = state.resolved_arguments or {}
        state.call_id = state.call_id or self.ids.deterministic(
            "call",
            f"{run.id}:{step.id}",
        )
        state.idempotency_key = state.idempotency_key or self._idempotency_key(
            run,
            step,
            arguments,
        )
        return tool, arguments

    def _tool_context(self, run: AgentRun, step: PlanStep) -> ToolContext:
        state = run.step_states[step.id]
        if state.call_id is None or state.idempotency_key is None:
            raise RuntimeError("call identity must be resolved before execution")
        return ToolContext(
            run_id=run.id,
            step_id=step.id,
            call_id=state.call_id,
            idempotency_key=state.idempotency_key,
            actor=run.actor,
            objective=run.objective,
            metadata={"plan_id": run.plan.id},
        )

    async def _recover_inflight(
        self,
        run: AgentRun,
        step: PlanStep,
        tool: Tool,
        context: ToolContext,
        arguments: JsonObject,
    ) -> StepExecutionOutcome | None:
        verification = await self.invoker.verify(tool, context, arguments, None)
        state = run.step_states[step.id]
        if verification.outcome is VerificationOutcome.CONFIRMED_SUCCESS:
            state.status = StepStatus.SUCCEEDED
            state.output = verification.observed_output or {}
            state.output_metadata = {"recovered_after_restart": True}
            state.error = None
            state.completed_at = self.clock.now()
            await self.journal.save(
                run,
                events=(
                    self.events.create(
                        run_id=run.id,
                        step_id=step.id,
                        event_type=EventType.TOOL_OUTCOME_RECOVERED,
                        payload={
                            "tool_name": tool.spec.name,
                            "strategy": "restart_verification",
                        },
                    ),
                    self.events.create(
                        run_id=run.id,
                        step_id=step.id,
                        event_type=EventType.STEP_SUCCEEDED,
                        payload={"tool_name": tool.spec.name, "recovered": True},
                    ),
                ),
            )
            return StepExecutionOutcome.succeeded()

        if (
            verification.outcome is VerificationOutcome.CONFIRMED_NOT_APPLIED
            or self.invoker.repeat_is_safe(tool)
        ):
            state.status = StepStatus.PENDING
            await self.journal.save(
                run,
                events=(
                    self.events.create(
                        run_id=run.id,
                        step_id=step.id,
                        event_type=EventType.TOOL_RETRY_SCHEDULED,
                        payload={
                            "tool_name": tool.spec.name,
                            "reason": "inflight_step_recovery",
                            "verification": verification.outcome.value,
                        },
                    ),
                ),
            )
            return None

        return await self.fail(
            run,
            step,
            ErrorInfo(
                code="inflight_outcome_inconclusive",
                message=(
                    "cannot safely resume a non-idempotent in-flight tool call "
                    "because verification was inconclusive"
                ),
                details={"tool_name": tool.spec.name},
            ),
        )

    async def _mark_attempt_started(
        self,
        run: AgentRun,
        step: PlanStep,
        tool: Tool,
    ) -> None:
        state = run.step_states[step.id]
        state.status = StepStatus.RUNNING
        state.attempts += 1
        state.started_at = state.started_at or self.clock.now()
        await self.journal.save(
            run,
            events=(
                self.events.create(
                    run_id=run.id,
                    step_id=step.id,
                    event_type=EventType.STEP_STARTED,
                    payload={
                        "tool_name": tool.spec.name,
                        "attempt": state.attempts,
                        "effect": tool.spec.effect.value,
                        "call_id": state.call_id,
                    },
                ),
            ),
        )

    async def _mark_succeeded(
        self,
        run: AgentRun,
        step: PlanStep,
        tool: Tool,
        attempt: AttemptSuccess,
    ) -> StepExecutionOutcome:
        state = run.step_states[step.id]
        state.status = StepStatus.SUCCEEDED
        state.output = attempt.result.output
        state.output_metadata = attempt.result.metadata
        state.error = None
        state.completed_at = self.clock.now()

        events: list[RuntimeEvent] = []
        if attempt.recovered_by_verification:
            events.append(
                self.events.create(
                    run_id=run.id,
                    step_id=step.id,
                    event_type=EventType.TOOL_OUTCOME_RECOVERED,
                    payload={
                        "tool_name": tool.spec.name,
                        "attempt": state.attempts,
                        "strategy": "postcondition_verification",
                    },
                ),
            )
        events.append(
            self.events.create(
                run_id=run.id,
                step_id=step.id,
                event_type=EventType.STEP_SUCCEEDED,
                payload={
                    "tool_name": tool.spec.name,
                    "attempts": state.attempts,
                    "recovered_by_verification": attempt.recovered_by_verification,
                },
            ),
        )
        await self.journal.save(run, events=tuple(events))
        return StepExecutionOutcome.succeeded()

    async def _schedule_retry(
        self,
        run: AgentRun,
        step: PlanStep,
        tool: Tool,
        error: ErrorInfo,
    ) -> None:
        state = run.step_states[step.id]
        delay = min(
            tool.spec.backoff_seconds * (2 ** (state.attempts - 1)),
            _MAX_BACKOFF_SECONDS,
        )
        await self.journal.save(
            run,
            events=(
                self.events.create(
                    run_id=run.id,
                    step_id=step.id,
                    event_type=EventType.TOOL_RETRY_SCHEDULED,
                    payload={
                        "tool_name": tool.spec.name,
                        "attempt": state.attempts,
                        "next_attempt": state.attempts + 1,
                        "delay_seconds": delay,
                        "error_code": error.code,
                    },
                ),
            ),
        )
        if delay:
            await self.sleeper.sleep(delay)

    async def fail(
        self,
        run: AgentRun,
        step: PlanStep,
        error: ErrorInfo,
    ) -> StepExecutionOutcome:
        state = run.step_states[step.id]
        state.status = StepStatus.FAILED
        state.error = error
        state.completed_at = self.clock.now()
        await self.journal.save(
            run,
            events=(
                self.events.create(
                    run_id=run.id,
                    step_id=step.id,
                    event_type=EventType.STEP_FAILED,
                    payload={
                        "tool_name": step.tool_name,
                        "error_code": error.code,
                        "retryable": error.retryable,
                    },
                ),
            ),
        )
        return StepExecutionOutcome.failed(error)

    @staticmethod
    def _template_context(run: AgentRun) -> JsonObject:
        return {
            "input": run.input,
            "steps": {
                step_id: {
                    "status": state.status.value,
                    "output": state.output or {},
                }
                for step_id, state in run.step_states.items()
            },
        }

    @staticmethod
    def _idempotency_key(
        run: AgentRun,
        step: PlanStep,
        arguments: JsonObject,
    ) -> str:
        canonical = json.dumps(
            {
                "run_id": run.id,
                "step_id": step.id,
                "tool": step.tool_name,
                "arguments": arguments,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return "idem_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:40]
