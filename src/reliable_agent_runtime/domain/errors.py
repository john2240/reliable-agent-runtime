"""Typed domain and application errors.

The API layer maps these errors to RFC 9457 problem details without coupling
core runtime code to HTTP status codes.
"""

from __future__ import annotations

from typing import Any


class ReliableAgentError(Exception):
    """Base class for errors that are safe to expose at an API boundary."""

    code = "reliable_agent_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ValidationError(ReliableAgentError):
    code = "validation_error"


class PlanValidationError(ValidationError):
    code = "plan_validation_error"


class TemplateResolutionError(ValidationError):
    code = "template_resolution_error"


class ToolInputValidationError(ValidationError):
    code = "tool_input_validation_error"


class NotFoundError(ReliableAgentError):
    code = "not_found"


class RunNotFoundError(NotFoundError):
    code = "run_not_found"


class ToolNotFoundError(NotFoundError):
    code = "tool_not_found"


class ApprovalNotFoundError(NotFoundError):
    code = "approval_not_found"


class ConflictError(ReliableAgentError):
    code = "conflict"


class ConcurrentUpdateError(ConflictError):
    code = "concurrent_update"


class InvalidRunStateError(ConflictError):
    code = "invalid_run_state"


class ApprovalAlreadyDecidedError(ConflictError):
    code = "approval_already_decided"


class IdempotencyConflictError(ConflictError):
    code = "idempotency_conflict"


class PolicyViolationError(ReliableAgentError):
    code = "policy_violation"


class ToolExecutionError(Exception):
    """Base exception raised by tool adapters.

    Tool exceptions stay internal to the runtime and are converted into a
    serializable :class:`ErrorInfo` before persistence.
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool,
        safe_to_retry: bool,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.retryable = retryable
        self.safe_to_retry = safe_to_retry
        self.details = details or {}


class TransientToolError(ToolExecutionError):
    """A temporary tool failure whose outcome is known."""

    def __init__(
        self,
        message: str,
        *,
        safe_to_retry: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            message,
            retryable=True,
            safe_to_retry=safe_to_retry,
            details=details,
        )


class PermanentToolError(ToolExecutionError):
    """A non-retryable tool failure whose outcome is known."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            retryable=False,
            safe_to_retry=False,
            details=details,
        )


class UnknownToolOutcome(ToolExecutionError):
    """The call may have committed although the client did not get a response."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(
            message,
            retryable=True,
            safe_to_retry=False,
            details=details,
        )


class CompensationNotSupportedError(PermanentToolError):
    """Raised when compensation is requested for a non-compensatable tool."""
