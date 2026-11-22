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


def imported_modules(path: Path, package: str = "") -> set[str]:
    """Dotted names imported by a file; relative imports resolve against `package`."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            parts = package.split(".") if package else []
            anchor = parts[: len(parts) - (node.level - 1)] if node.level else []
            base = ".".join([*anchor, *([node.module] if node.module else [])])
            if base:
                names.add(base)
                names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


def is_forbidden(name: str) -> bool:
    if name.split(".")[0] in FORBIDDEN_MODULES:
        return True
    return any(name == p or name.startswith(p + ".") for p in FORBIDDEN_PACKAGES)


@pytest.mark.req("REQ-SIM-002")
def test_core_has_no_forbidden_imports() -> None:
    """AC1: core stays deterministic and independent of higher layers."""
    offenders = []
    for path in sorted(CORE.rglob("*.py")):
        package = ".".join(("pericles", "core", *path.relative_to(CORE).parts[:-1]))
        offenders += [
            f"{path.relative_to(CORE)}: {name}"
            for name in imported_modules(path, package)
            if is_forbidden(name)
        ]
    assert offenders == []


@pytest.mark.req("REQ-SIM-002")
def test_imported_modules_sees_from_imports_and_relative_imports(tmp_path: Path) -> None:
    """AC1: the helper flags `from pericles import agents`, `import time`, relative forms."""
    source = tmp_path / "mod.py"
    source.write_text(
        "from pericles import agents\nimport time\nfrom .. import llm\nfrom ..server import x\n",
        encoding="utf-8",
    )
    names = imported_modules(source, package="pericles.core")
    assert "pericles.agents" in names
    assert "time" in names
    assert "pericles.llm" in names
    assert "pericles.server" in names
    assert is_forbidden("pericles.agents")
    assert is_forbidden("time")
    assert not is_forbidden("pericles.agentsx")
    assert not is_forbidden("pericles.core.world")
