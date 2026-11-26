import ast
import os
from pathlib import Path
from typing import cast

import pytest

import pericles
import pericles.agents
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


# Numeric literals other than 0 and 1 that core may contain: (file, enclosing scope, value) → why.
ALLOWED_NUMBERS: dict[tuple[str, str, float], str] = {
    ("inventory.py", "<module>", 10): "UNLIMITED = 10**9, a sentinel capacity",
    ("inventory.py", "<module>", 9): "UNLIMITED = 10**9, a sentinel capacity",
    ("inventory.py", "<module>", 1e-09): "EPSILON, the float-comparison tolerance",
    ("mapgen.py", "<module>", 2.0): "_EPS = 2.0**-30, a power-of-two tolerance",
    ("mapgen.py", "<module>", 30): "_EPS = 2.0**-30, a power-of-two tolerance",
    ("mapgen.py", "start_area", 2): "halving for the centre and squaring the radius",
    ("mapgen.py", "TileMap.start", 2): "the map centre",
    ("mapgen.py", "_smooth", 3.0): "smoothstep 3t^2 - 2t^3",
    ("mapgen.py", "_smooth", 2.0): "smoothstep 3t^2 - 2t^3",
    ("mapgen.py", "value_noise", 2): "the lattice needs one padding cell on each side",
    ("mapgen.py", "generate_map", 6): "decimal places kept when serialising elevation",
    ("buildings.py", "Ownership.__post_init__", 2): "shared ownership means at least two owners",
    ("engine.py", "Engine._cost_field", 2): "index of the field in the cache tuple",
    ("life.py", "<module>", 60): "MINUTES_PER_HOUR, a unit definition",
}
# Modules whose literals are parameter defaults or content validation bounds.
PARAMETER_MODULES = {"config.py", "calendar.py", "content/schema.py"}
PARAMETER_CLASSES = {("mapgen.py", "MapParams")}


def numeric_literals(path: Path, name: str) -> list[tuple[str, float, int]]:
    """(enclosing scope, value, line) for every int/float literal other than 0 and 1."""
    found: list[tuple[str, float, int]] = []

    def visit(node: ast.AST, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                if (name, child.name) in PARAMETER_CLASSES:
                    continue
                visit(child, [*scope, child.name])
            elif isinstance(child, ast.Constant) and type(child.value) in (int, float):
                value = cast(float, child.value)
                if value not in (0, 1):
                    found.append((".".join(scope) or "<module>", value, child.lineno))
            else:
                visit(child, scope)

    visit(ast.parse(path.read_text(encoding="utf-8")), [])
    return found


@pytest.mark.skipif(
    "MUTANT_UNDER_TEST" in os.environ,
    reason="mutmut rewrites core into mangled trampolines; this is a static source check",
)
def test_core_has_no_magic_numbers() -> None:
    """No magic values (ADR-0015 §11): numbers live in config or content, not in core code."""
    offenders = []
    for path in sorted(CORE.rglob("*.py")):
        name = path.relative_to(CORE).as_posix()
        if name in PARAMETER_MODULES:
            continue
        offenders += [
            f"{name}:{line} {value!r} in {scope}"
            for scope, value, line in numeric_literals(path, name)
            if (name, scope, value) not in ALLOWED_NUMBERS
        ]
    assert offenders == []


def test_numeric_literals_finds_nested_numbers(tmp_path: Path) -> None:
    """The scanner reports scope and value, skips 0, 1, strings, and parameter classes."""
    source = tmp_path / "mod.py"
    source.write_text(
        "X = 7\n"
        "def f():\n    return 0 + 1 + 2.5\n"
        "class MapParams:\n    size: int = 16\n"
        "class C:\n    def g(self):\n        return '9'\n",
        encoding="utf-8",
    )
    assert numeric_literals(source, "mapgen.py") == [("<module>", 7, 1), ("f", 2.5, 3)]


AGENTS = Path(pericles.agents.__file__).parent
AGENT_FORBIDDEN_MODULES = ("random", "time", "datetime", "uuid", "secrets")
AGENT_FORBIDDEN_PACKAGES = ("pericles.experiment", "pericles.server", "pericles.analysis")
# Numeric literals other than 0 and 1 that agents may contain: (file, scope, value) → why.
AGENT_ALLOWED_NUMBERS: dict[tuple[str, str, float], str] = {}
AGENT_PARAMETER_MODULES = {"config.py"}


@pytest.mark.req("REQ-AGT-008")
def test_agents_are_deterministic_and_layered() -> None:
    """AC1: scripted minds use no clock or randomness and sit below the experiment layer."""
    offenders = []
    for path in sorted(AGENTS.rglob("*.py")):
        package = ".".join(("pericles", "agents", *path.relative_to(AGENTS).parts[:-1]))
        for name in imported_modules(path, package):
            top = name.split(".")[0]
            bad_package = any(
                name == p or name.startswith(p + ".") for p in AGENT_FORBIDDEN_PACKAGES
            )
            if top in AGENT_FORBIDDEN_MODULES or bad_package:
                offenders.append(f"{path.relative_to(AGENTS)}: {name}")
    assert offenders == []


@pytest.mark.skipif(
    "MUTANT_UNDER_TEST" in os.environ,
    reason="mutmut rewrites agents into mangled trampolines; this is a static source check",
)
def test_agents_have_no_magic_numbers() -> None:
    """No magic values (ADR-0016): scripted thresholds live in AgentConfig, not in code."""
    offenders = []
    for path in sorted(AGENTS.rglob("*.py")):
        name = path.relative_to(AGENTS).as_posix()
        if name in AGENT_PARAMETER_MODULES:
            continue
        offenders += [
            f"{name}:{line} {value!r} in {scope}"
            for scope, value, line in numeric_literals(path, name)
            if (name, scope, value) not in AGENT_ALLOWED_NUMBERS
        ]
    assert offenders == []


@pytest.mark.req("REQ-EXP-003")
def test_analysis_reads_only_the_event_schema() -> None:
    """AC1: metrics derive from the event log and config, independent of the engine and agents."""
    import pericles.analysis

    root = Path(pericles.analysis.__file__).parent
    offenders = [
        f"{path.name}: {name}"
        for path in sorted(root.rglob("*.py"))
        for name in imported_modules(path, "pericles.analysis")
        if name.startswith("pericles")
        and not name.startswith(("pericles.core.events", "pericles.analysis"))
    ]
    assert offenders == []


SRC = Path(pericles.__file__).parent
CLIENTS = ("urllib", "http.client", "requests", "httpx", "ollama", "openai", "mlx", "mlx_lm")
CLIENT_OWNERS = {
    "llm/ollama.py": ("urllib", "http.client"),
    "llm/mlx_runtime.py": ("mlx", "mlx_lm"),
}
BACKEND_MODULES = (
    "pericles.llm.ollama",
    "pericles.llm.mlx",
    "pericles.llm.mlx_runtime",
    "pericles.llm.fake",
)
LLM_MAY_IMPORT = ("pericles.llm", "pericles.core.canonical")


def _sources() -> list[tuple[str, set[str]]]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        package = ".".join(("pericles", *path.relative_to(SRC).parts[:-1]))
        found.append((relative, imported_modules(path, package)))
    return found


def _within(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


@pytest.mark.req("REQ-LLM-001")
def test_only_the_backend_modules_import_a_model_client() -> None:
    """AC1: no other module imports an HTTP or MLX client."""
    offenders = [
        f"{relative}: {name}"
        for relative, names in _sources()
        for name in names
        if _within(name, CLIENTS) and not _within(name, CLIENT_OWNERS.get(relative, ()))
    ]
    assert offenders == []


@pytest.mark.req("REQ-LLM-001")
def test_only_llm_and_experiment_construct_backends() -> None:
    """AC1: agents and the rest reach models only through the gateway."""
    offenders = [
        f"{relative}: {name}"
        for relative, names in _sources()
        if not relative.startswith(("llm/", "experiment/"))
        for name in names
        if _within(name, BACKEND_MODULES)
    ]
    assert offenders == []


@pytest.mark.req("REQ-LLM-001")
def test_llm_imports_no_other_pericles_package() -> None:
    """AC1: the gateway knows no villages."""
    offenders = [
        f"{relative}: {name}"
        for relative, names in _sources()
        if relative.startswith("llm/")
        for name in names
        if name.startswith("pericles") and name != "pericles" and not _within(name, LLM_MAY_IMPORT)
    ]
    assert offenders == []
