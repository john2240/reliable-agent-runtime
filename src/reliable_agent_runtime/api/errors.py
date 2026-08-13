"""Exception-to-HTTP mapping using RFC 9457 problem details."""

from __future__ import annotations

import logging
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from reliable_agent_runtime.api.schemas import ProblemDetail
from reliable_agent_runtime.domain.errors import (
    ConflictError,
    NotFoundError,
    PolicyViolationError,
    ReliableAgentError,
    ValidationError,
)

logger = logging.getLogger(__name__)


def _problem_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    detail: str,
    errors: list[dict] | None = None,
) -> JSONResponse:
    title = HTTPStatus(status_code).phrase
    problem = ProblemDetail(
        type=f"urn:reliable-agent-runtime:problem:{code}",
        title=title,
        status=status_code,
        detail=detail,
        instance=str(request.url.path),
        code=code,
        request_id=getattr(request.state, "request_id", None),
        errors=errors,
    )
    return JSONResponse(
        status_code=status_code,
        content=problem.model_dump(mode="json", exclude_none=True),
        media_type="application/problem+json",
    )


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ReliableAgentError)
    async def handle_domain_error(
        request: Request,
        exc: ReliableAgentError,
    ) -> JSONResponse:
        if isinstance(exc, NotFoundError):
            status_code = 404
        elif isinstance(exc, ConflictError):
            status_code = 409
        elif isinstance(exc, PolicyViolationError):
            status_code = 403
        elif isinstance(exc, ValidationError):
            status_code = 422
        else:
            status_code = 400
        return _problem_response(
            request,
            status_code=status_code,
            code=exc.code,
            detail=exc.message,
            errors=[jsonable_encoder(exc.details)] if exc.details else None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _problem_response(
            request,
            status_code=422,
            code="request_validation_error",
            detail="the request payload or parameters are invalid",
            errors=jsonable_encoder(exc.errors()),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        response = _problem_response(
            request,
            status_code=exc.status_code,
            code="http_error",
            detail=str(exc.detail),
        )
        if exc.headers:
            response.headers.update(exc.headers)
        return response

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled API error", exc_info=exc)
        return _problem_response(
            request,
            status_code=500,
            code="internal_server_error",
            detail="an unexpected error occurred",
        )
