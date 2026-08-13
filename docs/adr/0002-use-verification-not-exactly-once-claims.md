# ADR 0002: Use idempotency and verification instead of exactly-once claims

- Status: Accepted
- Date: 2026-08-08

## Context

After a timeout, the runtime may not know whether an external write failed or
only its response was lost. Blind retry can duplicate a payment, notification,
or provisioning action. Conversely, treating every timeout as success can hide
a failed operation.

A generic runtime cannot guarantee exactly-once behavior across arbitrary
external systems. The available guarantees depend on each provider and adapter.

## Decision

Every logical step receives a stable call ID and idempotency key. Side-effecting
adapters must expose a verification strategy against provider state. The
runtime retries only when:

1. the action is confirmed not applied; or
2. repeating the same logical call is safe because the provider honors the
   supplied idempotency key.

Reversible writes may additionally define semantic compensation. Irreversible
writes require approval under the default policy.

## Consequences

### Positive

- Unknown outcomes are explicit rather than collapsed into generic failures.
- Lost responses can be reconstructed from provider state.
- Guarantees remain honest and adapter-specific.
- Acceptance tests can assert observable invariants such as a single refund.

### Negative

- Adapters require more implementation work than simple function wrappers.
- Providers without lookup or idempotency support may remain inconclusive.
- Compensation is best effort and cannot erase every real-world consequence.
