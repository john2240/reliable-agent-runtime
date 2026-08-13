# HTTP API v1

Base path: `/api/v1`

The service publishes OpenAPI at `/openapi.json` and interactive documentation
at `/docs` when running with the default FastAPI configuration. A deterministic
snapshot is committed at `docs/openapi.json` and verified in CI.

## Conventions

- JSON request and response bodies.
- `Idempotency-Key` is accepted by `POST /actions` and `POST /runs`.
- `X-Request-ID` is accepted or generated and echoed on every response.
- Optional `X-API-Key` protection is enabled when `RAR_API_KEY` is configured.
- Run representations include a weak `ETag`; create responses also include `Location`.
- Errors use `application/problem+json` with stable machine code, request ID,
  and validation details.
- Unknown request fields are rejected.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health/live` | Process liveness |
| `GET` | `/health/ready` | Storage readiness |
| `GET` | `/api/v1/tools` | Discover tool schemas and side-effect metadata |
| `POST` | `/api/v1/actions` | Execute one planner-proposed adaptive action |
| `POST` | `/api/v1/runs` | Create an immutable plan/run request |
| `GET` | `/api/v1/runs/{run_id}` | Read the current aggregate snapshot |
| `POST` | `/api/v1/runs/{run_id}/execute` | Advance until terminal or approval is needed |
| `GET` | `/api/v1/runs/{run_id}/events` | Read sequenced audit events |
| `GET` | `/api/v1/runs/{run_id}/approvals` | Read approval requests |
| `POST` | `/api/v1/approvals/{id}/decision` | Approve or deny once |

## Adaptive actions

`POST /api/v1/actions` is a convenience over the same durable run machinery. It
creates a one-step plan, advances it immediately, and returns a normal
`RunResponse`. An adaptive agent can inspect the output/error/status and choose
its next action without declaring a complete long-horizon plan.

If the action requires approval, the response is `waiting_approval`; use the
existing approval and run-execution endpoints to resume it. If several effects
must be compensated together, submit them through `POST /api/v1/runs` as a
short DAG instead of separate actions.

## Create idempotency

The first valid request with a key returns `201 Created`. Replaying the same
payload and actor returns the existing run with `200 OK`. Reusing the key for a
different objective, input, actor, or plan returns `409 idempotency_conflict`.

The key prevents duplicate runtime resources. Each tool adapter must separately
honor the runtime-provided tool idempotency key for external side effects.

## Execution response

Execution is synchronous only until the run:

- succeeds;
- fails;
- reaches an approval boundary.

This keeps the reference API easy to inspect. For slow production tools, place
execution behind a queue/worker and return `202 Accepted` while preserving the
same domain and store ports.

For a successful plan with one terminal DAG step, `result` is that step's
normalized output. For multiple terminal steps, the response is shaped as
`{"steps": {"step_id": {...}}}` so no branch is discarded.

## Problem detail example

```json
{
  "type": "urn:reliable-agent-runtime:problem:run_not_found",
  "title": "Not Found",
  "status": 404,
  "detail": "run 'run_missing' does not exist",
  "instance": "/api/v1/runs/run_missing",
  "code": "run_not_found",
  "request_id": "req_..."
}
```
