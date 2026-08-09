from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "app"


def test_domain_and_ports_do_not_import_adapters_or_bootstrap() -> None:
    forbidden = (
        "app.pipeline.bootstrap",
        "src.infrastructure",
        ".adapters",
    )
    checked_files = [
        path
        for path in SRC.rglob("*.py")
        if any(part in {"domain", "ports"} for part in path.parts)
    ]
    violations: list[str] = []
    for path in checked_files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = None
            if isinstance(node, ast.ImportFrom):
                module = node.module
            elif isinstance(node, ast.Import):
                module = node.names[0].name
            if module and any(value in module for value in forbidden):
                violations.append(f"{path.relative_to(ROOT)} imports {module}")

    assert violations == []
