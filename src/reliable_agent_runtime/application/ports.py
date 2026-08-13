"""Dependency inversion ports used by the application layer."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol

from reliable_agent_runtime.domain.enums import ApprovalDecision
from reliable_agent_runtime.domain.models import (
    AgentRun,
    Approval,
    CheckResult,
    RuntimeEvent,
    ToolContext,
    ToolResult,
    ToolSpec,
    VerificationResult,
)
from reliable_agent_runtime.domain.types import JsonObject


class Clock(Protocol):
    """Provides wall-clock time for deterministic tests."""

    def now(self) -> datetime:
        """Return a timezone-aware datetime."""


class Sleeper(Protocol):
    """Suspends retry loops and can be replaced by a deterministic test double."""

    async def sleep(self, seconds: float) -> None:
        """Suspend for the requested delay."""


class IdGenerator(Protocol):
    """Generates random and deterministic resource identifiers."""

    def new(self, prefix: str) -> str:
        """Return a new unique identifier."""

    def deterministic(self, prefix: str, key: str) -> str:
        """Return a stable identifier for an idempotency key."""


class Tool(Protocol):
    """Framework-independent tool adapter contract."""

    @property
    def spec(self) -> ToolSpec:
        """Return static tool metadata."""

    @property
    def input_schema(self) -> JsonObject:
        """Return JSON Schema for discovery and validation clients."""

    @property
    def output_schema(self) -> JsonObject:
        """Return JSON Schema for the normalized tool output."""

    @property
    def supports_compensation(self) -> bool:
        """Whether a successful write can be reversed."""

    async def validate_arguments(self, arguments: JsonObject) -> JsonObject:
        """Validate and normalize planner-supplied arguments."""

    async def check_preconditions(
        self,
        context: ToolContext,
        arguments: JsonObject,
    ) -> CheckResult:
        """Check external state immediately before execution."""

    async def execute(
        self,
        context: ToolContext,
        arguments: JsonObject,
    ) -> ToolResult:
        """Execute the tool once using the supplied idempotency key."""

    async def verify(
        self,
        context: ToolContext,
        arguments: JsonObject,
        result: ToolResult | None,
    ) -> VerificationResult:
        """Verify postconditions or recover an ambiguous call outcome."""

    async def compensate(
        self,
        context: ToolContext,
        arguments: JsonObject,
        result: ToolResult,
    ) -> ToolResult:
        """Reverse a successful write when supported."""


class ToolRegistry(Protocol):
    """Resolves tools without coupling the runtime to concrete adapters."""

    def get(self, name: str) -> Tool:
        """Return a registered tool or raise ToolNotFoundError."""

    def list(self) -> tuple[Tool, ...]:
        """Return all registered tools in deterministic order."""


class PolicyDecisionResult(Protocol):
    """Structural protocol for policy results."""

    allowed: bool
    approval_required: bool
    reason: str | None


class PolicyEngine(Protocol):
    """Evaluates whether a resolved call may execute."""

    def evaluate(
        self,
        *,
        run: AgentRun,
        tool: ToolSpec,
        arguments: JsonObject,
    ) -> PolicyDecisionResult:
        """Return allow/deny and approval requirements."""


class RuntimeStore(Protocol):
    """Transactional persistence boundary for runs, events, and approvals."""

    async def initialize(self) -> None:
        """Create required storage structures."""

    async def close(self) -> None:
        """Release storage resources."""

    async def ping(self) -> bool:
        """Check storage availability."""

    async def create_run(
        self,
        run: AgentRun,
        *,
        events: Sequence[RuntimeEvent],
    ) -> None:
        """Persist a new aggregate and initial events atomically."""

    async def get_run(self, run_id: str) -> AgentRun:
        """Load a run aggregate."""

    async def save_run(
        self,
        run: AgentRun,
        *,
        expected_version: int,
        events: Sequence[RuntimeEvent] = (),
        approvals: Sequence[Approval] = (),
    ) -> None:
        """Optimistically save a run and related records atomically."""

    async def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[RuntimeEvent, ...]:
        """Return ordered audit events."""

    async def get_approval(self, approval_id: str) -> Approval:
        """Load one approval request."""

    async def list_approvals(self, run_id: str) -> tuple[Approval, ...]:
        """Return all approvals for a run."""

    async def decide_approval(
        self,
        approval: Approval,
        *,
        decision: ApprovalDecision,
        event: RuntimeEvent,
    ) -> Approval:
        """Persist a one-time human decision and its audit event atomically."""


class RunLockManager(Protocol):
    """Serializes execution of one run within a process."""

    def lock(self, run_id: str) -> AbstractAsyncContextManager[None]:
        """Return an async context manager for a per-run lock."""
