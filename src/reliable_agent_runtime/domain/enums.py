"""Domain enumerations for runs, steps, tools, approvals, and events."""

from enum import StrEnum


class ToolEffect(StrEnum):
    """How a tool call can affect external state."""

    READ = "read"
    WRITE = "write"
    IRREVERSIBLE = "irreversible"


class RunStatus(StrEnum):
    """Lifecycle states of an agent run."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    FAILED_COMPENSATED = "failed_compensated"

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.FAILED_COMPENSATED,
        }


class StepStatus(StrEnum):
    """Lifecycle states of an individual plan step."""

    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    COMPENSATED = "compensated"


class ApprovalStatus(StrEnum):
    """Human approval states."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class ApprovalDecision(StrEnum):
    """Decisions accepted by the approval API."""

    APPROVE = "approve"
    DENY = "deny"


class VerificationOutcome(StrEnum):
    """Tri-state result used to resolve ambiguous tool outcomes safely."""

    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_NOT_APPLIED = "confirmed_not_applied"
    INCONCLUSIVE = "inconclusive"


class EventType(StrEnum):
    """Append-only audit events emitted by the runtime."""

    RUN_CREATED = "run.created"
    RUN_STARTED = "run.started"
    RUN_RESUMED = "run.resumed"
    RUN_SUCCEEDED = "run.succeeded"
    RUN_FAILED = "run.failed"
    STEP_STARTED = "step.started"
    STEP_SUCCEEDED = "step.succeeded"
    STEP_FAILED = "step.failed"
    STEP_COMPENSATION_STARTED = "step.compensation_started"
    STEP_COMPENSATED = "step.compensated"
    STEP_COMPENSATION_FAILED = "step.compensation_failed"
    TOOL_RETRY_SCHEDULED = "tool.retry_scheduled"
    TOOL_OUTCOME_RECOVERED = "tool.outcome_recovered"
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_APPROVED = "approval.approved"
    APPROVAL_DENIED = "approval.denied"
