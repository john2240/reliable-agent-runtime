"""Adaptive action endpoint for agents that plan one step at a time."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Response, status

from reliable_agent_runtime.api.dependencies import get_action_service
from reliable_agent_runtime.api.schemas import ExecuteActionRequest, RunResponse
from reliable_agent_runtime.application.actions import ActionService

router = APIRouter(tags=["actions"])


def _set_resource_headers(response: Response, run_id: str, version: int) -> None:
    response.headers["ETag"] = f'W/"{version}"'
    response.headers["Location"] = f"/api/v1/runs/{run_id}"


@router.post(
    "/actions",
    response_model=RunResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="execute_adaptive_agent_action",
    summary="Execute one planner-proposed action",
    responses={200: {"description": "Existing idempotent action returned"}},
)
async def execute_action(
    request: ExecuteActionRequest,
    response: Response,
    service: Annotated[ActionService, Depends(get_action_service)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=200),
    ] = None,
) -> RunResponse:
    result = await service.execute_action(
        objective=request.objective,
        action_id=request.action_id,
        tool_name=request.tool,
        arguments=request.arguments,
        actor=request.actor,
        description=request.description,
        idempotency_key=idempotency_key,
    )
    response.status_code = status.HTTP_201_CREATED if result.created else status.HTTP_200_OK
    _set_resource_headers(response, result.run.id, result.run.version)
    return RunResponse.from_domain(result.run)
