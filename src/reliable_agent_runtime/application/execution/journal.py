"""Optimistic aggregate persistence for the execution application layer."""

from __future__ import annotations

from dataclasses import dataclass

from reliable_agent_runtime.application.ports import Clock, RuntimeStore
from reliable_agent_runtime.domain.models import AgentRun, Approval, RuntimeEvent


@dataclass(frozen=True, slots=True)
class RunJournal:
    """Persist a mutated run together with its audit records atomically.

    Domain objects stay persistence-agnostic. This service is the only execution
    component that advances aggregate versions and timestamps, which keeps
    optimistic concurrency bookkeeping out of orchestration code.
    """

    store: RuntimeStore
    clock: Clock

    async def save(
        self,
        run: AgentRun,
        *,
        events: tuple[RuntimeEvent, ...] = (),
        approvals: tuple[Approval, ...] = (),
    ) -> None:
        expected_version = run.version
        previous_updated_at = run.updated_at
        run.version = expected_version + 1
        run.updated_at = self.clock.now()
        try:
            await self.store.save_run(
                run,
                expected_version=expected_version,
                events=events,
                approvals=approvals,
            )
        except Exception:
            # Keep the in-memory aggregate consistent when a persistence call
            # fails and the caller decides to retry or report the error.
            run.version = expected_version
            run.updated_at = previous_updated_at
            raise
