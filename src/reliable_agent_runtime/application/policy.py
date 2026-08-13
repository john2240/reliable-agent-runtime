"""Composable runtime policies for side-effecting tool calls."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from reliable_agent_runtime.domain.enums import ToolEffect
from reliable_agent_runtime.domain.models import AgentRun, ToolSpec
from reliable_agent_runtime.domain.types import JsonObject


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """Final policy result consumed by the execution engine."""

    allowed: bool = True
    approval_required: bool = False
    reason: str | None = None


class PolicyRule(Protocol):
    """One independently testable policy rule."""

    def evaluate(
        self,
        *,
        run: AgentRun,
        tool: ToolSpec,
        arguments: JsonObject,
    ) -> PolicyDecision:
        """Evaluate one tool call."""


@dataclass(frozen=True, slots=True)
class IrreversibleActionsRequireApproval:
    """Require a human decision for actions that cannot be compensated."""

    reason: str = "irreversible actions require explicit human approval"

    def evaluate(
        self,
        *,
        run: AgentRun,
        tool: ToolSpec,
        arguments: JsonObject,
    ) -> PolicyDecision:
        del run, arguments
        if tool.effect is ToolEffect.IRREVERSIBLE:
            return PolicyDecision(approval_required=True, reason=self.reason)
        return PolicyDecision()


@dataclass(frozen=True, slots=True)
class DeclaredToolApproval:
    """Honor approval requirements declared by a tool adapter."""

    def evaluate(
        self,
        *,
        run: AgentRun,
        tool: ToolSpec,
        arguments: JsonObject,
    ) -> PolicyDecision:
        del run, arguments
        if tool.requires_approval:
            return PolicyDecision(
                approval_required=True,
                reason=f"tool {tool.name!r} requires approval",
            )
        return PolicyDecision()


@dataclass(frozen=True, slots=True)
class CompositePolicyEngine:
    """Aggregate policy rules using deny-first, approval-second semantics."""

    rules: Sequence[PolicyRule]

    def evaluate(
        self,
        *,
        run: AgentRun,
        tool: ToolSpec,
        arguments: JsonObject,
    ) -> PolicyDecision:
        approval_reasons: list[str] = []
        for rule in self.rules:
            decision = rule.evaluate(run=run, tool=tool, arguments=arguments)
            if not decision.allowed:
                return decision
            if decision.approval_required and decision.reason:
                approval_reasons.append(decision.reason)

        if approval_reasons:
            return PolicyDecision(
                approval_required=True,
                reason="; ".join(dict.fromkeys(approval_reasons)),
            )
        return PolicyDecision()


def default_policy_engine() -> CompositePolicyEngine:
    """Build the secure-by-default policy set."""

    return CompositePolicyEngine(
        rules=(
            IrreversibleActionsRequireApproval(),
            DeclaredToolApproval(),
        ),
    )
