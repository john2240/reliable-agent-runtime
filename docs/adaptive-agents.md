# Adaptive agents

Reliable Agent Runtime does not require an agent to freeze an entire long-horizon
plan before execution. Two integration styles are supported:

1. **Short DAG run** — submit a small group of steps that share one business
   invariant, such as update-ticket → issue-refund.
2. **Single adaptive action** — submit one tool call through `POST /api/v1/actions`,
   inspect the structured result, and let the planner choose the next action.

The planner remains responsible for reasoning, branching, clarification, and
replanning. The runtime owns the reliability boundary around external effects.

```text
LLM / deterministic planner
          │
          │ next action or short phase
          ▼
Reliable Agent Runtime
  schema → policy → fresh precondition → execute → verify
          │
          ▼
structured run outcome
          │
          ├─ succeeded
          ├─ waiting_approval
          ├─ failed / safe rejection
          └─ recovered unknown outcome
          │
          ▼
planner observes and replans
```

## Single-action API

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: session-42:read-order' \
  -d '{
    "objective": "Resolve the customer refund request",
    "actor": "support-agent",
    "action_id": "read_order",
    "tool": "retail.get_order",
    "arguments": {"order_id": "ord-1001"}
  }' \
  http://127.0.0.1:8000/api/v1/actions
```

The response is the same durable `RunResponse` used by the regular run API. An
irreversible action can return `waiting_approval`; after a decision, resume it
through the existing `/api/v1/runs/{run_id}/execute` endpoint.

## Choosing the transaction boundary

Do not wrap an entire open-ended conversation in one transaction. Use the
smallest phase whose operations must be reasoned about together:

- one read or idempotent write: use `/actions`;
- several dependent operations with compensation requirements: use a short DAG;
- long-horizon reasoning: keep it in the planner loop and submit another phase
  after each observation.

Cross-run compensation is intentionally not automatic. If two mutations must
succeed or be compensated together, place them in the same short run.

## LLM integration

A model adapter only needs to map a tool call to the action request above and
append the returned status/output/error to its conversation state. The runtime
is model-neutral and does not hide the planner behind a framework-specific API.

See `examples/adaptive_agent_loop.py` for a key-free deterministic example. Its
planner can be replaced by any OpenAI-compatible, Anthropic-compatible, or local
model client without changing the execution layer.
