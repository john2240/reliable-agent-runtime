"""Serialization boundary between dataclass domain models and JSON storage."""

from __future__ import annotations

from typing import Any, cast

from pydantic import TypeAdapter

from reliable_agent_runtime.domain import models as domain_models
from reliable_agent_runtime.domain import types as domain_types
from reliable_agent_runtime.domain.models import AgentRun, Approval, RuntimeEvent

_TYPES_NAMESPACE = {
    **vars(domain_models),
    **vars(domain_types),
}

_RUN_ADAPTER = TypeAdapter(AgentRun)
_APPROVAL_ADAPTER = TypeAdapter(Approval)
_EVENT_ADAPTER = TypeAdapter(RuntimeEvent)
for _adapter in (_RUN_ADAPTER, _APPROVAL_ADAPTER, _EVENT_ADAPTER):
    _adapter.rebuild(force=True, _types_namespace=_TYPES_NAMESPACE)


def encode_run(run: AgentRun) -> dict[str, Any]:
    return cast(dict[str, Any], _RUN_ADAPTER.dump_python(run, mode="json"))


def decode_run(payload: dict[str, Any]) -> AgentRun:
    return _RUN_ADAPTER.validate_python(payload)


def encode_approval(approval: Approval) -> dict[str, Any]:
    return cast(dict[str, Any], _APPROVAL_ADAPTER.dump_python(approval, mode="json"))


def decode_approval(payload: dict[str, Any]) -> Approval:
    return _APPROVAL_ADAPTER.validate_python(payload)


def encode_event(event: RuntimeEvent) -> dict[str, Any]:
    return cast(dict[str, Any], _EVENT_ADAPTER.dump_python(event, mode="json"))


def decode_event(payload: dict[str, Any]) -> RuntimeEvent:
    return _EVENT_ADAPTER.validate_python(payload)
