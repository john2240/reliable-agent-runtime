"""Pydantic request and response models for API v1."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field

from reliable_agent_runtime.domain.enums import (
    ApprovalDecision,
    ApprovalStatus,
    EventType,
    RunStatus,
    StepStatus,
    ToolEffect,
)
from reliable_agent_runtime.domain.models import (
    AgentRun,
    Approval,
    ExecutionPlan,
    PlanStep,
    RuntimeEvent,
)


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PlanStepCreate(ApiModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    tool: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class ExecutionPlanCreate(ApiModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    name: str = Field(min_length=1, max_length=200)
    compensate_on_failure: bool = True
    steps: list[PlanStepCreate] = Field(min_length=1, max_length=100)

    def to_domain(self) -> ExecutionPlan:
        return ExecutionPlan(
            id=self.id,
            name=self.name,
            compensate_on_failure=self.compensate_on_failure,
            steps=tuple(
                PlanStep(
                    id=step.id,
                    tool_name=step.tool,
                    arguments=step.arguments,
                    depends_on=tuple(step.depends_on),
                    description=step.description,
                )
                for step in self.steps
            ),
        )


class CreateRunRequest(ApiModel):
    objective: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="api-user", min_length=1, max_length=200)
    input: dict[str, Any] = Field(default_factory=dict)
    plan: ExecutionPlanCreate


class ExecuteActionRequest(ApiModel):
    """One planner-proposed action for an adaptive agent loop."""

    objective: str = Field(min_length=1, max_length=4000)
    actor: str = Field(default="api-user", min_length=1, max_length=200)
    action_id: str = Field(default="action", pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    tool: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,63}$")
    arguments: dict[str, Any] = Field(default_factory=dict)
    description: str | None = Field(default=None, max_length=500)


class ApprovalDecisionRequest(ApiModel):
    decision: ApprovalDecision
    actor: str = Field(min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class PlanStepResponse(ApiModel):
    id: str
    tool: str
    arguments: dict[str, Any]
    depends_on: list[str]
    description: str | None


class ExecutionPlanResponse(ApiModel):
    id: str
    name: str
    compensate_on_failure: bool
    steps: list[PlanStepResponse]


class ErrorInfoResponse(ApiModel):
    code: str
    message: str
    retryable: bool
    details: dict[str, Any]


class StepStateResponse(ApiModel):
    id: str
    status: StepStatus
    attempts: int
    call_id: str | None
    idempotency_key: str | None
    resolved_arguments: dict[str, Any] | None
    output: dict[str, Any] | None
    output_metadata: dict[str, Any]
    error: ErrorInfoResponse | None
    approval_id: str | None
    started_at: datetime | None
    completed_at: datetime | None


class RunLinks(ApiModel):
    self: str
    execute: str
    events: str
    approvals: str


class RunResponse(ApiModel):
    id: str
    objective: str
    actor: str
    status: RunStatus
    version: int
    input: dict[str, Any]
    plan: ExecutionPlanResponse
    steps: list[StepStateResponse]
    result: dict[str, Any] | None
    error: ErrorInfoResponse | None
    created_at: datetime
    updated_at: datetime
    links: RunLinks

    @classmethod
    def from_domain(cls, run: AgentRun, *, api_prefix: str = "/api/v1") -> Self:
        plan = ExecutionPlanResponse(
            id=run.plan.id,
            name=run.plan.name,
            compensate_on_failure=run.plan.compensate_on_failure,
            steps=[
                PlanStepResponse(
                    id=step.id,
                    tool=step.tool_name,
                    arguments=step.arguments,
                    depends_on=list(step.depends_on),
                    description=step.description,
                )
                for step in run.plan.steps
            ],
        )
        steps: list[StepStateResponse] = []
        for step in run.plan.steps:
            state = run.step_states[step.id]
            steps.append(
                StepStateResponse(
                    id=step.id,
                    status=state.status,
                    attempts=state.attempts,
                    call_id=state.call_id,
                    idempotency_key=state.idempotency_key,
                    resolved_arguments=state.resolved_arguments,
                    output=state.output,
                    output_metadata=state.output_metadata,
                    error=(
                        ErrorInfoResponse(
                            code=state.error.code,
                            message=state.error.message,
                            retryable=state.error.retryable,
                            details=state.error.details,
                        )
                        if state.error
                        else None
                    ),
                    approval_id=state.approval_id,
                    started_at=state.started_at,
                    completed_at=state.completed_at,
                ),
            )
        base = f"{api_prefix}/runs/{run.id}"
        return cls(
            id=run.id,
            objective=run.objective,
            actor=run.actor,
            status=run.status,
            version=run.version,
            input=run.input,
            plan=plan,
            steps=steps,
            result=run.result,
            error=(
                ErrorInfoResponse(
                    code=run.error.code,
                    message=run.error.message,
                    retryable=run.error.retryable,
                    details=run.error.details,
                )
                if run.error
                else None
            ),
            created_at=run.created_at,
            updated_at=run.updated_at,
            links=RunLinks(
                self=base,
                execute=f"{base}/execute",
                events=f"{base}/events",
                approvals=f"{base}/approvals",
            ),
        )


class RuntimeEventResponse(ApiModel):
    id: str
    run_id: str
    sequence: int
    type: EventType
    step_id: str | None
    payload: dict[str, Any]
    created_at: datetime

    @classmethod
    def from_domain(cls, event: RuntimeEvent) -> Self:
        if event.sequence is None:
            raise ValueError("persisted event must have a sequence")
        return cls(
            id=event.id,
            run_id=event.run_id,
            sequence=event.sequence,
            type=event.event_type,
            step_id=event.step_id,
            payload=event.payload,
            created_at=event.created_at,
        )


class ApprovalResponse(ApiModel):
    id: str
    run_id: str
    step_id: str
    tool_name: str
    call_id: str
    reason: str
    arguments: dict[str, Any]
    status: ApprovalStatus
    requested_at: datetime
    decided_at: datetime | None
    decided_by: str | None
    decision_reason: str | None

    @classmethod
    def from_domain(cls, approval: Approval) -> Self:
        return cls.model_validate(approval, from_attributes=True)


class ToolResponse(ApiModel):
    name: str
    version: str
    description: str
    effect: ToolEffect
    idempotent: bool
    requires_approval: bool
    supports_compensation: bool
    timeout_seconds: float
    max_attempts: int
    tags: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]


class HealthResponse(ApiModel):
    status: str
    service: str
    environment: str


class ProblemDetail(BaseModel):
    """RFC 9457-compatible error response."""

    model_config = ConfigDict(extra="allow")

    type: str
    title: str
    status: int
    detail: str
    instance: str
    code: str
    request_id: str | None = None
    errors: list[dict[str, Any]] | None = None
