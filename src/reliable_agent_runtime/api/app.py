"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from reliable_agent_runtime import __version__
from reliable_agent_runtime.api.dependencies import require_api_key
from reliable_agent_runtime.api.errors import install_exception_handlers
from reliable_agent_runtime.api.middleware import RequestIdMiddleware
from reliable_agent_runtime.api.openapi import PROTECTED_PROBLEM_RESPONSES
from reliable_agent_runtime.api.routes import actions, health, runs, tools
from reliable_agent_runtime.bootstrap import AppContainer, build_container
from reliable_agent_runtime.infrastructure.observability.logging import configure_logging
from reliable_agent_runtime.settings import Settings


def create_app(
    *,
    settings: Settings | None = None,
    container: AppContainer | None = None,
) -> FastAPI:
    resolved_container = container or build_container(settings)
    configure_logging(resolved_container.settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = resolved_container
        await resolved_container.initialize()
        try:
            yield
        finally:
            await resolved_container.close()

    app = FastAPI(
        title=resolved_container.settings.app_name,
        version=__version__,
        description=(
            "A planner-agnostic runtime for auditable, idempotent, verifiable, "
            "and compensatable tool execution in adaptive agents."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "health", "description": "Liveness and readiness checks."},
            {"name": "tools", "description": "Discover registered tool contracts."},
            {
                "name": "actions",
                "description": "Execute one action at a time from an adaptive planner.",
            },
            {"name": "runs", "description": "Create, execute, inspect, and approve runs."},
        ],
    )
    app.add_middleware(RequestIdMiddleware)
    if resolved_container.settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_container.settings.cors_origins),
            allow_credentials=False,
            allow_methods=["GET", "POST"],
            allow_headers=["Content-Type", "Idempotency-Key", "X-API-Key", "X-Request-ID"],
            expose_headers=["ETag", "Location", "X-Request-ID"],
        )

    install_exception_handlers(app)
    app.include_router(health.router)
    protected = APIRouter(
        prefix="/api/v1",
        dependencies=[Depends(require_api_key)],
        responses=PROTECTED_PROBLEM_RESPONSES,
    )
    protected.include_router(tools.router)
    protected.include_router(actions.router)
    protected.include_router(runs.router)
    app.include_router(protected)
    return app


app = create_app()
