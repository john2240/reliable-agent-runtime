"""Dependency-free structural checks used alongside Ruff and pytest.

The gate intentionally focuses on architecture and unsafe constructs that are
cheap to enforce in every environment. Ruff remains responsible for style and
common correctness rules in CI.
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

ROOTS = (
    Path("src"),
    Path("tests"),
    Path("examples"),
    Path("benchmarks"),
    Path("scripts"),
)
BANNED_CALLS = {"eval", "exec", "compile"}
CORE_FRAMEWORK_PREFIXES = ("fastapi", "pydantic", "sqlalchemy", "starlette")
INTERNAL_PREFIX = "reliable_agent_runtime."
ALLOWED_INTERNAL_LAYERS: dict[str, frozenset[str]] = {
    "domain": frozenset({"domain"}),
    "application": frozenset({"application", "domain"}),
    "infrastructure": frozenset({"application", "domain", "infrastructure", "settings"}),
}


@dataclass(frozen=True, slots=True)
class Finding:
    path: Path
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


class QualityVisitor(ast.NodeVisitor):
    def __init__(self, path: Path, *, production: bool, layer: str | None) -> None:
        self.path = path
        self.production = production
        self.layer = layer
        self.findings: list[Finding] = []

    def _add(self, node: ast.AST, message: str) -> None:
        self.findings.append(Finding(self.path, getattr(node, "lineno", 1), message))

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self._add(node, "bare except is forbidden")
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._check_import(node, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if any(alias.name == "*" for alias in node.names):
            self._add(node, "wildcard imports are forbidden")
        if node.module:
            self._check_import(node, node.module)
        self.generic_visit(node)

    def _check_import(self, node: ast.AST, module: str) -> None:
        if self.layer in {"domain", "application"} and module.startswith(
            CORE_FRAMEWORK_PREFIXES,
        ):
            self._add(
                node,
                f"{self.layer} layer must not import framework module {module!r}",
            )

        allowed_layers = ALLOWED_INTERNAL_LAYERS.get(self.layer or "")
        if allowed_layers is None or not module.startswith(INTERNAL_PREFIX):
            return
        imported_layer = module.removeprefix(INTERNAL_PREFIX).split(".", maxsplit=1)[0]
        if imported_layer not in allowed_layers:
            self._add(
                node,
                f"{self.layer} layer must not depend on {imported_layer!r}",
            )

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in BANNED_CALLS:
            self._add(node, f"dynamic execution via {node.func.id} is forbidden")
        if self.production and isinstance(node.func, ast.Name) and node.func.id == "print":
            self._add(node, "use structured logging instead of print in production code")
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_function(node)
        self.generic_visit(node)

    def _check_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        if self.production and node.returns is None:
            self._add(node, "production function is missing a return annotation")

        arguments = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
        for argument in arguments:
            if argument.arg in {"self", "cls"}:
                continue
            if self.production and argument.annotation is None:
                self._add(node, f"argument {argument.arg!r} is missing a type annotation")

        defaults = [*node.args.defaults, *node.args.kw_defaults]
        for default in defaults:
            if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self._add(node, "mutable collection literal used as a default argument")


def python_files() -> list[Path]:
    return sorted(
        path
        for root in ROOTS
        if root.exists()
        for path in root.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def source_layer(path: Path) -> str | None:
    parts = path.parts
    if len(parts) < 3 or parts[0] != "src" or parts[1] != "reliable_agent_runtime":
        return None
    candidate = parts[2]
    return candidate if candidate in ALLOWED_INTERNAL_LAYERS else None


def main() -> int:
    findings: list[Finding] = []
    for path in python_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            findings.append(Finding(path, exc.lineno or 1, f"syntax error: {exc.msg}"))
            continue
        visitor = QualityVisitor(
            path,
            production=path.parts[0] == "src",
            layer=source_layer(path),
        )
        visitor.visit(tree)
        findings.extend(visitor.findings)

    if findings:
        for finding in findings:
            print(finding.render(), file=sys.stderr)
        return 1

    print(f"quality gate passed for {len(python_files())} Python files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
