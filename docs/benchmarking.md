# Benchmarking plan

The project is evaluated as an engineering runtime, not as a new foundation
model or a claim of novel transaction theory. The comparison asks a practical
question:

> With the same model, prompt, tools, tasks, and random seeds, does the reliable
> execution layer preserve normal task utility while reducing bad side effects
> and recovering more tool failures than reasonable baselines?

## Public benchmark

The first public adapter should use the Retail domain from τ³-bench. Retail is a
natural fit because its tasks contain stateful reads and writes such as order
changes, cancellation, return, exchange, and refund workflows.

Pin the exact upstream release or commit and publish a machine-readable task
manifest. Do not manually choose only tasks that favor this runtime.

## Execution modes

### Deterministic runtime track

Replay one valid reference action trace from the public task as a workload. This
track does not call an LLM and isolates execution behavior.

Compare:

1. **Direct + generic retry** — validates arguments and retries transient errors.
2. **Retry + stable idempotency** — adds a logical operation key and durable
   result reuse.
3. **Reliable Runtime** — adds fresh preconditions, verification of ambiguous
   outcomes, durable journal, approval gates, and explicit recovery states.

A checkpoint/replay baseline is a useful later addition, but is not required to
publish the first useful engineering comparison.

### End-to-end agent track

Use the same agent model and user simulator for all executors. The planner emits
one action at a time through `/api/v1/actions` or submits a short DAG when a
small group of effects shares one invariant. Only the execution backend changes.

## Clean-task table

Report this table before fault injection:

| Executor | Official success ↑ | False block ↓ | Tool calls ↓ | p95 latency ↓ | Cost/task ↓ |
|---|---:|---:|---:|---:|---:|
| Direct + retry | TBD | TBD | TBD | TBD | TBD |
| Retry + idempotency | TBD | TBD | TBD | TBD | TBD |
| Reliable Runtime | TBD | TBD | TBD | TBD | TBD |

This prevents a misleading result in which a runtime looks safe only because it
refuses useful writes. Suggested derived metric:

```text
utility_retention = reliable_clean_success / direct_clean_success
```

## Fault-injected table

| Executor | Reliable success ↑ | Duplicate write ↓ | Unsafe write ↓ | Recovery ↑ |
|---|---:|---:|---:|---:|
| Direct + retry | TBD | TBD | TBD | TBD |
| Retry + idempotency | TBD | TBD | TBD | TBD |
| Reliable Runtime | TBD | TBD | TBD | TBD |

Recommended deterministic fault cases:

- timeout before provider commit;
- response loss after provider commit;
- duplicate delivery of the same logical action;
- stale state between read and write;
- runtime restart after dispatch but before local success persistence.

All executors must receive the same paired trial key:

```text
benchmark_commit + task_id + action_id + fault_kind + seed
```

## Metric definitions

- **Reliable success**: scenario-specific safe oracle passes, with no duplicate
  mutation, unsafe write, or unresolved unknown outcome.
- **Duplicate write**: the same semantic operation reaches a mutating provider
  more than once when it should be applied once.
- **Unsafe write**: a mutation reaches the provider after a required fresh
  precondition has become false.
- **Recovery**: a recoverable fault ends in the correct safe state without
  restarting the whole task manually.
- **False block**: a valid clean action is rejected by the runtime.

Publish raw JSONL trial records, summary CSV/Markdown, environment metadata,
model parameters, token usage, and exact commands.
