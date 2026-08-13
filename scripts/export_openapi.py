"""Export or verify the committed OpenAPI contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reliable_agent_runtime.api.app import create_app
from reliable_agent_runtime.settings import Settings

DEFAULT_OUTPUT = Path("docs/openapi.json")


def render_openapi() -> str:
    """Return a deterministic JSON representation of the API contract."""

    app = create_app(
        settings=Settings(database_url="sqlite+pysqlite:///:memory:"),
    )
    return json.dumps(
        app.openapi(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"contract path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when the committed contract differs from generated output",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rendered = render_openapi()
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            print(f"OpenAPI contract is stale: regenerate {args.output}")
            return 1
        print(f"OpenAPI contract is current: {args.output}")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
