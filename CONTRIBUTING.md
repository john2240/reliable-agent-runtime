# Contributing

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
make quality
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1`.

## Design rules

1. Domain and application modules must not import FastAPI, SQLAlchemy, or a
   concrete LLM SDK.
2. New tools implement the `Tool` port, declare their side-effect semantics,
   validate inputs, and provide a verification strategy.
3. Every behavior change includes unit or integration tests.
4. Public API changes update `docs/api.md` and the changelog.
5. Side-effecting code must document idempotency and compensation behavior.

## Pull requests

Keep changes focused. Explain the failure mode, the chosen invariant, and how
tests demonstrate it. Run `make quality` before submitting.
