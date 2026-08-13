# Production hardening guide

The repository is a production-oriented reference implementation, not a claim
that a single-process SQLite demo provides every production guarantee.

Before a multi-replica deployment:

1. Replace SQLite with PostgreSQL and add Alembic migrations.
2. Replace `InMemoryRunLockManager` with a distributed lease, or partition a
   durable work queue by run ID.
3. Execute slow runs in workers and expose asynchronous job semantics.
4. Put the API behind an identity-aware gateway; apply actor and tool-level
   authorization rather than relying only on the optional API key.
5. Store secrets in a secret manager and redact sensitive tool arguments from
   logs/events where required.
6. Add metrics and traces for run duration, retries, approval latency,
   verification outcomes, compensation failures, and tool error budgets.
7. Ensure every external write API supports provider idempotency or a durable
   deduplication record controlled by the adapter.
8. Define retention and encryption policies for audit data.
9. Add rate limits, request size limits, and tenant isolation.
10. Chaos-test response loss, worker termination, duplicate delivery, stale
    reads, and partial external outages.

## Exactly-once language

The runtime does not promise universal exactly-once execution. Across arbitrary
external systems, that promise is generally unavailable. It instead provides
stable logical call identity, safe retry rules, external-state verification,
and explicit compensation—the guarantees an adapter can actually enforce.
