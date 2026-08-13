"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from reliable_agent_runtime.api.dependencies import get_container
from reliable_agent_runtime.api.openapi import problem_response
from reliable_agent_runtime.api.schemas import HealthResponse
from reliable_agent_runtime.bootstrap import AppContainer

router = APIRouter(tags=["health"])


@router.get(
    "/health/live",
    response_model=HealthResponse,
    operation_id="get_liveness",
    summary="Check process liveness",
)
async def liveness(
    container: Annotated[AppContainer, Depends(get_container)],
) -> HealthResponse:
    return HealthResponse(
        status="ok",
        service=container.settings.app_name,
        environment=container.settings.environment,
    )


@router.get(
    "/health/ready",
    response_model=HealthResponse,
    operation_id="get_readiness",
    summary="Check runtime storage readiness",
    responses={503: problem_response("Runtime store is unavailable")},
)
async def readiness(
    container: Annotated[AppContainer, Depends(get_container)],
) -> HealthResponse:
    if not await container.store.ping():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="runtime store is unavailable",
        )
    return HealthResponse(
        status="ready",
        service=container.settings.app_name,
        environment=container.settings.environment,
    )
