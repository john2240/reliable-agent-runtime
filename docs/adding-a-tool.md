# Adding a tool

A reliable tool adapter is more than a function wrapper. It defines input and
output contracts, side effects, idempotency, preconditions, verification, and
optionally compensation.

## Checklist

1. Define strict Pydantic input/output models.
2. Extend `PydanticTool` or implement the `Tool` port directly.
3. Declare `ToolSpec.effect`:
   - `read`: no external mutation;
   - `write`: external mutation that may be compensatable;
   - `irreversible`: sensitive mutation requiring approval by default.
4. Send `ToolContext.idempotency_key` to the external provider.
5. Check current external state in `check_preconditions`.
6. Implement `verify` so timeouts and restart recovery do not guess.
7. Implement `compensate` only when a semantic inverse actually exists.
8. Register the adapter in the composition root or a registry module.
9. Add tests for duplicate calls, response loss, stale state, and compensation.

See `examples/custom_tool.py` for a minimal typed adapter and
`infrastructure/tools/retail/` for complete examples.

## Verification outcomes

- `confirmed_success`: the intended postcondition exists; observed output may
  reconstruct a lost response.
- `confirmed_not_applied`: the action is known not to have committed.
- `inconclusive`: do not assume success or failure. The runtime retries only if
  repeating the same logical call is safe.

## Adapter boundary rule

Do not leak SDK exceptions into the application layer. Convert known failures
to `TransientToolError`, `PermanentToolError`, or `UnknownToolOutcome`.
Unexpected exceptions are normalized by `ToolInvoker` and recorded without
exposing stack traces through the API.
