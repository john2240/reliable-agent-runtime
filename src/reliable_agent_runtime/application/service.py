"""Use cases for creating, querying, and approving agent runs."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace

from reliable_agent_runtime.application.events import EventFactory
from reliable_agent_runtime.application.ports import (
    Clock,
    IdGenerator,
    RunLockManager,
    RuntimeStore,
)
from reliable_agent_runtime.domain.enums import (
    ApprovalDecision,
    ApprovalStatus,
    EventType,
)
from reliable_agent_runtime.domain.errors import (
    ConflictError,
    IdempotencyConflictError,
    InvalidRunStateError,
    ValidationError,
)
from reliable_agent_runtime.domain.models import (
    AgentRun,
    Approval,
    ExecutionPlan,
    RuntimeEvent,
)
from reliable_agent_runtime.domain.types import JsonObject


@dataclass(frozen=True, slots=True)
class CreateRunResult:
    """Return both the aggregate and whether it was newly created."""

    run: AgentRun
    created: bool


@dataclass(frozen=True, slots=True)
class RunService:
    """Application service for non-execution run lifecycle operations."""

    store: RuntimeStore
    locks: RunLockManager
    clock: Clock
    ids: IdGenerator
    events: EventFactory

    async def create_run(
        self,
        *,
        objective: str,
        plan: ExecutionPlan,
        input_data: JsonObject,
        actor: str,
        idempotency_key: str | None = None,
    ) -> CreateRunResult:
        normalized_objective = objective.strip()
        normalized_actor = actor.strip()
        if not normalized_objective:
            raise ValidationError("objective must not be blank")
        if not normalized_actor:
            raise ValidationError("actor must not be blank")
        if idempotency_key is not None and not idempotency_key.strip():
            raise ValidationError("Idempotency-Key must not be blank")

        fingerprint = self._request_fingerprint(
            objective=normalized_objective,
            plan=plan,
            input_data=input_data,
            actor=normalized_actor,
        )
        run_id = (
            self.ids.deterministic("run", idempotency_key.strip())
            if idempotency_key
            else self.ids.new("run")
        )
        run = AgentRun.create(
            run_id=run_id,
            objective=normalized_objective,
            plan=plan,
            input_data=input_data,
            actor=normalized_actor,
            request_fingerprint=fingerprint,
            now=self.clock.now(),
        )
        event = self.events.create(
            run_id=run.id,
            event_type=EventType.RUN_CREATED,
            payload={"plan_id": plan.id, "actor": normalized_actor},
        )

        try:
            await self.store.create_run(run, events=(event,))
        except ConflictError:
            if not idempotency_key:
                raise
            existing = await self.store.get_run(run_id)
            if existing.request_fingerprint != fingerprint:
                raise IdempotencyConflictError(
                    "Idempotency-Key was already used for a different request",
                    details={"run_id": run_id},
                ) from None
            return CreateRunResult(run=existing, created=False)

        return CreateRunResult(run=run, created=True)

    async def get_run(self, run_id: str) -> AgentRun:
        return await self.store.get_run(run_id)

    async def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[RuntimeEvent, ...]:
        await self.store.get_run(run_id)
        return await self.store.list_events(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def list_approvals(self, run_id: str) -> tuple[Approval, ...]:
        await self.store.get_run(run_id)
        return await self.store.list_approvals(run_id)

    async def decide_approval(
        self,
        *,
        approval_id: str,
        decision: ApprovalDecision,
        actor: str,
        reason: str | None,
    ) -> Approval:
        normalized_actor = actor.strip()
        if not normalized_actor:
            raise ValidationError("approval actor must not be blank")

        current = await self.store.get_approval(approval_id)
        async with self.locks.lock(current.run_id):
            # Re-read inside the run-level critical section. This makes the
            # one-time decision check and event append consistent with local
            # execution while the store remains the final concurrency guard.
            current = await self.store.get_approval(approval_id)
            run = await self.store.get_run(current.run_id)
            if run.status.is_terminal:
                raise InvalidRunStateError(
                    f"cannot decide approval for terminal run {run.id!r}",
                    details={"run_id": run.id, "status": run.status.value},
                )

            status = (
                ApprovalStatus.APPROVED
                if decision is ApprovalDecision.APPROVE
                else ApprovalStatus.DENIED
            )
            updated = replace(
                current,
                status=status,
                decided_at=self.clock.now(),
                decided_by=normalized_actor,
                decision_reason=reason.strip() if reason else None,
            )
            event_type = (
                EventType.APPROVAL_APPROVED
                if decision is ApprovalDecision.APPROVE
                else EventType.APPROVAL_DENIED
            )
            event = self.events.create(
                run_id=current.run_id,
                step_id=current.step_id,
                event_type=event_type,
                payload={
                    "approval_id": current.id,
                    "decided_by": normalized_actor,
                    "reason": updated.decision_reason,
                },
            )
            return await self.store.decide_approval(
                updated,
                decision=decision,
                event=event,
            )

    @staticmethod
    def _request_fingerprint(
        *,
        objective: str,
        plan: ExecutionPlan,
        input_data: JsonObject,
        actor: str,
    ) -> str:
        canonical = json.dumps(
            {
                "objective": objective,
                "plan": asdict(plan),
                "input": input_data,
                "actor": actor,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
