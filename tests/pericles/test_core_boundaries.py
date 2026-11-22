import ast
from pathlib import Path

import pytest

import pericles.core

CORE = Path(pericles.core.__file__).parent
FORBIDDEN_PACKAGES = (
    "pericles.agents",
    "pericles.llm",
    "pericles.experiment",
    "pericles.server",
    "pericles.analysis",
)
FORBIDDEN_MODULES = ("time", "datetime", "uuid", "secrets")


def imported_modules(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


@pytest.mark.req("REQ-SIM-002")
def test_core_has_no_forbidden_imports() -> None:
    """AC1: core stays deterministic and independent of higher layers."""
    offenders = []
    for path in sorted(CORE.rglob("*.py")):
        for name in imported_modules(path):
            top = name.split(".")[0]
            if top in FORBIDDEN_MODULES or name.startswith(FORBIDDEN_PACKAGES):
                offenders.append(f"{path.relative_to(CORE)}: {name}")
    assert offenders == []
