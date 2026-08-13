"""Transactional SQLAlchemy implementation of the runtime store port."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reliable_agent_runtime.domain.enums import ApprovalDecision, ApprovalStatus
from reliable_agent_runtime.domain.errors import (
    ApprovalAlreadyDecidedError,
    ApprovalNotFoundError,
    ConcurrentUpdateError,
    ConflictError,
    RunNotFoundError,
)
from reliable_agent_runtime.domain.models import AgentRun, Approval, RuntimeEvent
from reliable_agent_runtime.infrastructure.persistence.codec import (
    decode_approval,
    decode_event,
    decode_run,
    encode_approval,
    encode_event,
    encode_run,
)
from reliable_agent_runtime.infrastructure.persistence.database import Database
from reliable_agent_runtime.infrastructure.persistence.models import (
    ApprovalRecord,
    EventRecord,
    RunRecord,
)


class SqlAlchemyRuntimeStore:
    """Persist each aggregate mutation and its audit events in one transaction."""

    def __init__(self, database: Database) -> None:
        self._database = database

    async def initialize(self) -> None:
        await self._database.initialize()

    async def close(self) -> None:
        await self._database.close()

    async def ping(self) -> bool:
        return await self._database.ping()

    async def create_run(
        self,
        run: AgentRun,
        *,
        events: Sequence[RuntimeEvent],
    ) -> None:
        await asyncio.to_thread(self._create_run_sync, run, tuple(events))

    def _create_run_sync(self, run: AgentRun, events: tuple[RuntimeEvent, ...]) -> None:
        try:
            with self._database.sessions.begin() as session:
                session.add(self._run_record(run))
                self._insert_events(session, run.id, events)
        except IntegrityError as exc:
            raise ConflictError(
                f"run {run.id!r} already exists",
                details={"run_id": run.id},
            ) from exc

    async def get_run(self, run_id: str) -> AgentRun:
        return await asyncio.to_thread(self._get_run_sync, run_id)

    def _get_run_sync(self, run_id: str) -> AgentRun:
        with self._database.sessions() as session:
            record = session.get(RunRecord, run_id)
            if record is None:
                raise RunNotFoundError(
                    f"run {run_id!r} does not exist",
                    details={"run_id": run_id},
                )
            return decode_run(record.payload)

    async def save_run(
        self,
        run: AgentRun,
        *,
        expected_version: int,
        events: Sequence[RuntimeEvent] = (),
        approvals: Sequence[Approval] = (),
    ) -> None:
        await asyncio.to_thread(
            self._save_run_sync,
            run,
            expected_version,
            tuple(events),
            tuple(approvals),
        )

    def _save_run_sync(
        self,
        run: AgentRun,
        expected_version: int,
        events: tuple[RuntimeEvent, ...],
        approvals: tuple[Approval, ...],
    ) -> None:
        if run.version != expected_version + 1:
            raise ValueError("run.version must equal expected_version + 1")

        try:
            with self._database.sessions.begin() as session:
                statement = (
                    update(RunRecord)
                    .where(
                        RunRecord.id == run.id,
                        RunRecord.version == expected_version,
                    )
                    .values(
                        version=run.version,
                        status=run.status.value,
                        objective=run.objective,
                        actor=run.actor,
                        request_fingerprint=run.request_fingerprint,
                        payload=encode_run(run),
                        updated_at=run.updated_at,
                    )
                )
                result = session.execute(statement)
                if result.rowcount != 1:
                    exists = session.get(RunRecord, run.id)
                    if exists is None:
                        raise RunNotFoundError(
                            f"run {run.id!r} does not exist",
                            details={"run_id": run.id},
                        )
                    raise ConcurrentUpdateError(
                        f"run {run.id!r} was updated concurrently",
                        details={
                            "run_id": run.id,
                            "expected_version": expected_version,
                            "actual_version": exists.version,
                        },
                    )

                for approval in approvals:
                    session.add(self._approval_record(approval))
                self._insert_events(session, run.id, events)
        except IntegrityError as exc:
            raise ConflictError(
                "persistence constraint was violated",
                details={"run_id": run.id},
            ) from exc

    async def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> tuple[RuntimeEvent, ...]:
        return await asyncio.to_thread(
            self._list_events_sync,
            run_id,
            after_sequence,
            limit,
        )

    def _list_events_sync(
        self,
        run_id: str,
        after_sequence: int,
        limit: int,
    ) -> tuple[RuntimeEvent, ...]:
        with self._database.sessions() as session:
            if session.get(RunRecord, run_id) is None:
                raise RunNotFoundError(
                    f"run {run_id!r} does not exist",
                    details={"run_id": run_id},
                )
            statement = (
                select(EventRecord)
                .where(
                    EventRecord.run_id == run_id,
                    EventRecord.sequence > after_sequence,
                )
                .order_by(EventRecord.sequence)
                .limit(limit)
            )
            records = session.scalars(statement).all()
            return tuple(decode_event(record.payload) for record in records)

    async def get_approval(self, approval_id: str) -> Approval:
        return await asyncio.to_thread(self._get_approval_sync, approval_id)

    def _get_approval_sync(self, approval_id: str) -> Approval:
        with self._database.sessions() as session:
            record = session.get(ApprovalRecord, approval_id)
            if record is None:
                raise ApprovalNotFoundError(
                    f"approval {approval_id!r} does not exist",
                    details={"approval_id": approval_id},
                )
            return decode_approval(record.payload)

    async def list_approvals(self, run_id: str) -> tuple[Approval, ...]:
        return await asyncio.to_thread(self._list_approvals_sync, run_id)

    def _list_approvals_sync(self, run_id: str) -> tuple[Approval, ...]:
        with self._database.sessions() as session:
            if session.get(RunRecord, run_id) is None:
                raise RunNotFoundError(
                    f"run {run_id!r} does not exist",
                    details={"run_id": run_id},
                )
            statement = (
                select(ApprovalRecord)
                .where(ApprovalRecord.run_id == run_id)
                .order_by(ApprovalRecord.requested_at)
            )
            records = session.scalars(statement).all()
            return tuple(decode_approval(record.payload) for record in records)

    async def decide_approval(
        self,
        approval: Approval,
        *,
        decision: ApprovalDecision,
        event: RuntimeEvent,
    ) -> Approval:
        return await asyncio.to_thread(
            self._decide_approval_sync,
            approval,
            decision,
            event,
        )

    def _decide_approval_sync(
        self,
        approval: Approval,
        decision: ApprovalDecision,
        event: RuntimeEvent,
    ) -> Approval:
        expected_status = (
            ApprovalStatus.APPROVED
            if decision is ApprovalDecision.APPROVE
            else ApprovalStatus.DENIED
        )
        if approval.status is not expected_status:
            raise ValueError("approval status does not match decision")

        with self._database.sessions.begin() as session:
            record = session.get(ApprovalRecord, approval.id)
            if record is None:
                raise ApprovalNotFoundError(
                    f"approval {approval.id!r} does not exist",
                    details={"approval_id": approval.id},
                )
            current = decode_approval(record.payload)
            if current.status is not ApprovalStatus.PENDING:
                raise ApprovalAlreadyDecidedError(
                    f"approval {approval.id!r} was already decided",
                    details={"approval_id": approval.id, "status": current.status.value},
                )

            record.status = approval.status.value
            record.payload = encode_approval(approval)
            record.decided_at = approval.decided_at
            self._insert_events(session, approval.run_id, (event,))
            return approval

    @staticmethod
    def _run_record(run: AgentRun) -> RunRecord:
        return RunRecord(
            id=run.id,
            version=run.version,
            status=run.status.value,
            objective=run.objective,
            actor=run.actor,
            request_fingerprint=run.request_fingerprint,
            payload=encode_run(run),
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    @staticmethod
    def _approval_record(approval: Approval) -> ApprovalRecord:
        return ApprovalRecord(
            id=approval.id,
            run_id=approval.run_id,
            step_id=approval.step_id,
            status=approval.status.value,
            payload=encode_approval(approval),
            requested_at=approval.requested_at,
            decided_at=approval.decided_at,
        )

    @staticmethod
    def _insert_events(
        session: Session,
        run_id: str,
        events: Sequence[RuntimeEvent],
    ) -> None:
        if not events:
            return
        current = session.scalar(
            select(func.coalesce(func.max(EventRecord.sequence), 0)).where(
                EventRecord.run_id == run_id,
            ),
        )
        sequence = int(current or 0)
        for event in events:
            sequence += 1
            sequenced = replace(event, sequence=sequence)
            session.add(
                EventRecord(
                    id=sequenced.id,
                    run_id=sequenced.run_id,
                    sequence=sequence,
                    event_type=sequenced.event_type.value,
                    step_id=sequenced.step_id,
                    payload=encode_event(sequenced),
                    created_at=sequenced.created_at,
                ),
            )
