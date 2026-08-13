"""Reusable OpenAPI response documentation for the HTTP boundary."""

from __future__ import annotations

from typing import Any

from reliable_agent_runtime.api.schemas import ProblemDetail


def problem_response(description: str) -> dict[str, Any]:
    """Describe an RFC 9457 problem response with its actual media type."""

    return {
        "description": description,
        "content": {
            "application/problem+json": {
                "schema": ProblemDetail.model_json_schema(mode="serialization"),
            },
        },
    }


PROTECTED_PROBLEM_RESPONSES: dict[int, dict[str, Any]] = {
    400: problem_response("Invalid runtime operation"),
    401: problem_response("Missing or invalid API key"),
    403: problem_response("Operation denied by policy"),
    404: problem_response("Requested runtime resource not found"),
    409: problem_response("Idempotency or concurrent-state conflict"),
    422: problem_response("Request or domain validation failed"),
    500: problem_response("Unexpected server error"),
}
