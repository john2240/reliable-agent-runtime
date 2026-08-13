# Testing strategy

## Unit tests

- plan DAG validation and deterministic ordering;
- template resolution and fail-closed missing references;
- tool registry invariants;
- approval, unknown-outcome recovery, compensation, and idempotency;
- defensive plan copying, multi-sink DAG results, fresh preconditions, and
  observationally idempotent re-execution.

## API integration tests

- complete create → execute → approve → resume flow;
- adaptive single-action execution, approval, recovery, and idempotent replay;
- resource headers and replay semantics;
- RFC 9457-compatible errors;
- optional API-key enforcement;
- idempotency conflicts and one-time approval decisions.

## Acceptance scenarios

`benchmarks/reliability_scenarios.py` runs deterministic end-to-end reliability
checks and writes a machine-readable report. These are system invariants, not
model-quality scores. The planned public benchmark adds clean-task utility and
fault-injected reliability comparisons; see `docs/benchmarking.md`.

## Quality gates

- Ruff formatting and linting in CI;
- dependency-free AST checks for annotations, bare exceptions, wildcard
  imports, mutable defaults, dynamic execution, production `print` calls, and architectural dependency rules;
- committed OpenAPI contract drift checks;
- bytecode compilation;
- branch coverage with an 80% minimum.
