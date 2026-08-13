"""Command-line entry point for the HTTP service."""

from __future__ import annotations

import argparse
import os

import uvicorn


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reliable-agent-runtime",
        description="Run the Reliable Agent Runtime HTTP API.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("RAR_HOST", "0.0.0.0"),
        help="bind address (default: RAR_HOST or 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("RAR_PORT", "8000")),
        help="bind port (default: RAR_PORT or 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="enable development auto-reload",
    )
    return parser


def main() -> None:
    """Start Uvicorn using the application factory's module-level app."""

    args = _parser().parse_args()
    uvicorn.run(
        "reliable_agent_runtime.api.app:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        access_log=True,
    )


if __name__ == "__main__":
    main()
