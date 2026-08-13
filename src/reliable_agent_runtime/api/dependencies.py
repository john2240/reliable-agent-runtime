"""FastAPI dependency providers."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from reliable_agent_runtime.application.actions import ActionService
from reliable_agent_runtime.application.engine import ExecutionEngine
from reliable_agent_runtime.application.service import RunService
from reliable_agent_runtime.bootstrap import AppContainer

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def get_container(request: Request) -> AppContainer:
    return request.app.state.container


def get_run_service(
    container: Annotated[AppContainer, Depends(get_container)],
) -> RunService:
    return container.run_service


def get_action_service(
    container: Annotated[AppContainer, Depends(get_container)],
) -> ActionService:
    return container.action_service


def get_execution_engine(
    container: Annotated[AppContainer, Depends(get_container)],
) -> ExecutionEngine:
    return container.execution_engine


async def require_api_key(
    request: Request,
    supplied_key: Annotated[str | None, Depends(_api_key_header)],
) -> None:
    configured_key = get_container(request).settings.api_key
    if configured_key is None:
        return
    if supplied_key is None or not secrets.compare_digest(supplied_key, configured_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
