"""Safe invocation and verification of one tool adapter call."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from reliable_agent_runtime.application.ports import Tool
from reliable_agent_runtime.domain.enums import ToolEffect, VerificationOutcome
from reliable_agent_runtime.domain.errors import (
    PermanentToolError,
    ToolExecutionError,
    UnknownToolOutcome,
)
from reliable_agent_runtime.domain.models import (
    CheckResult,
    ErrorInfo,
    ToolContext,
    ToolResult,
    VerificationResult,
)
from reliable_agent_runtime.domain.types import JsonObject

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AttemptSuccess:
    """A tool call whose postcondition was confirmed."""

    result: ToolResult
    recovered_by_verification: bool = False


@dataclass(frozen=True, slots=True)
class AttemptFailure:
    """A normalized failure and whether the exact call may be retried."""

    error: ErrorInfo
    can_retry: bool


@dataclass(frozen=True, slots=True)
class ToolInvoker:
    """Protect the runtime from adapter-specific failure semantics.

    The invoker owns timeout handling, exception normalization, ambiguous
    outcome recovery, and postcondition verification. It does not mutate or
    persist a run, so it can be tested independently of orchestration.
    """

    async def check_preconditions(
        self,
        tool: Tool,
        context: ToolContext,
        arguments: JsonObject,
    ) -> CheckResult:
        try:
            async with asyncio.timeout(tool.spec.timeout_seconds):
                return await tool.check_preconditions(context, arguments)
        except TimeoutError:
            return CheckResult(
                passed=False,
                reason=f"precondition check for {tool.spec.name!r} timed out",
                retryable=True,
            )
        except Exception as exc:
            logger.warning(
                "tool precondition check failed",
                extra={
                    "tool": tool.spec.name,
                    "exception_type": type(exc).__name__,
                },
            )
            return CheckResult(
                passed=False,
                reason=f"precondition check failed with {type(exc).__name__}",
                details={"exception_type": type(exc).__name__},
            )

    async def invoke(
        self,
        tool: Tool,
        context: ToolContext,
        arguments: JsonObject,
    ) -> AttemptSuccess | AttemptFailure:
        try:
            async with asyncio.timeout(tool.spec.timeout_seconds):
                result = await tool.execute(context, arguments)
        except TimeoutError:
            return await self._resolve_ambiguous_outcome(
                tool,
                context,
                arguments,
                code="tool_timeout",
                message=f"tool {tool.spec.name!r} timed out",
            )
        except UnknownToolOutcome as exc:
            return await self._resolve_ambiguous_outcome(
                tool,
                context,
                arguments,
                code="unknown_tool_outcome",
                message=exc.message,
                details=exc.details,
            )
        except ToolExecutionError as exc:
            can_retry = exc.retryable and exc.safe_to_retry and self.repeat_is_safe(tool)
            return AttemptFailure(
                error=ErrorInfo(
                    code=self._tool_error_code(exc),
                    message=exc.message,
                    retryable=can_retry,
                    details=exc.details,
                ),
                can_retry=can_retry,
            )
        except Exception as exc:  # defensive boundary around third-party adapters
            logger.exception(
                "unexpected tool adapter failure",
                extra={"tool": tool.spec.name},
            )
            return AttemptFailure(
                error=ErrorInfo(
                    code="tool_adapter_error",
                    message=f"tool {tool.spec.name!r} failed unexpectedly",
                    retryable=False,
                    details={"exception_type": type(exc).__name__},
                ),
                can_retry=False,
            )

        verification = await self.verify(tool, context, arguments, result)
        if verification.outcome is VerificationOutcome.CONFIRMED_SUCCESS:
            return AttemptSuccess(
                result=ToolResult(
                    output=verification.observed_output or result.output,
                    metadata=result.metadata,
                ),
            )
        if verification.outcome is VerificationOutcome.CONFIRMED_NOT_APPLIED:
            can_retry = self.repeat_is_safe(tool)
            return AttemptFailure(
                error=ErrorInfo(
                    code="postcondition_not_applied",
                    message=verification.details,
                    retryable=can_retry,
                ),
                can_retry=can_retry,
            )

        can_retry = self.repeat_is_safe(tool)
        return AttemptFailure(
            error=ErrorInfo(
                code="postcondition_inconclusive",
                message=verification.details,
                retryable=can_retry,
            ),
            can_retry=can_retry,
        )

    async def verify(
        self,
        tool: Tool,
        context: ToolContext,
        arguments: JsonObject,
        result: ToolResult | None,
    ) -> VerificationResult:
        try:
            async with asyncio.timeout(tool.spec.timeout_seconds):
                return await tool.verify(context, arguments, result)
        except Exception as exc:
            # Verification failure must never turn into an unsafe retry.
            logger.warning(
                "tool verification failed",
                extra={
                    "tool": tool.spec.name,
                    "exception_type": type(exc).__name__,
                },
            )
            return VerificationResult(
                outcome=VerificationOutcome.INCONCLUSIVE,
                details=f"verification failed with {type(exc).__name__}",
            )

    async def _resolve_ambiguous_outcome(
        self,
        tool: Tool,
        context: ToolContext,
        arguments: JsonObject,
        *,
        code: str,
        message: str,
        details: JsonObject | None = None,
    ) -> AttemptSuccess | AttemptFailure:
        verification = await self.verify(tool, context, arguments, None)
        if verification.outcome is VerificationOutcome.CONFIRMED_SUCCESS:
            return AttemptSuccess(
                result=ToolResult(
                    output=verification.observed_output or {},
                    metadata={"recovered_from": code},
                ),
                recovered_by_verification=True,
            )
        if verification.outcome is VerificationOutcome.CONFIRMED_NOT_APPLIED:
            return AttemptFailure(
                error=ErrorInfo(
                    code=code,
                    message=message,
                    retryable=True,
                    details=details or {},
                ),
                can_retry=True,
            )

        can_retry = self.repeat_is_safe(tool)
        return AttemptFailure(
            error=ErrorInfo(
                code="ambiguous_tool_outcome",
                message=f"{message}; verification was inconclusive",
                retryable=can_retry,
                details={
                    **(details or {}),
                    "verification": verification.details,
                },
            ),
            can_retry=can_retry,
        )

    @staticmethod
    def repeat_is_safe(tool: Tool) -> bool:
        """Return whether repeating the same logical call is safe."""

        return tool.spec.effect is ToolEffect.READ or tool.spec.idempotent

    @staticmethod
    def _tool_error_code(error: ToolExecutionError) -> str:
        if isinstance(error, PermanentToolError):
            return "permanent_tool_error"
        return "transient_tool_error"
