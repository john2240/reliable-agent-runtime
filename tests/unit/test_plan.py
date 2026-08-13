from __future__ import annotations

import pytest

from reliable_agent_runtime.domain.errors import PlanValidationError
from reliable_agent_runtime.domain.models import ExecutionPlan, PlanStep


def test_topological_order_is_stable() -> None:
    plan = ExecutionPlan(
        id="stable_plan",
        name="Stable plan",
        steps=(
            PlanStep(id="first", tool_name="demo.read", arguments={}),
            PlanStep(id="second", tool_name="demo.read", arguments={}),
            PlanStep(
                id="third",
                tool_name="demo.write",
                arguments={},
                depends_on=("first", "second"),
            ),
        ),
    )

    assert [step.id for step in plan.topological_steps()] == ["first", "second", "third"]


def test_terminal_steps_support_multiple_dag_sinks() -> None:
    plan = ExecutionPlan(
        id="parallel_results",
        name="Parallel result branches",
        steps=(
            PlanStep(id="root", tool_name="demo.read", arguments={}),
            PlanStep(
                id="left",
                tool_name="demo.write",
                arguments={},
                depends_on=("root",),
            ),
            PlanStep(
                id="right",
                tool_name="demo.write",
                arguments={},
                depends_on=("root",),
            ),
        ),
    )

    assert [step.id for step in plan.terminal_steps()] == ["left", "right"]


def test_plan_defensively_copies_planner_owned_arguments() -> None:
    arguments = {"nested": {"value": 1}}
    step = PlanStep(id="read", tool_name="demo.read", arguments=arguments)

    arguments["nested"]["value"] = 99

    assert step.arguments == {"nested": {"value": 1}}


def test_plan_rejects_dependency_cycle() -> None:
    with pytest.raises(PlanValidationError, match="cycle"):
        ExecutionPlan(
            id="cyclic_plan",
            name="Cyclic plan",
            steps=(
                PlanStep(
                    id="first",
                    tool_name="demo.read",
                    arguments={},
                    depends_on=("second",),
                ),
                PlanStep(
                    id="second",
                    tool_name="demo.read",
                    arguments={},
                    depends_on=("first",),
                ),
            ),
        )


def test_plan_rejects_unknown_dependency() -> None:
    with pytest.raises(PlanValidationError, match="unknown"):
        ExecutionPlan(
            id="invalid_plan",
            name="Invalid plan",
            steps=(
                PlanStep(
                    id="first",
                    tool_name="demo.read",
                    arguments={},
                    depends_on=("missing",),
                ),
            ),
        )
