"""Factories for consistent runtime audit events."""

from __future__ import annotations

from dataclasses import dataclass

from reliable_agent_runtime.application.ports import Clock, IdGenerator
from reliable_agent_runtime.domain.enums import EventType
from reliable_agent_runtime.domain.models import RuntimeEvent
from reliable_agent_runtime.domain.types import JsonObject


@dataclass(frozen=True, slots=True)
class EventFactory:
    """Create timestamped, uniquely identified audit events."""

    clock: Clock
    ids: IdGenerator

    def create(
        self,
        *,
        run_id: str,
        event_type: EventType,
        step_id: str | None = None,
        payload: JsonObject | None = None,
    ) -> RuntimeEvent:
        return RuntimeEvent(
            id=self.ids.new("evt"),
            run_id=run_id,
            event_type=event_type,
            created_at=self.clock.now(),
            step_id=step_id,
            payload=payload or {},
        )
