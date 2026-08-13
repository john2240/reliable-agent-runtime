# Reliability checks and public benchmark work

## Acceptance scenarios

`reliability_scenarios.py` contains deterministic runtime checks, not a claim of
model quality or academic benchmark superiority. It verifies:

1. a refund that commits before a simulated connection failure is recovered by
   verification and is not duplicated;
2. denial of an irreversible action compensates an earlier reversible write;
3. create-run idempotency returns the same resource and rejects key reuse with a
   different payload.

Run:

```bash
make acceptance
```

## Public benchmark comparison

The planned τ³-bench Retail adapter compares three practical backends:

```text
Direct + generic retry
Retry + stable idempotency
Reliable Runtime
```

The clean track must be reported beside the fault-injected track so reliability
is not achieved by blocking valid actions. The detailed protocol and metric
definitions are in [`docs/benchmarking.md`](../docs/benchmarking.md).
