from __future__ import annotations

import pytest

from reliable_agent_runtime.application.template import TemplateResolver
from reliable_agent_runtime.domain.errors import TemplateResolutionError


def test_full_placeholder_preserves_native_type() -> None:
    resolver = TemplateResolver()
    context = {
        "input": {"amount": 12900},
        "steps": {"lookup": {"output": {"eligible": True}}},
    }

    resolved = resolver.resolve_arguments(
        {
            "amount_cents": "${input.amount}",
            "eligible": "${steps.lookup.output.eligible}",
            "message": "amount=${input.amount}",
        },
        context,
    )

    assert resolved == {
        "amount_cents": 12900,
        "eligible": True,
        "message": "amount=12900",
    }


def test_missing_placeholder_fails_closed() -> None:
    with pytest.raises(TemplateResolutionError, match="does not exist"):
        TemplateResolver().resolve_arguments(
            {"value": "${steps.missing.output.value}"},
            {"input": {}, "steps": {}},
        )
