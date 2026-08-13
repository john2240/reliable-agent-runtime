# Reliable Agent Runtime

A planner-agnostic Python runtime for **auditable, idempotent, verifiable, and
compensatable tool execution** in adaptive agents.

The project is an engineering implementation, not a claim that transaction or
durable-execution ideas are new. Its goal is to provide a clean, inspectable
reference that can sit behind an LLM, a workflow engine, or a deterministic
planner.

Instead of trying to make a model infallible, the runtime treats each proposed
action or short execution phase as untrusted input and enforces reliability at
the system boundary:

- classify tool side effects;
- re-check external preconditions before mutation;
- require human approval for irreversible actions;
- reuse deterministic call and idempotency identities;
- verify postconditions after success, timeout, or response loss;
- resume in-flight calls after process interruption;
- compensate completed reversible writes after downstream failure;
- persist every state transition in an ordered audit journal;
- accept either a short validated DAG or one adaptive action at a time.

The included retail workflow intentionally simulates a difficult failure: the
refund provider commits the payment reversal and then the response connection
fails. The runtime queries provider state using the same idempotency key,
recovers the result, and proceeds without issuing a second refund.

> **Project status:** v0.2.0 alpha. The core semantics and demos are fully
> runnable; see [Production hardening](docs/production.md) before deploying
> multiple replicas or connecting sensitive systems.

## Why this project exists

A conventional tool loop often looks like this:

```text
LLM → tool call → observation → next tool call
```

That loop leaves critical questions unanswered:

- Did a timed-out payment call fail, or did only its response fail?
- Is the state used by the planner still current when execution begins?
- Can a retried write create a duplicate side effect?
- What happens when step 3 succeeds and step 4 fails?
- Which actions require approval, and where is that decision audited?
- Can an interrupted run recover without replaying every prior action?

Reliable Agent Runtime supplies explicit execution semantics for those cases.
It does **not** prescribe a model, prompt, planner, memory system, or agent
framework. An adaptive planner may submit one action, observe the result, and
replan; deterministic workflows may submit a short DAG.

## Reliability model

| Mechanism | Failure it addresses |
|---|---|
| `READ` / `WRITE` / `IRREVERSIBLE` effects | Treating every tool call as equally safe |
| Fresh preconditions | Acting on stale planner context |
| Provider idempotency keys | Duplicate writes after retry or redelivery |
| Postcondition verification | Unknown outcome after timeout/connection loss |
| Human approval records | Unsupervised sensitive actions |
| Optimistic aggregate versions | Lost updates under concurrent writers |
| Per-run execution lock | Concurrent advancement inside one process |
| Reverse-order compensation | Partial workflow failure after earlier writes |
| Append-only event sequence | Missing auditability and difficult debugging |
| Strict input/output schemas | Malformed planner arguments and adapter drift |

## Architecture

```text
                             ┌──────────────────────────┐
Adaptive planner / workflow ─► Versioned FastAPI API   │
                             └────────────┬─────────────┘
                                          │
                         ┌────────────────▼────────────────┐
                         │ Application use cases           │
                         │ RunService + ExecutionEngine    │
                         └────────────────┬────────────────┘
                                          │
             ┌────────────────────────────┼────────────────────────────┐
             │                            │                            │
     ┌───────▼────────┐        ┌──────────▼─────────┐       ┌──────────▼─────────┐
     │ StepExecutor   │        │ ApprovalCoordinator│       │ Compensation       │
     │ step lifecycle│        │ human authority    │       │ reverse writes     │
     └───────┬────────┘        └────────────────────┘       └────────────────────┘
             │
     ┌───────▼────────┐             Ports                  Adapters
     │ ToolInvoker    │      RuntimeStore / Tool /     SQLAlchemy / retail
     │ timeout/verify │      Policy / Clock / Lock     tools / asyncio lock
     └────────────────┘
```

The dependency rule is enforced by package layout: domain and application code
do not import FastAPI, SQLAlchemy, or a concrete model SDK. The composition
root in `bootstrap.py` wires ports to adapters. See
[docs/architecture.md](docs/architecture.md) and the decisions in
[docs/adr/](docs/adr/).

## Repository layout

```text
src/reliable_agent_runtime/
├── domain/                 # framework-free state, plans, events, errors
├── application/
│   ├── actions.py          # one-action convenience use case
│   ├── engine.py           # run lifecycle and short-DAG traversal
│   ├── service.py          # create/query/approval use cases
│   ├── policy.py           # composable authorization rules
│   └── execution/
│       ├── steps.py        # one step's lifecycle
│       ├── invocation.py   # timeout, errors, verification
│       ├── approvals.py    # approval gates
│       ├── compensation.py # rollback coordination
│       └── journal.py      # optimistic atomic persistence
├── infrastructure/
│   ├── persistence/        # SQLAlchemy store
│   ├── tools/              # typed adapters and demo external system
│   ├── locks.py
│   └── observability/
├── api/                    # HTTP schemas, routes, middleware, errors
└── bootstrap.py            # explicit dependency graph
```

## Quick start

Python 3.12 or newer is required.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
cp .env.example .env
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Start the API:

```bash
export RAR_DEMO_REFUND_UNKNOWN_OUTCOME_ONCE=true
reliable-agent-runtime --reload
```

The service exposes:

- API documentation: `http://127.0.0.1:8000/docs`
- OpenAPI document: `http://127.0.0.1:8000/openapi.json`
- readiness: `http://127.0.0.1:8000/health/ready`

Run the complete HTTP demo from another terminal:

```bash
./examples/curl_demo.sh
```

Or execute the runtime directly without HTTP:

```bash
python examples/run_demo.py
```

Run the adaptive-planning demo, which chooses the next action after every fresh
observation rather than freezing a complete workflow up front:

```bash
python examples/adaptive_agent_loop.py
```

Expected invariants:

```text
after first execution: waiting_approval
final status: succeeded
refunds created: 1
... tool.outcome_recovered ...
```

## Docker

```bash
docker compose up --build
```

The container runs as a non-root user, persists SQLite data in a named volume,
and includes a readiness health check.

## API workflow

### Adaptive action API

An LLM or other planner may execute one proposed action and then replan:

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: session-42:read-order' \
  --data '{
    "objective": "Resolve the refund request",
    "actor": "support-agent",
    "action_id": "read_order",
    "tool": "retail.get_order",
    "arguments": {"order_id": "ord-1001"}
  }' \
  http://127.0.0.1:8000/api/v1/actions
```

The response is a durable run snapshot. The planner can append its output or
error to the model context and choose another action. See
[docs/adaptive-agents.md](docs/adaptive-agents.md).

### Short workflow API

#### 1. Create a run

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: refund-demo' \
  --data @examples/retail_refund_plan.json \
  http://127.0.0.1:8000/api/v1/runs
```

A repeated request with the same key and payload returns the existing run. A
different payload using that key returns `409 idempotency_conflict`.

#### 2. Advance execution

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs/{run_id}/execute
```

The demo pauses at the irreversible refund and returns
`status=waiting_approval`.

#### 3. Approve once

```bash
curl -X POST \
  -H 'Content-Type: application/json' \
  --data '{"decision":"approve","actor":"manager","reason":"policy checked"}' \
  http://127.0.0.1:8000/api/v1/approvals/{approval_id}/decision
```

#### 4. Resume and inspect events

```bash
curl -X POST http://127.0.0.1:8000/api/v1/runs/{run_id}/execute
curl http://127.0.0.1:8000/api/v1/runs/{run_id}/events
```

See [docs/api.md](docs/api.md) for the complete contract.

## Plan format

Short workflows are validated DAGs. Long-horizon agents are expected to keep
reasoning and replanning outside the transaction boundary, then submit another
action or short phase. Arguments may reference run input or prior step outputs
without `eval` or arbitrary code execution:

```json
{
  "id": "refund",
  "tool": "retail.issue_refund",
  "depends_on": ["read_order", "update_ticket"],
  "arguments": {
    "order_id": "${input.order_id}",
    "amount_cents": "${steps.read_order.output.total_cents}"
  }
}
```

A placeholder occupying the entire value preserves the native JSON type, so
`amount_cents` remains an integer. Embedded placeholders are rendered as text.
Missing references fail closed.

## Implementing a tool

A tool adapter declares more than a callable:

```python
class Tool(Protocol):
    @property
    def spec(self) -> ToolSpec: ...

    async def validate_arguments(self, arguments: JsonObject) -> JsonObject: ...
    async def check_preconditions(...) -> CheckResult: ...
    async def execute(...) -> ToolResult: ...
    async def verify(...) -> VerificationResult: ...
    async def compensate(...) -> ToolResult: ...
```

Use `PydanticTool` for strict typed input/output models. Send
`ToolContext.idempotency_key` to the external provider and implement
verification against external state. See
[docs/adding-a-tool.md](docs/adding-a-tool.md) and
[examples/custom_tool.py](examples/custom_tool.py).

## API and operational features

- `/api/v1` versioning;
- OpenAPI-generated request/response contracts with a committed, CI-checked snapshot;
- unknown fields rejected by strict schemas;
- RFC 9457-style `application/problem+json` errors;
- request correlation IDs;
- optional constant-time API-key comparison;
- create-resource idempotency;
- conventional `Location` on creation and weak `ETag` on run representations;
- liveness/readiness endpoints;
- JSON structured application logs;
- paginated event reads by sequence cursor.

## Quality gates

```bash
make quality
make acceptance
```

The repository includes:

- unit and API integration tests;
- branch coverage with an 80% threshold;
- Ruff format/lint configuration and pre-commit hooks;
- a dependency-free AST architecture and safety gate;
- a committed OpenAPI snapshot checked for API drift in CI;
- Python bytecode compilation in CI;
- a Python 3.12/3.13 GitHub Actions matrix;
- typed public package marker (`py.typed`);
- Docker, contribution, security, conduct, and changelog files.

The acceptance report in `benchmarks/results/v0.2.0/acceptance.json` verifies duplicate
refund prevention, approval-denial compensation, and create-run idempotency.
It is a runtime invariant report—not a claim about LLM benchmark quality.

The public-benchmark plan deliberately reports both clean-task utility and
fault-injected reliability. A runtime that blocks every write is not useful;
normal task completion, false blocking, latency, and tool-call overhead must be
reported beside duplicate-write and recovery metrics. See
[docs/benchmarking.md](docs/benchmarking.md).

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `RAR_DATABASE_URL` | SQLite file | SQLAlchemy database URL |
| `RAR_API_KEY` | unset | Optional API-key protection for `/api/v1` |
| `RAR_CORS_ORIGINS` | empty | Comma-separated allowed origins |
| `RAR_LOG_LEVEL` | `INFO` | Structured log level |
| `RAR_DEMO_REFUND_UNKNOWN_OUTCOME_ONCE` | `false` | Simulate commit-then-response-loss once |
| `RAR_HOST` | `0.0.0.0` | CLI bind address |
| `RAR_PORT` | `8000` | CLI bind port |

## Explicit non-goals and limitations

- The runtime does not train or choose an LLM.
- The v0.2 reference API advances runs synchronously; slow production work should use a
  queue/worker.
- The reference lock is in-process and must be replaced for multiple replicas.
- The demo external retail system is in-memory; real adapters must query
  durable provider state.
- SQLite and automatic table creation are development defaults; production
  deployments need PostgreSQL and migrations.
- The runtime does not promise universal exactly-once execution. It provides
  stable logical identity, conservative retry rules, verification, and
  compensation where adapters can support them.

## Roadmap

- PostgreSQL/Alembic deployment profile;
- durable worker and distributed run lease;
- OpenTelemetry traces and Prometheus metrics;
- encrypted/redacted event payload policies;
- optional planner adapters for OpenAI-compatible and local models;
- τ³-bench Retail adapter with direct, retry/idempotency, and runtime baselines;
- prompt-injection provenance and least-privilege capability policies;
- WebSocket or webhook run-event delivery.

## License

MIT. See [LICENSE](LICENSE).
