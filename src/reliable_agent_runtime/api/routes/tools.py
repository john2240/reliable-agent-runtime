"""Tool discovery endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from reliable_agent_runtime.api.dependencies import get_container
from reliable_agent_runtime.api.schemas import ToolResponse
from reliable_agent_runtime.bootstrap import AppContainer

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get(
    "",
    response_model=list[ToolResponse],
    operation_id="list_tool_contracts",
    summary="List registered tool contracts",
)
async def list_tools(
    container: Annotated[AppContainer, Depends(get_container)],
) -> list[ToolResponse]:
    return [
        ToolResponse(
            name=tool.spec.name,
            version=tool.spec.version,
            description=tool.spec.description,
            effect=tool.spec.effect,
            idempotent=tool.spec.idempotent,
            requires_approval=tool.spec.requires_approval,
            supports_compensation=tool.supports_compensation,
            timeout_seconds=tool.spec.timeout_seconds,
            max_attempts=tool.spec.max_attempts,
            tags=list(tool.spec.tags),
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
        )
        for tool in container.tools.list()
    ]
