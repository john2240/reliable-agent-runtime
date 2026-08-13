# ADR 0001: Separate planning from reliable execution

- Status: Accepted
- Date: 2026-08-08

## Context

Model providers, prompts, and planning strategies evolve quickly. Reliability
rules for external side effects—approval, idempotency, verification, audit,
and compensation—should not be duplicated inside every planner or prompt.
Mixing both concerns also makes experiments ambiguous: a result may improve
because the planner changed, because execution changed, or both.

## Decision

The runtime accepts a validated declarative `ExecutionPlan` and does not own
LLM inference. Planners are clients of the runtime. The application layer
operates only on domain plans, tool ports, and persistence/policy abstractions.

The execution boundary is therefore:

```text
planner output -> validated plan -> policy -> reliable tool execution
```

## Consequences

### Positive

- One runtime can serve deterministic workflows and multiple LLM planners.
- Runtime ablations can hold model and plan generation constant.
- Concrete model SDKs cannot leak into reliability-critical application code.
- Plans are inspectable and may be approved before side effects occur.

### Negative

- The v0.1 runtime does not repair a poor plan or perform autonomous replanning.
- A planner adapter must translate model output into the plan contract.
- Dynamic tasks may need a future controlled replanning protocol rather than
  arbitrary model calls inside tool adapters.
