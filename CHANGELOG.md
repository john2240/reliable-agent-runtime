# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.0] - 2026-08-09

### Added

- Single-action API for adaptive planners that replan after each observation.
- `ActionService` as a cohesive application-layer convenience over durable runs.
- Key-free adaptive agent-loop example with approval and unknown-outcome recovery.
- Practical public-benchmark methodology with clean-utility and fault-reliability tables.

### Changed

- Documentation now recommends short transaction boundaries instead of freezing an
  entire long-horizon plan.
- Project positioning explicitly focuses on engineering quality rather than novelty.

## [0.1.0] - 2026-08-08

### Added

- Planner-agnostic execution plans with stable DAG validation.
- Read, write, and irreversible tool-effect classification.
- Idempotency keys, preconditions, postcondition verification, and retries.
- Human approval gates for irreversible actions.
- Reverse-order compensation for reversible writes.
- Restart recovery for in-flight calls with ambiguous outcomes.
- Transactional SQLAlchemy store and append-only audit event journal.
- Versioned FastAPI API with OpenAPI, request IDs, API-key support, and
  RFC 9457-compatible problem details.
- Demo retail adapters and reliability acceptance scenarios.
