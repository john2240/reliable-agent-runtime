"""Run, event, and approval API endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Response, status

from reliable_agent_runtime.api.dependencies import get_execution_engine, get_run_service
from reliable_agent_runtime.api.schemas import (
    ApprovalDecisionRequest,
    ApprovalResponse,
    CreateRunRequest,
    RunResponse,
    RuntimeEventResponse,
)
from reliable_agent_runtime.application.engine import ExecutionEngine
from reliable_agent_runtime.application.service import RunService

router = APIRouter(tags=["runs"])


def _set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'W/"{version}"'


def _set_created_resource_headers(response: Response, run_id: str, version: int) -> None:
    _set_etag(response, version)
    response.headers["Location"] = f"/api/v1/runs/{run_id}"


@router.post(
    "/runs",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="create_agent_run",
    summary="Create an agent run",
    responses={200: {"description": "Existing idempotent run returned"}},
)
async def create_run(
    request: CreateRunRequest,
    response: Response,
    service: Annotated[RunService, Depends(get_run_service)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=200),
    ] = None,
) -> RunResponse:
    result = await service.create_run(
        objective=request.objective,
        plan=request.plan.to_domain(),
        input_data=request.input,
        actor=request.actor,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    _set_created_resource_headers(response, result.run.id, result.run.version)
    return RunResponse.from_domain(result.run)


@router.get(
    "/runs/{run_id}",
    response_model=RunResponse,
    operation_id="get_agent_run",
    summary="Get an agent run snapshot",
)
async def get_run(
    run_id: str,
    response: Response,
    service: Annotated[RunService, Depends(get_run_service)],
) -> RunResponse:
    run = await service.get_run(run_id)
    _set_etag(response, run.version)
    return RunResponse.from_domain(run)


@router.post(
    "/runs/{run_id}/execute",
    response_model=RunResponse,
    operation_id="execute_agent_run",
    summary="Advance an agent run",
)
async def execute_run(
    run_id: str,
    response: Response,
    engine: Annotated[ExecutionEngine, Depends(get_execution_engine)],
) -> RunResponse:
    run = await engine.execute(run_id)
    _set_etag(response, run.version)
    return RunResponse.from_domain(run)


@router.get(
    "/runs/{run_id}/events",
    response_model=list[RuntimeEventResponse],
    operation_id="list_agent_run_events",
    summary="List ordered run events",
)
async def list_events(
    run_id: str,
    service: Annotated[RunService, Depends(get_run_service)],
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[RuntimeEventResponse]:
    events = await service.list_events(
        run_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    return [RuntimeEventResponse.from_domain(event) for event in events]


@router.get(
    "/runs/{run_id}/approvals",
    response_model=list[ApprovalResponse],
    operation_id="list_agent_run_approvals",
    summary="List run approvals",
)
async def list_approvals(
    run_id: str,
    service: Annotated[RunService, Depends(get_run_service)],
) -> list[ApprovalResponse]:
    approvals = await service.list_approvals(run_id)
    return [ApprovalResponse.from_domain(approval) for approval in approvals]


@router.post(
    "/approvals/{approval_id}/decision",
    response_model=ApprovalResponse,
    operation_id="decide_agent_run_approval",
    summary="Approve or deny a pending action",
)
async def decide_approval(
    approval_id: str,
    request: ApprovalDecisionRequest,
    service: Annotated[RunService, Depends(get_run_service)],
) -> ApprovalResponse:
    approval = await service.decide_approval(
        approval_id=approval_id,
        decision=request.decision,
        actor=request.actor,
        reason=request.reason,
    )
    return ApprovalResponse.from_domain(approval)
