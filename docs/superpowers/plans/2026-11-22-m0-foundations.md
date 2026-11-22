# M0 Foundations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A working, gated engineering foundation for Pericles: Python package skeleton with lint, type and test tooling; requirement → test traceability; ADR checks; mutation-testing gates; a Three.js viewer skeleton; CI; and a GitHub backlog generated from the requirements catalog.

**Architecture:** The product code lives in `src/pericles/` (empty sub-packages for now). Dev tooling lives in `tools/pericles_tools/`, a separate importable package that is tested but neither shipped nor mutation-tested. Every gate is a small pure-Python module with a `main(argv) -> int` CLI, so CI and developers run the same commands. The viewer is an independent pnpm project in `viewer/`.

**Tech Stack:** Python ≥ 3.12, uv, hatchling, pytest, Hypothesis, ruff, mypy (strict), mutmut 3.8.x, PyYAML; Node ≥ 20, pnpm, Vite, TypeScript, Three.js, Vitest, ESLint (typescript-eslint), Stryker; GitHub Actions; `gh` CLI.

**Spec:** `docs/superpowers/specs/2026-11-22-pericles-design.md` (§11 Engineering process). Requirements covered by this plan: REQ-NFR-002, REQ-NFR-005, REQ-NFR-006, REQ-NFR-007, REQ-NFR-008 (`docs/requirements/nfr.md`).

**Later milestones:** M1–M5 each get their own plan, written when the previous milestone is done (they depend on code that does not exist yet).

## Global Constraints

- Python `requires-python = ">=3.12"`. CI tests on Python 3.12 and 3.14 (Linux). Local development is on macOS Apple Silicon.
- Node ≥ 20 (CI uses 22).
- `mypy --strict` on `src`, `tools` and `tests`. `ruff check` + `ruff format --check`, line length 100.
- Tests link to requirements only via `@pytest.mark.req("REQ-…")` (literal strings, `pytest.mark.req` spelled out), either as a decorator or as module-level `pytestmark`.
- pytest runs with `--strict-markers`, and `slow` tests are excluded by default.
- Mutation-score targets: ≥ 80% for `pericles.core`, ≥ 70% for `pericles.agents` and `pericles.llm` (Python). Stryker break threshold 70 (viewer).
- Requirement docs format: `### REQ-<AREA>-NNN: Title`, then a line `<Must|Should|Could> · M<n> · <Proposed|Accepted|Implemented|Withdrawn>`, then an optional statement, then `- ACn: …` lines.
- Every commit message ends with the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run Python tools with `PYTHONPATH=tools` when invoking them via `python -m` (pytest gets it from `pythonpath = ["tools"]`).
- All work happens on branch `m0-foundations` (create it before Task 1: `git switch -c m0-foundations`) and lands via a PR to `main`.

## Review Focus

1. **Small formatting slips in requirement docs** (an ASCII `-` instead of `·`, trailing spaces, CRLF line endings, a typo like `REQ-SIM-1`): the parser must either tolerate them (whitespace, CRLF) or fail loudly with `file:line`. It must never silently skip a requirement. Tests are in Task 2.
2. **Markers written in other valid forms** (module-level `pytestmark` as a single marker or a list, a decorator on a class, a method in a class, several IDs in one marker) must be detected. A non-literal argument (`pytest.mark.req(SOME_ID)`) must be an error, not silently ignored. Tests are in Task 3.
3. **mutmut crashing or finding nothing:** mutmut exits 1 when no tests cover any mutant (verified with mutmut 3.8.1). The gate must pass when there is genuinely nothing to mutate, but fail when mutable code exists and mutmut produced no results. Tests are in Task 6.
4. **Re-running the backlog sync after a partial failure** (network drop halfway) must not create duplicate issues. Re-running after a requirement title edit must not duplicate it either (match on the requirement ID). Tests are in Task 9.
5. **A new ADR added without updating the index, or an ADR deleted:** the ADR check must fail (index missing a link; numbering gap). Tests are in Task 5.

---

## File Structure

```
pyproject.toml                         # package, dev deps, pytest/mypy/ruff/mutmut config
uv.lock                                # committed
.gitignore
CLAUDE.md                              # contributor/agent workflow (Task 10)
src/pericles/__init__.py               # __version__
src/pericles/{core,agents,llm,experiment,server,analysis}/__init__.py
tools/pericles_tools/__init__.py
tools/pericles_tools/requirements.py   # parse docs/requirements/*.md + milestones.md
tools/pericles_tools/markers.py        # AST scan of tests for req markers
tools/pericles_tools/traceability.py   # evaluate rules, render matrix, CLI
tools/pericles_tools/adr.py            # ADR structure/index checks, CLI
tools/pericles_tools/mutation_gate.py  # run mutmut, per-package score gate, CLI
tools/pericles_tools/backlog.py        # sync GitHub labels/milestones/issues, CLI
tests/pericles/test_package.py         # runs under mutmut (product tests only)
tests/tools/test_*.py                  # tool tests (not run under mutmut)
viewer/                                # pnpm project: Vite + TS + Three.js + Vitest + Stryker
.github/workflows/ci.yml
.github/workflows/mutation-nightly.yml
```

---

### Task 1: Python package scaffold and quality tooling

**Files:**
- Create: `pyproject.toml`, `.gitignore`, `src/pericles/__init__.py`, `src/pericles/{core,agents,llm,experiment,server,analysis}/__init__.py`, `tools/pericles_tools/__init__.py`, `tests/pericles/test_package.py`, `tests/tools/test_platform.py`

**Interfaces:**
- Produces: importable `pericles` (with `pericles.__version__: str`) and its six sub-packages; importable `pericles_tools` under pytest; registered pytest markers `req` and `slow`.

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "pericles"
version = "0.0.1"
description = "A research sandbox: a village society whose villagers are driven by local LLMs"
readme = "README.md"
requires-python = ">=3.12"
dependencies = []

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/pericles"]

[dependency-groups]
dev = [
    "pytest>=8.3",
    "hypothesis>=6.120",
    "mypy>=1.13",
    "ruff>=0.8",
    "mutmut>=3.8,<4",
    "pyyaml>=6.0",
    "types-PyYAML>=6.0",
]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["tools"]
addopts = "--strict-markers -m 'not slow'"
markers = [
    "req(*ids): links a test to one or more requirement IDs (REQ-<AREA>-NNN)",
    "slow: needs live external services such as Ollama; excluded by default",
]

[tool.mypy]
strict = true
python_version = "3.12"
files = ["src", "tools", "tests"]
mypy_path = "tools"

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "RUF"]
# mutmut names class-method mutants with U+01C1 (e.g. "xǁWorldǁstep__mutmut_1")
allowed-confusables = ["ǁ"]

[tool.mutmut]
source_paths = ["src/pericles"]
pytest_add_cli_args_test_selection = ["tests/pericles"]
```

- [ ] **Step 2: Create `.gitignore`**

```gitignore
.venv/
__pycache__/
*.pyc
.mypy_cache/
.ruff_cache/
.pytest_cache/
.hypothesis/
mutants/
runs/
docs/requirements/traceability.md
viewer/node_modules/
viewer/dist/
viewer/reports/
viewer/.stryker-tmp/
.DS_Store
```

- [ ] **Step 3: Write the failing tests**

`tests/pericles/test_package.py`:

```python
import importlib

import pytest

import pericles

SUBPACKAGES = ("core", "agents", "llm", "experiment", "server", "analysis")


@pytest.mark.req("REQ-NFR-002")
def test_package_exposes_version() -> None:
    """AC1: the core package installs and imports on the supported Python versions."""
    assert isinstance(pericles.__version__, str)
    assert pericles.__version__


@pytest.mark.req("REQ-NFR-002")
@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackages_import(name: str) -> None:
    """AC1: every architectural package from spec §3.1 exists and imports."""
    module = importlib.import_module(f"pericles.{name}")
    assert module.__name__ == f"pericles.{name}"
```

`tests/tools/test_platform.py`:

```python
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("REQ-NFR-002")
def test_python_floor_is_3_12() -> None:
    """AC1: the declared Python floor is 3.12."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.12"
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv sync && uv run pytest -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles'` (`test_platform` passes).

- [ ] **Step 5: Create the packages**

`src/pericles/__init__.py`:

```python
"""Pericles: a village society whose villagers are driven by local LLMs."""

__version__ = "0.0.1"
```

Each of `src/pericles/core/__init__.py`, `agents`, `llm`, `experiment`, `server`, `analysis` contains one docstring line:

```python
"""Deterministic simulation engine (spec §3.1)."""
```

Use these docstrings respectively. core: `"""Deterministic simulation engine (spec §3.1)."""`; agents: `"""Villager minds, executor and communication (spec §5)."""`; llm: `"""LLM gateway and backends (spec §6)."""`; experiment: `"""Experiment config, runner and interventions (spec §7)."""`; server: `"""WebSocket server for the viewer (spec §9)."""`; analysis: `"""Metrics and reports from event logs (spec §8)."""`.

`tools/pericles_tools/__init__.py`:

```python
"""Development tooling for Pericles (not shipped, not mutation-tested)."""
```

- [ ] **Step 6: Run all gates**

Run: `uv sync && uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check .`
Expected: all tests PASS (8 passed); mypy `Success`; ruff clean. If `ruff format --check` fails, run `uv run ruff format .` and re-run.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock .gitignore src tools tests
git commit -m "build: Python package scaffold with pytest, mypy, ruff and mutmut config"
```

---

### Task 2: Requirements catalog parser

**Files:**
- Create: `tools/pericles_tools/requirements.py`
- Test: `tests/tools/test_requirements.py`

**Interfaces:**
- Produces:
  - `class RequirementsError(Exception)`
  - `@dataclass(frozen=True) class Requirement: id: str; title: str; priority: str; milestone: str; status: str; statement: str; criteria: tuple[tuple[str, str], ...]; source: Path; line: int`, with property `area -> str` (e.g. `"SIM"`)
  - `parse_file(path: Path) -> list[Requirement]`
  - `load_catalog(directory: Path) -> dict[str, Requirement]` (keyed by ID; skips `README.md`, `milestones.md`, `traceability.md`)
  - `load_milestones(path: Path) -> dict[str, bool]` (e.g. `{"M0": False}`)

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_requirements.py`:

```python
from pathlib import Path

import pytest

from pericles_tools.requirements import (
    RequirementsError,
    load_catalog,
    load_milestones,
    parse_file,
)

pytestmark = pytest.mark.req("REQ-NFR-007")

SAMPLE = """# SIM: Simulation

### REQ-SIM-001: Seeded map generation
Must · M1 · Accepted
The engine generates a map.
- AC1: Same seed, same map.
- AC2: Different seeds differ.

### REQ-SIM-002: Tick loop
Should · M1 · Implemented
- AC1: Deterministic.
"""

MILESTONES = """# Milestones

| Milestone | Title | Done |
|-----------|-------|------|
| M0 | Foundations | yes |
| M1 | Headless sim | no |
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_meta_statement_and_criteria(tmp_path: Path) -> None:
    reqs = parse_file(write(tmp_path, "sim.md", SAMPLE))
    assert [r.id for r in reqs] == ["REQ-SIM-001", "REQ-SIM-002"]
    first = reqs[0]
    assert first.title == "Seeded map generation"
    assert (first.priority, first.milestone, first.status) == ("Must", "M1", "Accepted")
    assert first.statement == "The engine generates a map."
    assert first.criteria == (("AC1", "Same seed, same map."), ("AC2", "Different seeds differ."))
    assert first.area == "SIM"
    assert first.line == 3
    assert reqs[1].statement == ""
    assert reqs[1].status == "Implemented"


def test_tolerates_crlf_and_trailing_whitespace(tmp_path: Path) -> None:
    reqs = parse_file(write(tmp_path, "sim.md", SAMPLE.replace("\n", "  \r\n")))
    assert reqs[0].title == "Seeded map generation"
    assert reqs[0].criteria[0] == ("AC1", "Same seed, same map.")
    assert reqs[0].status == "Accepted"


def test_malformed_meta_line_reports_file_and_line(tmp_path: Path) -> None:
    text = SAMPLE.replace("Must · M1 · Accepted", "Must - M1 - Accepted")
    with pytest.raises(RequirementsError, match=r"sim\.md:4:"):
        parse_file(write(tmp_path, "sim.md", text))


def test_malformed_heading_is_an_error(tmp_path: Path) -> None:
    text = SAMPLE.replace("### REQ-SIM-002: Tick loop", "### REQ-SIM-2: Tick loop")
    with pytest.raises(RequirementsError, match=r"sim\.md:9: malformed requirement heading"):
        parse_file(write(tmp_path, "sim.md", text))


def test_requirement_without_criteria_is_an_error(tmp_path: Path) -> None:
    text = "### REQ-SIM-001: X\nMust · M1 · Accepted\nJust a statement.\n"
    with pytest.raises(RequirementsError, match="no acceptance criteria"):
        parse_file(write(tmp_path, "sim.md", text))


def test_duplicate_criterion_is_an_error(tmp_path: Path) -> None:
    text = "### REQ-SIM-001: X\nMust · M1 · Accepted\n- AC1: a\n- AC1: b\n"
    with pytest.raises(RequirementsError, match="duplicate AC1"):
        parse_file(write(tmp_path, "sim.md", text))


def test_catalog_rejects_duplicate_ids_across_files(tmp_path: Path) -> None:
    write(tmp_path, "sim.md", SAMPLE)
    write(tmp_path, "eco.md", "### REQ-SIM-001: Again\nMust · M3 · Accepted\n- AC1: x\n")
    with pytest.raises(RequirementsError, match=r"duplicate REQ-SIM-001.*eco\.md.*sim\.md"):
        load_catalog(tmp_path)


def test_catalog_skips_index_milestones_and_matrix(tmp_path: Path) -> None:
    write(tmp_path, "sim.md", SAMPLE)
    write(tmp_path, "README.md", "### REQ-BAD-1: not a requirement\n")
    write(tmp_path, "milestones.md", MILESTONES)
    write(tmp_path, "traceability.md", "### REQ-BAD-1: generated\n")
    assert sorted(load_catalog(tmp_path)) == ["REQ-SIM-001", "REQ-SIM-002"]


def test_load_milestones(tmp_path: Path) -> None:
    assert load_milestones(write(tmp_path, "milestones.md", MILESTONES)) == {
        "M0": True,
        "M1": False,
    }


def test_malformed_milestone_row_is_an_error(tmp_path: Path) -> None:
    text = MILESTONES.replace("| M1 | Headless sim | no |", "| M1 | Headless sim | maybe |")
    with pytest.raises(RequirementsError, match=r"milestones\.md:6:"):
        load_milestones(write(tmp_path, "milestones.md", text))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools/test_requirements.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles_tools.requirements'`

- [ ] **Step 3: Implement `tools/pericles_tools/requirements.py`**

```python
"""Parse the requirements catalog in docs/requirements/ (see its README for the format)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HEADING = re.compile(r"^### (REQ-[A-Z]+-\d{3}): (.+?)\s*$")
META = re.compile(
    r"^(Must|Should|Could) · (M\d+) · (Proposed|Accepted|Implemented|Withdrawn)\s*$"
)
CRITERION = re.compile(r"^- (AC\d+): (.+?)\s*$")
MILESTONE_ROW = re.compile(r"^\|\s*(M\d+)\s*\|\s*(.+?)\s*\|\s*(yes|no)\s*\|\s*$")
SKIP_FILES = frozenset({"README.md", "milestones.md", "traceability.md"})


class RequirementsError(Exception):
    """The requirements catalog is malformed."""


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    priority: str
    milestone: str
    status: str
    statement: str
    criteria: tuple[tuple[str, str], ...]
    source: Path
    line: int

    @property
    def area(self) -> str:
        return self.id.split("-")[1]


def parse_file(path: Path) -> list[Requirement]:
    lines = path.read_text(encoding="utf-8").splitlines()
    reqs: list[Requirement] = []
    i = 0
    while i < len(lines):
        heading = HEADING.match(lines[i])
        if heading is None:
            if lines[i].startswith("### REQ-"):
                raise RequirementsError(
                    f"{path}:{i + 1}: malformed requirement heading: {lines[i].strip()!r}"
                )
            i += 1
            continue
        req_id, title = heading.group(1), heading.group(2)
        start = i + 1
        meta = META.match(lines[i + 1]) if i + 1 < len(lines) else None
        if meta is None:
            raise RequirementsError(
                f"{path}:{i + 2}: expected 'Priority · Milestone · Status' after {req_id}"
            )
        i += 2
        statement: list[str] = []
        criteria: list[tuple[str, str]] = []
        while i < len(lines) and not lines[i].startswith("### "):
            criterion = CRITERION.match(lines[i])
            if criterion is not None:
                ac_id = criterion.group(1)
                if any(existing == ac_id for existing, _ in criteria):
                    raise RequirementsError(f"{path}:{i + 1}: duplicate {ac_id} in {req_id}")
                criteria.append((ac_id, criterion.group(2)))
            elif lines[i].strip() and not criteria:
                statement.append(lines[i].strip())
            i += 1
        if not criteria:
            raise RequirementsError(f"{path}:{start}: {req_id} has no acceptance criteria")
        reqs.append(
            Requirement(
                id=req_id,
                title=title,
                priority=meta.group(1),
                milestone=meta.group(2),
                status=meta.group(3),
                statement=" ".join(statement),
                criteria=tuple(criteria),
                source=path,
                line=start,
            )
        )
    return reqs


def load_catalog(directory: Path) -> dict[str, Requirement]:
    catalog: dict[str, Requirement] = {}
    for path in sorted(directory.glob("*.md")):
        if path.name in SKIP_FILES:
            continue
        for req in parse_file(path):
            if req.id in catalog:
                other = catalog[req.id]
                raise RequirementsError(
                    f"duplicate {req.id}: {other.source}:{other.line} and {req.source}:{req.line}"
                )
            catalog[req.id] = req
    return catalog


def load_milestones(path: Path) -> dict[str, bool]:
    milestones: dict[str, bool] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not re.match(r"^\|\s*M\d", line):
            continue
        row = MILESTONE_ROW.match(line)
        if row is None:
            raise RequirementsError(
                f"{path}:{number}: expected '| M<n> | <title> | yes|no |', got {line.strip()!r}"
            )
        milestones[row.group(1)] = row.group(3) == "yes"
    return milestones
```

`load_catalog` reads files sorted by name, and the duplicate message names the first-seen location first (`eco.md` before `sim.md` in the test).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/tools/test_requirements.py -q && uv run mypy && uv run ruff check .`
Expected: 10 passed; mypy and ruff clean.

- [ ] **Step 5: Commit**

```bash
git add tools/pericles_tools/requirements.py tests/tools/test_requirements.py
git commit -m "feat(tools): requirements catalog parser"
```

---

### Task 3: Test marker scanner

**Files:**
- Create: `tools/pericles_tools/markers.py`
- Test: `tests/tools/test_markers.py`

**Interfaces:**
- Produces:
  - `class MarkerError(Exception)`
  - `@dataclass(frozen=True, order=True) class TestRef: req_id: str; nodeid: str` (nodeid like `tests/x/test_a.py::TestK::test_m`, or `tests/x/test_a.py` for module-level `pytestmark`)
  - `scan_file(path: Path, root: Path) -> list[TestRef]`
  - `scan_tests(test_dir: Path, root: Path) -> list[TestRef]` (files `test_*.py` and `*_test.py`, recursive, sorted)

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_markers.py`:

```python
from pathlib import Path

import pytest

from pericles_tools.markers import MarkerError, TestRef, scan_file, scan_tests

pytestmark = pytest.mark.req("REQ-NFR-007")


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_function_decorator(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "tests/test_a.py",
        'import pytest\n\n@pytest.mark.req("REQ-SIM-001")\ndef test_x() -> None: ...\n',
    )
    assert scan_file(path, tmp_path) == [TestRef("REQ-SIM-001", "tests/test_a.py::test_x")]


def test_multiple_ids_in_one_marker_and_stacked_markers(tmp_path: Path) -> None:
    src = (
        "import pytest\n\n"
        '@pytest.mark.req("REQ-SIM-001", "REQ-SIM-002")\n'
        '@pytest.mark.req("REQ-ECO-001")\n'
        "@pytest.mark.slow\n"
        "def test_x() -> None: ...\n"
    )
    refs = scan_file(write(tmp_path, "tests/test_a.py", src), tmp_path)
    assert sorted(r.req_id for r in refs) == ["REQ-ECO-001", "REQ-SIM-001", "REQ-SIM-002"]


def test_module_level_pytestmark_single_and_list(tmp_path: Path) -> None:
    single = write(
        tmp_path, "tests/test_s.py", 'import pytest\npytestmark = pytest.mark.req("REQ-A-001")\n'
    )
    listed = write(
        tmp_path,
        "tests/test_l.py",
        'import pytest\npytestmark = [pytest.mark.slow, pytest.mark.req("REQ-B-001")]\n',
    )
    assert scan_file(single, tmp_path) == [TestRef("REQ-A-001", "tests/test_s.py")]
    assert scan_file(listed, tmp_path) == [TestRef("REQ-B-001", "tests/test_l.py")]


def test_class_decorator_and_methods(tmp_path: Path) -> None:
    src = (
        "import pytest\n\n"
        '@pytest.mark.req("REQ-A-001")\n'
        "class TestThing:\n"
        '    @pytest.mark.req("REQ-A-002")\n'
        "    def test_m(self) -> None: ...\n"
    )
    refs = scan_file(write(tmp_path, "tests/test_c.py", src), tmp_path)
    assert refs == [
        TestRef("REQ-A-001", "tests/test_c.py::TestThing"),
        TestRef("REQ-A-002", "tests/test_c.py::TestThing::test_m"),
    ]


def test_non_literal_argument_is_an_error(tmp_path: Path) -> None:
    src = 'import pytest\nID = "REQ-A-001"\n\n@pytest.mark.req(ID)\ndef test_x() -> None: ...\n'
    with pytest.raises(MarkerError, match=r"test_a\.py:4: .*string literals"):
        scan_file(write(tmp_path, "tests/test_a.py", src), tmp_path)


def test_marker_without_ids_is_an_error(tmp_path: Path) -> None:
    src = "import pytest\n\n@pytest.mark.req()\ndef test_x() -> None: ...\n"
    with pytest.raises(MarkerError, match="at least one requirement ID"):
        scan_file(write(tmp_path, "tests/test_a.py", src), tmp_path)


def test_scan_tests_finds_both_naming_styles_recursively(tmp_path: Path) -> None:
    mark = 'import pytest\n\n@pytest.mark.req("REQ-A-001")\ndef test_x() -> None: ...\n'
    write(tmp_path, "tests/sub/test_one.py", mark)
    write(tmp_path, "tests/two_test.py", mark)
    write(tmp_path, "tests/helpers.py", mark)
    nodeids = [r.nodeid for r in scan_tests(tmp_path / "tests", tmp_path)]
    assert nodeids == ["tests/sub/test_one.py::test_x", "tests/two_test.py::test_x"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools/test_markers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles_tools.markers'`

- [ ] **Step 3: Implement `tools/pericles_tools/markers.py`**

```python
"""Find @pytest.mark.req(...) links from tests to requirements by static AST analysis."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


class MarkerError(Exception):
    """A req marker is written in a form the traceability check cannot read."""


@dataclass(frozen=True, order=True)
class TestRef:
    __test__ = False  # not a pytest test class

    req_id: str
    nodeid: str


def _is_req(func: ast.expr) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "req"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "pytest"
    )


def _ids(node: ast.expr, path: Path) -> list[str]:
    if not (isinstance(node, ast.Call) and _is_req(node.func)):
        return []
    ids: list[str] = []
    for arg in node.args:
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            raise MarkerError(f"{path}:{arg.lineno}: req marker arguments must be string literals")
        ids.append(arg.value)
    if not ids:
        raise MarkerError(f"{path}:{node.lineno}: req marker needs at least one requirement ID")
    return ids


def _refs(decorators: list[ast.expr], nodeid: str, path: Path) -> list[TestRef]:
    return [TestRef(req_id, nodeid) for d in decorators for req_id in _ids(d, path)]


def _scan_body(body: list[ast.stmt], prefix: str, path: Path) -> list[TestRef]:
    refs: list[TestRef] = []
    for stmt in body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            refs += _refs(stmt.decorator_list, f"{prefix}::{stmt.name}", path)
        elif isinstance(stmt, ast.ClassDef):
            nodeid = f"{prefix}::{stmt.name}"
            refs += _refs(stmt.decorator_list, nodeid, path)
            refs += _scan_body(stmt.body, nodeid, path)
    return refs


def scan_file(path: Path, root: Path) -> list[TestRef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(root).as_posix()
    refs: list[TestRef] = []
    for stmt in tree.body:
        if (
            isinstance(stmt, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets)
        ):
            value = stmt.value
            values = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
            refs += _refs(values, rel, path)
    return refs + _scan_body(tree.body, rel, path)


def scan_tests(test_dir: Path, root: Path) -> list[TestRef]:
    files = sorted(
        p
        for p in test_dir.rglob("*.py")
        if p.name.startswith("test_") or p.name.endswith("_test.py")
    )
    return [ref for path in files for ref in scan_file(path, root)]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/tools/test_markers.py -q && uv run mypy && uv run ruff check . && uv run ruff format --check .`
Expected: 7 passed; mypy and ruff clean (run `uv run ruff format .` if needed).

- [ ] **Step 5: Commit**

```bash
git add tools/pericles_tools/markers.py tests/tools/test_markers.py
git commit -m "feat(tools): static scanner for requirement markers in tests"
```

---

### Task 4: Traceability rules, matrix and CLI

**Files:**
- Create: `tools/pericles_tools/traceability.py`
- Test: `tests/tools/test_traceability.py`, `tests/tools/test_traceability_repo.py`

**Interfaces:**
- Consumes: `Requirement`, `load_catalog`, `load_milestones`, `RequirementsError` (Task 2); `TestRef`, `scan_tests`, `MarkerError` (Task 3).
- Produces:
  - `@dataclass(frozen=True) class Report: errors: tuple[str, ...]; gaps: tuple[str, ...]; coverage: Mapping[str, tuple[str, ...]]`
  - `evaluate(reqs: Mapping[str, Requirement], milestones: Mapping[str, bool], refs: Sequence[TestRef]) -> Report`
  - `render_matrix(reqs: Mapping[str, Requirement], report: Report) -> str`
  - `main(argv: Sequence[str] | None = None) -> int`. Subcommands: `check [--root DIR]` and `matrix [--root DIR] [--out FILE]` (default out: `docs/requirements/traceability.md`)

Rules (REQ-NFR-007):
1. A test referencing an unknown ID → error.
2. A test referencing a `Withdrawn` requirement → error.
3. A requirement whose milestone is not in `milestones.md` → error.
4. An `Implemented` requirement without tests → error.
5. A non-withdrawn requirement in a milestone marked done, without tests → error.
6. Any other non-withdrawn requirement without tests → gap (not an error).

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_traceability.py`:

```python
from pathlib import Path

import pytest

from pericles_tools.markers import TestRef
from pericles_tools.requirements import Requirement
from pericles_tools.traceability import evaluate, main, render_matrix

pytestmark = pytest.mark.req("REQ-NFR-007")


def req(req_id: str, status: str = "Accepted", milestone: str = "M1") -> Requirement:
    return Requirement(
        id=req_id,
        title=f"Title of {req_id}",
        priority="Must",
        milestone=milestone,
        status=status,
        statement="",
        criteria=(("AC1", "x"),),
        source=Path("docs/requirements/x.md"),
        line=1,
    )


def catalog(*reqs: Requirement) -> dict[str, Requirement]:
    return {r.id: r for r in reqs}


OPEN = {"M0": False, "M1": False}


def test_covered_requirement_has_no_errors_or_gaps() -> None:
    report = evaluate(catalog(req("REQ-A-001")), OPEN, [TestRef("REQ-A-001", "t.py::test_a")])
    assert report.errors == ()
    assert report.gaps == ()
    assert report.coverage["REQ-A-001"] == ("t.py::test_a",)


def test_unknown_id_in_test_is_an_error() -> None:
    report = evaluate(catalog(req("REQ-A-001")), OPEN, [TestRef("REQ-A-999", "t.py::test_a")])
    assert any("REQ-A-999" in e and "unknown" in e for e in report.errors)


def test_withdrawn_requirement_referenced_is_an_error() -> None:
    reqs = catalog(req("REQ-A-001", status="Withdrawn"))
    report = evaluate(reqs, OPEN, [TestRef("REQ-A-001", "t.py::test_a")])
    assert any("Withdrawn" in e for e in report.errors)


def test_implemented_without_tests_is_an_error() -> None:
    report = evaluate(catalog(req("REQ-A-001", status="Implemented")), OPEN, [])
    assert any("REQ-A-001" in e and "Implemented" in e for e in report.errors)


def test_done_milestone_without_tests_is_an_error_but_withdrawn_is_exempt() -> None:
    reqs = catalog(req("REQ-A-001", milestone="M0"), req("REQ-A-002", "Withdrawn", "M0"))
    report = evaluate(reqs, {"M0": True, "M1": False}, [])
    assert len(report.errors) == 1
    assert "REQ-A-001" in report.errors[0] and "M0" in report.errors[0]


def test_accepted_without_tests_in_open_milestone_is_a_gap() -> None:
    report = evaluate(catalog(req("REQ-A-001")), OPEN, [])
    assert report.errors == ()
    assert report.gaps == ("REQ-A-001",)


def test_unknown_milestone_is_an_error() -> None:
    report = evaluate(catalog(req("REQ-A-001", milestone="M9")), OPEN, [])
    assert any("M9" in e for e in report.errors)


def test_matrix_lists_every_requirement_with_tests_or_dash() -> None:
    reqs = catalog(req("REQ-A-001"), req("REQ-A-002"))
    report = evaluate(reqs, OPEN, [TestRef("REQ-A-001", "t.py::test_a")])
    matrix = render_matrix(reqs, report)
    assert "| REQ-A-001 | Title of REQ-A-001 | M1 | Accepted | `t.py::test_a` |" in matrix
    assert "| REQ-A-002 | Title of REQ-A-002 | M1 | Accepted | — |" in matrix
    assert "Open gaps: 1" in matrix


def make_repo(root: Path, status: str, with_test: bool) -> None:
    (root / "docs/requirements").mkdir(parents=True)
    (root / "docs/requirements/nfr.md").write_text(
        f"### REQ-NFR-001: Thing\nMust · M0 · {status}\n- AC1: x\n", encoding="utf-8"
    )
    (root / "docs/requirements/milestones.md").write_text(
        "| M0 | Foundations | no |\n", encoding="utf-8"
    )
    (root / "tests").mkdir()
    if with_test:
        (root / "tests/test_x.py").write_text(
            'import pytest\n\n@pytest.mark.req("REQ-NFR-001")\ndef test_x() -> None: ...\n',
            encoding="utf-8",
        )


def test_cli_check_passes_and_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    make_repo(good, "Implemented", with_test=True)
    make_repo(bad, "Implemented", with_test=False)
    assert main(["check", "--root", str(good)]) == 0
    assert main(["check", "--root", str(bad)]) == 1
    assert "REQ-NFR-001" in capsys.readouterr().out


def test_cli_reports_malformed_catalog_as_failure(tmp_path: Path) -> None:
    make_repo(tmp_path, "Implemented", with_test=True)
    (tmp_path / "docs/requirements/nfr.md").write_text("### REQ-NFR-1: bad\n", encoding="utf-8")
    assert main(["check", "--root", str(tmp_path)]) == 1


def test_cli_matrix_writes_file(tmp_path: Path) -> None:
    make_repo(tmp_path, "Accepted", with_test=False)
    out = tmp_path / "matrix.md"
    assert main(["matrix", "--root", str(tmp_path), "--out", str(out)]) == 0
    assert "| REQ-NFR-001 |" in out.read_text(encoding="utf-8")
```

`tests/tools/test_traceability_repo.py`:

```python
from pathlib import Path

import pytest

from pericles_tools.markers import scan_tests
from pericles_tools.requirements import load_catalog, load_milestones
from pericles_tools.traceability import evaluate

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("REQ-NFR-007")
def test_repository_catalog_and_tests_are_consistent() -> None:
    """AC1/AC2: the real catalog parses and satisfies the traceability rules."""
    reqs = load_catalog(ROOT / "docs/requirements")
    milestones = load_milestones(ROOT / "docs/requirements/milestones.md")
    report = evaluate(reqs, milestones, scan_tests(ROOT / "tests", ROOT))
    assert report.errors == ()
    assert len(reqs) >= 89
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools/test_traceability.py tests/tools/test_traceability_repo.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles_tools.traceability'`

- [ ] **Step 3: Implement `tools/pericles_tools/traceability.py`**

```python
"""Requirement → test traceability: rules, matrix, CLI (REQ-NFR-007, ADR-0008)."""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pericles_tools.markers import MarkerError, TestRef, scan_tests
from pericles_tools.requirements import (
    Requirement,
    RequirementsError,
    load_catalog,
    load_milestones,
)

DEFAULT_MATRIX = Path("docs/requirements/traceability.md")


@dataclass(frozen=True)
class Report:
    errors: tuple[str, ...]
    gaps: tuple[str, ...]
    coverage: Mapping[str, tuple[str, ...]]


def evaluate(
    reqs: Mapping[str, Requirement],
    milestones: Mapping[str, bool],
    refs: Sequence[TestRef],
) -> Report:
    errors: list[str] = []
    coverage: dict[str, list[str]] = {req_id: [] for req_id in reqs}
    for ref in sorted(refs):
        req = reqs.get(ref.req_id)
        if req is None:
            errors.append(f"{ref.nodeid}: references unknown requirement {ref.req_id}")
        elif req.status == "Withdrawn":
            errors.append(f"{ref.nodeid}: references Withdrawn requirement {ref.req_id}")
        else:
            coverage[ref.req_id].append(ref.nodeid)
    gaps: list[str] = []
    for req_id in sorted(reqs):
        req = reqs[req_id]
        if req.milestone not in milestones:
            errors.append(f"{req_id}: milestone {req.milestone} is not listed in milestones.md")
            continue
        if req.status == "Withdrawn" or coverage[req_id]:
            continue
        if req.status == "Implemented":
            errors.append(f"{req_id}: status Implemented but no test references it")
        elif milestones[req.milestone]:
            errors.append(f"{req_id}: milestone {req.milestone} is done but no test references it")
        else:
            gaps.append(req_id)
    return Report(
        errors=tuple(errors),
        gaps=tuple(gaps),
        coverage={k: tuple(v) for k, v in coverage.items()},
    )


def render_matrix(reqs: Mapping[str, Requirement], report: Report) -> str:
    lines = [
        "# Traceability Matrix",
        "",
        "_Generated by `python -m pericles_tools.traceability matrix`. Do not edit._",
        "",
        "| Requirement | Title | Milestone | Status | Tests |",
        "|---|---|---|---|---|",
    ]
    for req_id in sorted(reqs):
        req = reqs[req_id]
        tests = "<br>".join(f"`{t}`" for t in report.coverage.get(req_id, ())) or "—"
        lines.append(f"| {req_id} | {req.title} | {req.milestone} | {req.status} | {tests} |")
    lines += ["", f"Open gaps: {len(report.gaps)}", f"Errors: {len(report.errors)}", ""]
    return "\n".join(lines)


def _load(root: Path) -> tuple[dict[str, Requirement], Report]:
    reqs = load_catalog(root / "docs/requirements")
    milestones = load_milestones(root / "docs/requirements/milestones.md")
    return reqs, evaluate(reqs, milestones, scan_tests(root / "tests", root))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pericles_tools.traceability")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check", help="fail on traceability errors")
    check.add_argument("--root", type=Path, default=Path("."))
    matrix = sub.add_parser("matrix", help="write the traceability matrix")
    matrix.add_argument("--root", type=Path, default=Path("."))
    matrix.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    root: Path = args.root
    try:
        reqs, report = _load(root)
    except (RequirementsError, MarkerError) as exc:
        print(f"error: {exc}")
        return 1
    if args.command == "matrix":
        out: Path = args.out if args.out is not None else root / DEFAULT_MATRIX
        out.write_text(render_matrix(reqs, report), encoding="utf-8")
        print(f"wrote {out}")
        return 0
    for error in report.errors:
        print(f"error: {error}")
    covered = sum(1 for tests in report.coverage.values() if tests)
    print(f"{len(reqs)} requirements, {covered} covered, {len(report.gaps)} open gaps")
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests and the real check**

Run: `uv run pytest tests/tools -q && PYTHONPATH=tools uv run python -m pericles_tools.traceability check`
Expected: all pass; the check prints `89 requirements, 2 covered, 87 open gaps` (REQ-NFR-002 from Task 1, REQ-NFR-007 from Tasks 2–4) and exits 0.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run mypy && uv run ruff check . && uv run ruff format --check .
git add tools/pericles_tools/traceability.py tests/tools/test_traceability.py tests/tools/test_traceability_repo.py
git commit -m "feat(tools): traceability rules, matrix and CLI"
```

---

### Task 5: ADR structure and index check

**Files:**
- Create: `tools/pericles_tools/adr.py`
- Test: `tests/tools/test_adr.py`

**Interfaces:**
- Produces: `check_adrs(adr_dir: Path) -> list[str]` (error messages; empty = OK); `main(argv: Sequence[str] | None = None) -> int`, subcommand `check [--root DIR]`.

Rules (REQ-NFR-008): file names `NNNN-kebab-title.md`; first line `# ADR-NNNN: <title>` matching the file number; a `- **Status:** …` line; sections `## Context`, `## Decision`, `## Consequences`; numbers contiguous from 0001 (deleting one breaks the sequence); `README.md` links every ADR file.

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_adr.py`:

```python
from pathlib import Path

import pytest

from pericles_tools.adr import check_adrs, main

pytestmark = pytest.mark.req("REQ-NFR-008")

ROOT = Path(__file__).resolve().parents[2]


def adr_text(number: str, title: str = "Title") -> str:
    return (
        f"# ADR-{number}: {title}\n\n- **Status:** Accepted\n- **Date:** 2026-11-22\n\n"
        "## Context\n\nc\n\n## Decision\n\nd\n\n## Consequences\n\nq\n"
    )


def make(tmp_path: Path, numbers: list[str], index: list[str] | None = None) -> Path:
    for n in numbers:
        (tmp_path / f"{n}-some-title.md").write_text(adr_text(n), encoding="utf-8")
    linked = numbers if index is None else index
    rows = "\n".join(f"| [{n}]({n}-some-title.md) | Title | Accepted |" for n in linked)
    (tmp_path / "README.md").write_text(f"# ADRs\n\n{rows}\n", encoding="utf-8")
    return tmp_path


def test_valid_set_passes(tmp_path: Path) -> None:
    assert check_adrs(make(tmp_path, ["0001", "0002"])) == []


def test_missing_index_entry_fails(tmp_path: Path) -> None:
    errors = check_adrs(make(tmp_path, ["0001", "0002"], index=["0001"]))
    assert errors == ["README.md: index does not link 0002-some-title.md"]


def test_numbering_gap_fails(tmp_path: Path) -> None:
    errors = check_adrs(make(tmp_path, ["0001", "0003"]))
    assert any("contiguous" in e for e in errors)


def test_heading_must_match_file_number(tmp_path: Path) -> None:
    make(tmp_path, ["0001"])
    (tmp_path / "0001-some-title.md").write_text(adr_text("0002"), encoding="utf-8")
    assert any("# ADR-0001: " in e for e in check_adrs(tmp_path))


@pytest.mark.parametrize("missing", ["## Context", "## Decision", "## Consequences", "**Status:**"])
def test_required_parts(tmp_path: Path, missing: str) -> None:
    make(tmp_path, ["0001"])
    path = tmp_path / "0001-some-title.md"
    path.write_text(path.read_text(encoding="utf-8").replace(missing, "## Other"), encoding="utf-8")
    assert check_adrs(tmp_path) != []


def test_bad_file_name_fails(tmp_path: Path) -> None:
    make(tmp_path, ["0001"])
    (tmp_path / "Decision About X.md").write_text(adr_text("0002"), encoding="utf-8")
    assert any("NNNN-kebab-title.md" in e for e in check_adrs(tmp_path))


def test_repository_adrs_pass() -> None:
    """AC1: the real ADR set is well-formed and fully indexed."""
    assert check_adrs(ROOT / "docs/adr") == []
    assert main(["check", "--root", str(ROOT)]) == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools/test_adr.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles_tools.adr'`

- [ ] **Step 3: Implement `tools/pericles_tools/adr.py`**

```python
"""Check ADR files for structure, numbering and index completeness (REQ-NFR-008)."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

ADR_FILE = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
SECTIONS = ("Context", "Decision", "Consequences")


def check_adrs(adr_dir: Path) -> list[str]:
    errors: list[str] = []
    files = sorted(p for p in adr_dir.glob("*.md") if p.name != "README.md")
    numbers: list[int] = []
    for path in files:
        match = ADR_FILE.match(path.name)
        if match is None:
            errors.append(f"{path.name}: file name must be NNNN-kebab-title.md")
            continue
        number = match.group(1)
        numbers.append(int(number))
        text = path.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        if not first.startswith(f"# ADR-{number}: "):
            errors.append(f"{path.name}: first line must be '# ADR-{number}: <title>'")
        if not re.search(r"^- \*\*Status:\*\* \S", text, re.MULTILINE):
            errors.append(f"{path.name}: missing '- **Status:** ...' line")
        for section in SECTIONS:
            if not re.search(rf"^## {section}\s*$", text, re.MULTILINE):
                errors.append(f"{path.name}: missing '## {section}' section")
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        found = ", ".join(f"{n:04d}" for n in sorted(numbers))
        errors.append(f"ADR numbers must be contiguous from 0001 (ADRs are never deleted): {found}")
    index = adr_dir / "README.md"
    if not index.exists():
        errors.append("README.md: ADR index is missing")
    else:
        index_text = index.read_text(encoding="utf-8")
        for path in files:
            if f"]({path.name})" not in index_text:
                errors.append(f"README.md: index does not link {path.name}")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pericles_tools.adr")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    errors = check_adrs(args.root / "docs/adr")
    for error in errors:
        print(f"error: {error}")
    print("ADRs OK" if not errors else f"{len(errors)} ADR error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests and the real check**

Run: `uv run pytest tests/tools/test_adr.py -q && PYTHONPATH=tools uv run python -m pericles_tools.adr check`
Expected: all pass; prints `ADRs OK`. If the real check reports problems in `docs/adr/`, fix the ADR document (not the checker) and re-run.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run mypy && uv run ruff check . && uv run ruff format --check .
git add tools/pericles_tools/adr.py tests/tools/test_adr.py
git commit -m "feat(tools): ADR structure and index check"
```

---

### Task 6: Python mutation-testing gate

**Files:**
- Create: `tools/pericles_tools/mutation_gate.py`
- Test: `tests/tools/test_mutation_gate.py`

**Interfaces:**
- Produces:
  - `THRESHOLDS: dict[str, float] = {"pericles.core": 0.80, "pericles.agents": 0.70, "pericles.llm": 0.70}`
  - `@dataclass(frozen=True) class Score: killed: int; survived: int`, with properties `total -> int` and `ratio -> float` (1.0 when total is 0)
  - `parse_results(text: str) -> dict[str, str]` (mutant name → status)
  - `package_of(mutant: str) -> str` (e.g. `pericles.core.world.xǁWǁstep__mutmut_3` → `pericles.core`)
  - `scores(results: Mapping[str, str], packages: Iterable[str]) -> dict[str, Score]`
  - `failures(scores: Mapping[str, Score], thresholds: Mapping[str, float]) -> list[str]`
  - `module_globs(changed_files: Iterable[str]) -> list[str]`
  - `has_mutable_code(files: Iterable[Path]) -> bool`
  - `Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]`
  - `main(argv: Sequence[str] | None = None, runner: Runner = _run, root: Path = Path(".")) -> int`, subcommand `run [--changed-since REF]`

Verified mutmut 3.8.1 behaviour this design relies on:
- `mutmut results --all true` prints lines `    <module>.<x_func|xǁClassǁmethod>__mutmut_<n>: <status>`.
- `mutmut run <glob>…` accepts mutant-name globs such as `pericles.core.world.*`.
- `mutmut run` exits 1 when no tests cover any mutant.

Statuses: `killed`, `timeout`, `segfault` count as killed. `survived`, `no tests`, `suspicious` count as survived. `not checked` and `skipped` are ignored.

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_mutation_gate.py`:

```python
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from pericles_tools.mutation_gate import (
    THRESHOLDS,
    Score,
    failures,
    has_mutable_code,
    main,
    module_globs,
    package_of,
    parse_results,
    scores,
)

pytestmark = pytest.mark.req("REQ-NFR-006")

RESULTS = """
    pericles.core.world.x_step__mutmut_1: killed
    pericles.core.world.xǁWorldǁtick__mutmut_2: survived
    pericles.core.world.x_step__mutmut_3: timeout
    pericles.core.world.x_step__mutmut_4: not checked
    pericles.llm.gateway.x_call__mutmut_1: no tests
    pericles.llm.gateway.x_call__mutmut_2: killed
    pericles.experiment.run.x_go__mutmut_1: survived
"""


def test_thresholds_match_the_requirement() -> None:
    """AC2: core ≥ 80%, agents and llm ≥ 70%."""
    assert THRESHOLDS == {"pericles.core": 0.80, "pericles.agents": 0.70, "pericles.llm": 0.70}


def test_parse_results_and_package_of() -> None:
    results = parse_results(RESULTS)
    assert results["pericles.core.world.xǁWorldǁtick__mutmut_2"] == "survived"
    assert results["pericles.llm.gateway.x_call__mutmut_1"] == "no tests"
    assert package_of("pericles.core.world.xǁWorldǁtick__mutmut_2") == "pericles.core"


def test_scores_count_statuses_and_ignore_unchecked() -> None:
    result = scores(parse_results(RESULTS), THRESHOLDS)
    assert result["pericles.core"] == Score(killed=2, survived=1)
    assert result["pericles.llm"] == Score(killed=1, survived=1)
    assert result["pericles.agents"] == Score(killed=0, survived=0)
    assert "pericles.experiment" not in result


def test_score_ratio() -> None:
    assert Score(killed=3, survived=1).ratio == 0.75
    assert Score(killed=0, survived=0).ratio == 1.0


def test_failures_only_for_packages_below_threshold_with_mutants() -> None:
    result = {
        "pericles.core": Score(killed=79, survived=21),
        "pericles.llm": Score(killed=7, survived=3),
        "pericles.agents": Score(killed=0, survived=0),
    }
    messages = failures(result, THRESHOLDS)
    assert len(messages) == 1
    assert "pericles.core" in messages[0] and "79.0%" in messages[0]


def test_exact_threshold_passes() -> None:
    assert failures({"pericles.core": Score(killed=80, survived=20)}, THRESHOLDS) == []


def test_module_globs_from_changed_files() -> None:
    changed = [
        "src/pericles/core/world.py",
        "src/pericles/agents/__init__.py",
        "src/pericles/experiment/run.py",
        "tests/pericles/test_world.py",
        "src/pericles/core/content.yaml",
    ]
    assert module_globs(changed) == ["pericles.core.world.*", "pericles.agents.x*"]


def test_has_mutable_code(tmp_path: Path) -> None:
    empty = tmp_path / "a.py"
    empty.write_text('"""Docstring only."""\n__version__ = "1"\n', encoding="utf-8")
    code = tmp_path / "b.py"
    code.write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    assert has_mutable_code([empty]) is False
    assert has_mutable_code([empty, code]) is True


class FakeRunner:
    def __init__(self, results: str, run_code: int = 0, diff: str = "") -> None:
        self.results, self.run_code, self.diff = results, run_code, diff
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        if args[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(list(args), 0, self.diff, "")
        if args[:2] == ["mutmut", "run"]:
            return subprocess.CompletedProcess(list(args), self.run_code, "", "")
        return subprocess.CompletedProcess(list(args), 0, self.results, "")


def make_src(root: Path, with_code: bool) -> None:
    pkg = root / "src/pericles/core"
    pkg.mkdir(parents=True)
    body = "def f() -> int:\n    return 1\n" if with_code else '"""Empty."""\n'
    (pkg / "world.py").write_text(body, encoding="utf-8")


def test_main_skips_when_nothing_to_mutate(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=False)
    runner = FakeRunner(results="")
    assert main(["run"], runner=runner, root=tmp_path) == 0
    assert not any(call[0] == "mutmut" for call in runner.calls)


def test_main_fails_when_mutmut_produces_no_results_for_real_code(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=True)
    assert main(["run"], runner=FakeRunner(results="", run_code=1), root=tmp_path) == 1


def test_main_fails_below_threshold_and_passes_above(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=True)
    low = "    pericles.core.world.x_f__mutmut_1: survived\n"
    high = "    pericles.core.world.x_f__mutmut_1: killed\n"
    assert main(["run"], runner=FakeRunner(results=low), root=tmp_path) == 1
    assert main(["run"], runner=FakeRunner(results=high), root=tmp_path) == 0


def test_main_changed_since_runs_only_changed_modules(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=True)
    runner = FakeRunner(
        results="    pericles.core.world.x_f__mutmut_1: killed\n",
        diff="src/pericles/core/world.py\nREADME.md\n",
    )
    assert main(["run", "--changed-since", "origin/main"], runner=runner, root=tmp_path) == 0
    assert ["git", "diff", "--name-only", "origin/main...HEAD"] in runner.calls
    assert ["mutmut", "run", "pericles.core.world.*"] in runner.calls


def test_main_changed_since_with_no_relevant_changes_passes(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=True)
    runner = FakeRunner(results="", diff="README.md\n")
    assert main(["run", "--changed-since", "origin/main"], runner=runner, root=tmp_path) == 0
    assert not any(call[0] == "mutmut" for call in runner.calls)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools/test_mutation_gate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles_tools.mutation_gate'`

- [ ] **Step 3: Implement `tools/pericles_tools/mutation_gate.py`**

```python
"""Run mutmut and enforce per-package mutation-score thresholds (REQ-NFR-006, ADR-0008)."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

THRESHOLDS: dict[str, float] = {
    "pericles.core": 0.80,
    "pericles.agents": 0.70,
    "pericles.llm": 0.70,
}
KILLED = frozenset({"killed", "timeout", "segfault"})
SURVIVED = frozenset({"survived", "no tests", "suspicious"})
RESULT_LINE = re.compile(r"^\s*(\S+__mutmut_\d+): (.+?)\s*$")

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class Score:
    killed: int
    survived: int

    @property
    def total(self) -> int:
        return self.killed + self.survived

    @property
    def ratio(self) -> float:
        return 1.0 if self.total == 0 else self.killed / self.total


def parse_results(text: str) -> dict[str, str]:
    results: dict[str, str] = {}
    for line in text.splitlines():
        match = RESULT_LINE.match(line)
        if match is not None:
            results[match.group(1)] = match.group(2)
    return results


def package_of(mutant: str) -> str:
    return ".".join(mutant.split(".")[:2])


def scores(results: Mapping[str, str], packages: Iterable[str]) -> dict[str, Score]:
    counts = {pkg: [0, 0] for pkg in packages}
    for mutant, status in results.items():
        pkg = package_of(mutant)
        if pkg not in counts:
            continue
        if status in KILLED:
            counts[pkg][0] += 1
        elif status in SURVIVED:
            counts[pkg][1] += 1
    return {pkg: Score(killed=k, survived=s) for pkg, (k, s) in counts.items()}


def failures(result: Mapping[str, Score], thresholds: Mapping[str, float]) -> list[str]:
    messages: list[str] = []
    for pkg in sorted(result):
        score = result[pkg]
        if score.total and score.ratio < thresholds[pkg]:
            messages.append(
                f"{pkg}: mutation score {score.ratio:.1%} below {thresholds[pkg]:.0%} "
                f"({score.killed} killed, {score.survived} survived)"
            )
    return messages


def module_globs(changed_files: Iterable[str]) -> list[str]:
    globs: list[str] = []
    for name in changed_files:
        if not (name.startswith("src/pericles/") and name.endswith(".py")):
            continue
        module = name.removeprefix("src/").removesuffix(".py").replace("/", ".")
        if package_of(module) not in THRESHOLDS:
            continue
        if module.endswith(".__init__"):
            globs.append(module.removesuffix(".__init__") + ".x*")
        else:
            globs.append(module + ".*")
    return globs


def has_mutable_code(files: Iterable[Path]) -> bool:
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) for n in ast.walk(tree)):
            return True
    return False


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


def _package_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pkg in THRESHOLDS:
        files += sorted((root / "src" / Path(*pkg.split("."))).rglob("*.py"))
    return files


def main(
    argv: Sequence[str] | None = None, runner: Runner = _run, root: Path = Path(".")
) -> int:
    parser = argparse.ArgumentParser(prog="pericles_tools.mutation_gate")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--changed-since", default=None, help="git ref; mutate only changed modules")
    args = parser.parse_args(argv)

    globs: list[str] = []
    targets = _package_files(root)
    if args.changed_since is not None:
        diff = runner(["git", "diff", "--name-only", f"{args.changed_since}...HEAD"])
        changed = diff.stdout.split()
        globs = module_globs(changed)
        if not globs:
            print("mutation gate: no mutation-tested modules changed")
            return 0
        targets = [root / n for n in changed if n.startswith("src/") and n.endswith(".py")]
    if not has_mutable_code(p for p in targets if p.exists()):
        print("mutation gate: no functions to mutate yet")
        return 0

    run_proc = runner(["mutmut", "run", *globs])
    results = parse_results(runner(["mutmut", "results", "--all", "true"]).stdout)
    result = scores(results, THRESHOLDS)
    if not any(score.total for score in result.values()):
        print(f"mutation gate: mutmut produced no results (exit {run_proc.returncode})")
        print(run_proc.stdout[-2000:], run_proc.stderr[-2000:])
        return 1
    for pkg in sorted(result):
        score = result[pkg]
        if score.total:
            need = THRESHOLDS[pkg]
            print(f"{pkg}: {score.ratio:.1%} ({score.killed}/{score.total}), need {need:.0%}")
    messages = failures(result, THRESHOLDS)
    for message in messages:
        print(f"error: {message}")
    return 1 if messages else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests and the real gate**

Run: `uv run pytest tests/tools/test_mutation_gate.py -q && PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run`
Expected: all pass; the real gate prints `mutation gate: no functions to mutate yet` and exits 0 (packages are still empty).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run mypy && uv run ruff check . && uv run ruff format --check .
git add tools/pericles_tools/mutation_gate.py tests/tools/test_mutation_gate.py
git commit -m "feat(tools): mutation-score gate over mutmut with per-package thresholds"
```

---

### Task 7: Viewer skeleton (Vite + TypeScript + Three.js + Vitest + ESLint + Stryker)

**Files:**
- Create: `viewer/package.json`, `viewer/pnpm-workspace.yaml`, `viewer/tsconfig.json`, `viewer/vite.config.ts`, `viewer/eslint.config.js`, `viewer/stryker.config.json`, `viewer/index.html`, `viewer/src/coords.ts`, `viewer/src/coords.test.ts`, `viewer/src/main.ts`
- Test: `viewer/src/coords.test.ts`, `tests/tools/test_viewer_config.py`

**Interfaces:**
- Produces: `tileToWorld(tx: number, ty: number, mapSize: number, tileSize?: number): WorldPos` with `interface WorldPos { x: number; z: number }`. It maps tile centres to world coordinates centred on the origin and throws `RangeError` outside the map. pnpm scripts `lint`, `typecheck`, `test`, `build`, `mutation`.

- [ ] **Step 1: Create the project files**

`viewer/package.json`:

```json
{
  "name": "pericles-viewer",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "typecheck": "tsc --noEmit",
    "lint": "eslint .",
    "test": "vitest run",
    "mutation": "stryker run"
  }
}
```

`viewer/pnpm-workspace.yaml` (lets esbuild run its install script under pnpm's build-script policy):

```yaml
onlyBuiltDependencies:
  - esbuild
```

`viewer/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022", "DOM"],
    "strict": true,
    "noUncheckedIndexedAccess": true,
    "noEmit": true,
    "skipLibCheck": true,
    "isolatedModules": true
  },
  "include": ["src", "vite.config.ts"]
}
```

`viewer/vite.config.ts`:

```ts
import { defineConfig } from "vitest/config";

export default defineConfig({
  test: { include: ["src/**/*.test.ts"] },
});
```

`viewer/eslint.config.js`:

```js
import js from "@eslint/js";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "reports", ".stryker-tmp", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.strict,
);
```

`viewer/stryker.config.json`:

```json
{
  "$schema": "./node_modules/@stryker-mutator/core/schema/stryker-schema.json",
  "testRunner": "vitest",
  "checkers": ["typescript"],
  "tsconfigFile": "tsconfig.json",
  "mutate": ["src/**/*.ts", "!src/**/*.test.ts", "!src/main.ts"],
  "thresholds": { "high": 85, "low": 70, "break": 70 },
  "reporters": ["clear-text", "progress", "html"]
}
```

`viewer/index.html`:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Pericles Viewer</title>
    <style>
      html, body { margin: 0; height: 100%; background: #1d2a1f; overflow: hidden; }
      canvas { display: block; }
    </style>
  </head>
  <body>
    <script type="module" src="/src/main.ts"></script>
  </body>
</html>
```

- [ ] **Step 2: Install dependencies**

Run:

```bash
cd viewer
pnpm add three
pnpm add -D typescript vite vitest @types/three eslint @eslint/js typescript-eslint \
  @stryker-mutator/core @stryker-mutator/vitest-runner @stryker-mutator/typescript-checker
```

Expected: `pnpm-lock.yaml` created, no "Ignored build scripts" warning for esbuild. If pnpm still warns that build scripts were ignored, check that `pnpm-workspace.yaml` is in `viewer/`, then run `pnpm rebuild esbuild`.

- [ ] **Step 3: Write the failing test**

`viewer/src/coords.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { tileToWorld } from "./coords";

describe("tileToWorld", () => {
  it("maps the first tile centre of a 4x4 map to the negative corner", () => {
    expect(tileToWorld(0, 0, 4)).toEqual({ x: -1.5, z: -1.5 });
  });

  it("maps the last tile centre to the positive corner", () => {
    expect(tileToWorld(3, 3, 4)).toEqual({ x: 1.5, z: 1.5 });
  });

  it("keeps x and z independent", () => {
    expect(tileToWorld(3, 0, 4)).toEqual({ x: 1.5, z: -1.5 });
  });

  it("scales with tile size", () => {
    expect(tileToWorld(0, 1, 2, 10)).toEqual({ x: -5, z: 5 });
  });

  it.each([
    [-1, 0],
    [0, -1],
    [4, 0],
    [0, 4],
    [0.5, 0],
  ])("rejects tile (%d, %d) outside a 4x4 map", (tx, ty) => {
    expect(() => tileToWorld(tx, ty, 4)).toThrow(RangeError);
  });
});
```

- [ ] **Step 4: Run it to verify it fails**

Run: `cd viewer && pnpm test`
Expected: FAIL with `Failed to resolve import "./coords"`

- [ ] **Step 5: Implement `viewer/src/coords.ts` and `viewer/src/main.ts`**

`viewer/src/coords.ts`:

```ts
export interface WorldPos {
  x: number;
  z: number;
}

/** Centre of tile (tx, ty) in world units, with the map centred on the origin. */
export function tileToWorld(tx: number, ty: number, mapSize: number, tileSize = 1): WorldPos {
  const inside = (v: number): boolean => Number.isInteger(v) && v >= 0 && v < mapSize;
  if (!inside(tx) || !inside(ty)) {
    throw new RangeError(`tile (${tx}, ${ty}) is outside a ${mapSize}x${mapSize} map`);
  }
  const offset = (mapSize * tileSize) / 2;
  return {
    x: tx * tileSize + tileSize / 2 - offset,
    z: ty * tileSize + tileSize / 2 - offset,
  };
}
```

`viewer/src/main.ts` (placeholder scene; real rendering arrives in M5):

```ts
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { tileToWorld } from "./coords";

const MAP_SIZE = 32;

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
document.body.appendChild(renderer.domElement);

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1d2a1f);
const camera = new THREE.PerspectiveCamera(50, window.innerWidth / window.innerHeight, 0.1, 500);
camera.position.set(24, 28, 24);
const controls = new OrbitControls(camera, renderer.domElement);

scene.add(new THREE.HemisphereLight(0xffffff, 0x3a5a3a, 2));
const ground = new THREE.Mesh(
  new THREE.PlaneGeometry(MAP_SIZE, MAP_SIZE),
  new THREE.MeshLambertMaterial({ color: 0x6b8f4e }),
);
ground.rotation.x = -Math.PI / 2;
scene.add(ground, new THREE.GridHelper(MAP_SIZE, MAP_SIZE, 0x2f3f2a, 0x4f6f3e));

const houseGeometry = new THREE.BoxGeometry(1, 1, 1);
const houseMaterial = new THREE.MeshLambertMaterial({ color: 0xb08850 });
for (const [tx, ty] of [[14, 14], [16, 15], [15, 17]] as const) {
  const { x, z } = tileToWorld(tx, ty, MAP_SIZE);
  const house = new THREE.Mesh(houseGeometry, houseMaterial);
  house.position.set(x, 0.5, z);
  scene.add(house);
}

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});
```

- [ ] **Step 6: Run all viewer gates**

Run: `cd viewer && pnpm test && pnpm typecheck && pnpm lint && pnpm build && pnpm mutation`
Expected: tests pass (8); typecheck, lint and build clean; Stryker reports a mutation score ≥ 70 and exits 0. If Stryker reports surviving mutants in `coords.ts`, add the missing test case to `coords.test.ts` (do not lower the threshold).

- [ ] **Step 7: Add the Python-side config test**

`tests/tools/test_viewer_config.py`:

```python
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("REQ-NFR-006")
def test_stryker_breaks_below_70_and_excludes_tests() -> None:
    """AC1/AC2: Stryker is configured for the viewer with a break threshold of 70."""
    config = json.loads((ROOT / "viewer/stryker.config.json").read_text(encoding="utf-8"))
    assert config["thresholds"]["break"] == 70
    assert "!src/**/*.test.ts" in config["mutate"]


@pytest.mark.req("REQ-NFR-005")
def test_viewer_exposes_gate_scripts() -> None:
    """AC1: the viewer has lint, typecheck and test scripts for CI."""
    scripts = json.loads((ROOT / "viewer/package.json").read_text(encoding="utf-8"))["scripts"]
    assert {"lint", "typecheck", "test", "build", "mutation"} <= scripts.keys()
```

Run: `uv run pytest tests/tools/test_viewer_config.py -q`
Expected: 2 passed.

- [ ] **Step 8: Commit**

```bash
git add viewer tests/tools/test_viewer_config.py
git commit -m "build(viewer): Vite + TypeScript + Three.js skeleton with Vitest, ESLint and Stryker"
```

---

### Task 8: CI workflows

**Files:**
- Create: `.github/workflows/ci.yml`, `.github/workflows/mutation-nightly.yml`
- Test: `tests/tools/test_ci_config.py`

**Interfaces:**
- Consumes: CLIs from Tasks 4–6 (`pericles_tools.traceability check|matrix`, `pericles_tools.adr check`, `pericles_tools.mutation_gate run [--changed-since]`) and the viewer scripts from Task 7.

- [ ] **Step 1: Write the failing test**

`tests/tools/test_ci_config.py`:

```python
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def run_commands(workflow: str) -> str:
    data: dict[str, Any] = yaml.safe_load((ROOT / workflow).read_text(encoding="utf-8"))
    commands = [
        step.get("run", "")
        for job in data["jobs"].values()
        for step in job["steps"]
    ]
    return "\n".join(commands)


@pytest.mark.req("REQ-NFR-005")
def test_ci_runs_every_quality_gate() -> None:
    """AC1: ruff, mypy --strict, pytest, traceability and viewer gates all run in CI."""
    commands = run_commands(".github/workflows/ci.yml")
    for gate in (
        "uv sync --locked",
        "ruff check",
        "ruff format --check",
        "mypy",
        "pytest",
        "pericles_tools.traceability check",
        "pericles_tools.adr check",
        "pnpm install --frozen-lockfile",
        "pnpm lint",
        "pnpm typecheck",
        "pnpm test",
        "pnpm build",
    ):
        assert gate in commands, gate


@pytest.mark.req("REQ-NFR-006")
def test_mutation_runs_incrementally_on_prs_and_fully_nightly() -> None:
    """AC2: changed modules on PRs; full run nightly (Python and viewer)."""
    assert "mutation_gate run --changed-since" in run_commands(".github/workflows/ci.yml")
    nightly = run_commands(".github/workflows/mutation-nightly.yml")
    assert "mutation_gate run\n" in nightly + "\n"
    assert "pnpm mutation" in nightly
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/tools/test_ci_config.py -q`
Expected: FAIL with `FileNotFoundError` for `.github/workflows/ci.yml`

- [ ] **Step 3: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

env:
  PYTHONPATH: tools

jobs:
  python:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python: ["3.12", "3.14"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python }}
      - name: Install
        run: uv sync --locked
      - name: Lint
        run: uv run ruff check . && uv run ruff format --check .
      - name: Type check
        run: uv run mypy
      - name: Tests
        run: uv run pytest
      - name: Traceability
        run: uv run python -m pericles_tools.traceability check
      - name: ADRs
        run: uv run python -m pericles_tools.adr check
      - name: Traceability matrix
        run: uv run python -m pericles_tools.traceability matrix
      - uses: actions/upload-artifact@v4
        if: matrix.python == '3.12'
        with:
          name: traceability-matrix
          path: docs/requirements/traceability.md

  mutation:
    if: github.event_name == 'pull_request'
    needs: python
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
      - uses: pnpm/action-setup@v4
        with:
          version: 11
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - name: Install
        run: uv sync --locked
      - name: Mutation testing (changed modules)
        run: uv run python -m pericles_tools.mutation_gate run --changed-since origin/${{ github.base_ref }}
      - name: Viewer mutation testing (if viewer changed)
        run: |
          if git diff --name-only origin/${{ github.base_ref }}...HEAD | grep -q '^viewer/src/'; then
            cd viewer && pnpm install --frozen-lockfile && pnpm mutation
          else
            echo "viewer unchanged; skipping Stryker"
          fi

  viewer:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: viewer
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 11
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: viewer/pnpm-lock.yaml
      - name: Install
        run: pnpm install --frozen-lockfile
      - name: Lint
        run: pnpm lint
      - name: Type check
        run: pnpm typecheck
      - name: Tests
        run: pnpm test
      - name: Build
        run: pnpm build
```

- [ ] **Step 4: Create `.github/workflows/mutation-nightly.yml`**

```yaml
name: Mutation (nightly)

on:
  schedule:
    - cron: "0 2 * * *"
  workflow_dispatch:

env:
  PYTHONPATH: tools

jobs:
  python:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.12"
      - name: Install
        run: uv sync --locked
      - name: Mutation testing (full)
        run: uv run python -m pericles_tools.mutation_gate run

  viewer:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: viewer
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 11
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: pnpm
          cache-dependency-path: viewer/pnpm-lock.yaml
      - name: Install
        run: pnpm install --frozen-lockfile
      - name: Mutation testing (full)
        run: pnpm mutation
```

- [ ] **Step 5: Run the test and the whole local gate suite**

Run: `uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 6: Commit, push the branch and open a draft PR to verify CI on GitHub**

```bash
git add .github tests/tools/test_ci_config.py
git commit -m "ci: quality gates, traceability, incremental and nightly mutation testing"
git push -u origin m0-foundations
gh pr create --draft --base main --title "M0 Foundations" --body "Implements docs/superpowers/plans/2026-11-22-m0-foundations.md"
gh pr checks --watch
```

Expected: all checks pass (`python (3.12)`, `python (3.14)`, `viewer`, `mutation`; the mutation gate prints `no functions to mutate yet` or `no mutation-tested modules changed`). If a check fails, read the log with `gh run view --log-failed`, fix, commit, push and watch again.

---

### Task 9: GitHub backlog sync from the requirements catalog

**Files:**
- Create: `tools/pericles_tools/backlog.py`
- Test: `tests/tools/test_backlog.py`

**Interfaces:**
- Consumes: `Requirement`, `load_catalog` (Task 2).
- Produces:
  - `MILESTONES: dict[str, str]` (`"M0" → "M0 Foundations"`, …)
  - `@dataclass(frozen=True) class IssueSpec: title: str; body: str; labels: tuple[str, ...]; milestone: str`
  - `issue_spec(req: Requirement) -> IssueSpec`
  - `label_commands(reqs: Iterable[Requirement]) -> list[list[str]]`
  - `plan_sync(reqs: Mapping[str, Requirement], existing_titles: Iterable[str], existing_milestones: Iterable[str]) -> list[list[str]]` (gh argument lists, in order: labels, milestones, issues)
  - `Gh = Callable[[Sequence[str]], str]`
  - `sync(gh: Gh, reqs: Mapping[str, Requirement], apply: bool) -> list[list[str]]`
  - `main(argv: Sequence[str] | None = None, gh: Gh = _gh) -> int` with flags `[--apply] [--root DIR]` (dry run by default)

One issue per non-withdrawn requirement. Title `REQ-SIM-001: Seeded map generation`. Labels `type:requirement`, `area:<area lowercase>`, `priority:<must|should|could>`. Milestone from the requirement. An issue already exists if any existing title starts with `<REQ-ID>:` (survives title edits and partial reruns).

- [ ] **Step 1: Write the failing tests**

`tests/tools/test_backlog.py`:

```python
from collections.abc import Sequence
from pathlib import Path

import pytest

from pericles_tools.backlog import (
    MILESTONES,
    issue_spec,
    label_commands,
    main,
    plan_sync,
    sync,
)
from pericles_tools.requirements import Requirement


def req(req_id: str, status: str = "Accepted", milestone: str = "M1") -> Requirement:
    return Requirement(
        id=req_id,
        title="Seeded map generation",
        priority="Must",
        milestone=milestone,
        status=status,
        statement="The engine generates a map.",
        criteria=(("AC1", "Same seed, same map."), ("AC2", "Different seeds differ.")),
        source=Path("docs/requirements/sim.md"),
        line=3,
    )


def test_issue_spec_contents() -> None:
    spec = issue_spec(req("REQ-SIM-001"))
    assert spec.title == "REQ-SIM-001: Seeded map generation"
    assert spec.labels == ("type:requirement", "area:sim", "priority:must")
    assert spec.milestone == "M1 Headless sim"
    assert "- [ ] AC1: Same seed, same map." in spec.body
    assert "docs/requirements/sim.md" in spec.body
    assert "The engine generates a map." in spec.body


def test_milestone_titles_cover_m0_to_m5() -> None:
    assert sorted(MILESTONES) == ["M0", "M1", "M2", "M3", "M4", "M5"]


def test_label_commands_are_idempotent_force_creates() -> None:
    commands = label_commands([req("REQ-SIM-001"), req("REQ-ECO-001")])
    names = [c[2] for c in commands]
    assert names == ["area:eco", "area:sim", "priority:must", "type:requirement"]
    assert all(c[:2] == ["label", "create"] and "--force" in c for c in commands)


def test_plan_creates_missing_milestones_and_issues_only() -> None:
    reqs = {r.id: r for r in [req("REQ-SIM-001"), req("REQ-SIM-002"), req("REQ-SIM-003", "Withdrawn")]}
    commands = plan_sync(
        reqs,
        existing_titles=["REQ-SIM-001: an older title"],
        existing_milestones=["M1 Headless sim"],
    )
    issue_cmds = [c for c in commands if c[:2] == ["issue", "create"]]
    milestone_cmds = [c for c in commands if c[0] == "api"]
    assert len(issue_cmds) == 1
    assert "REQ-SIM-002: Seeded map generation" in issue_cmds[0]
    assert milestone_cmds == []


def test_plan_creates_milestone_before_issues() -> None:
    commands = plan_sync({"REQ-SIM-001": req("REQ-SIM-001")}, [], [])
    kinds = [c[0] for c in commands if c[0] in ("api", "issue")]
    assert kinds == ["api", "issue"]
    assert "title=M1 Headless sim" in commands[[c[0] for c in commands].index("api")]


class FakeGh:
    def __init__(self) -> None:
        self.titles: list[str] = []
        self.milestones: list[str] = []
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["issue", "list"]:
            return "\n".join(self.titles)
        if args[0] == "api" and "--jq" in args:
            return "\n".join(self.milestones)
        if args[:2] == ["issue", "create"]:
            self.titles.append(args[args.index("--title") + 1])
        if args[0] == "api" and "-f" in args:
            self.milestones.append(args[args.index("-f") + 1].removeprefix("title="))
        return ""


def test_sync_is_idempotent() -> None:
    gh = FakeGh()
    reqs = {r.id: r for r in [req("REQ-SIM-001"), req("REQ-SIM-002", milestone="M2")]}
    first = sync(gh, reqs, apply=True)
    assert sum(c[:2] == ["issue", "create"] for c in first) == 2
    second = sync(gh, reqs, apply=True)
    assert not any(c[:2] == ["issue", "create"] or c[0] == "api" for c in second)


def test_dry_run_does_not_create(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    (tmp_path / "docs/requirements").mkdir(parents=True)
    (tmp_path / "docs/requirements/sim.md").write_text(
        "### REQ-SIM-001: X\nMust · M1 · Accepted\n- AC1: y\n", encoding="utf-8"
    )
    gh = FakeGh()
    assert main(["--root", str(tmp_path)], gh=gh) == 0
    assert not any(c[:2] in (["issue", "create"], ["label", "create"]) for c in gh.calls)
    assert "dry run" in capsys.readouterr().out
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/tools/test_backlog.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles_tools.backlog'`

- [ ] **Step 3: Implement `tools/pericles_tools/backlog.py`**

```python
"""Sync GitHub labels, milestones and one issue per requirement (dry run by default)."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pericles_tools.requirements import Requirement, load_catalog

MILESTONES: dict[str, str] = {
    "M0": "M0 Foundations",
    "M1": "M1 Headless sim",
    "M2": "M2 LLM minds",
    "M3": "M3 Society",
    "M4": "M4 Experiments",
    "M5": "M5 Viewer",
}
LABEL_COLORS = {"type": "5319e7", "area": "1d76db", "priority": "fbca04"}

Gh = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class IssueSpec:
    title: str
    body: str
    labels: tuple[str, ...]
    milestone: str


def _labels(req: Requirement) -> tuple[str, ...]:
    return ("type:requirement", f"area:{req.area.lower()}", f"priority:{req.priority.lower()}")


def issue_spec(req: Requirement) -> IssueSpec:
    criteria = "\n".join(f"- [ ] {ac}: {text}" for ac, text in req.criteria)
    statement = f"{req.statement}\n\n" if req.statement else ""
    body = (
        f"**Requirement:** {req.id}: {req.title}\n"
        f"**Priority:** {req.priority} · **Milestone:** {req.milestone} · "
        f"**Source:** `{req.source.as_posix()}`\n\n"
        f"{statement}### Acceptance criteria\n\n{criteria}\n\n"
        "Tests must reference this requirement with "
        f'`@pytest.mark.req("{req.id}")`.\n'
    )
    return IssueSpec(f"{req.id}: {req.title}", body, _labels(req), MILESTONES[req.milestone])


def label_commands(reqs: Iterable[Requirement]) -> list[list[str]]:
    names = sorted({label for req in reqs for label in _labels(req)})
    return [
        ["label", "create", name, "--color", LABEL_COLORS[name.split(":")[0]], "--force"]
        for name in names
    ]


def plan_sync(
    reqs: Mapping[str, Requirement],
    existing_titles: Iterable[str],
    existing_milestones: Iterable[str],
) -> list[list[str]]:
    active = [reqs[k] for k in sorted(reqs) if reqs[k].status != "Withdrawn"]
    existing_ids = {title.split(":", 1)[0].strip() for title in existing_titles}
    have_milestones = set(existing_milestones)
    commands = label_commands(active)
    for key in sorted({req.milestone for req in active}):
        title = MILESTONES[key]
        if title not in have_milestones:
            commands.append(["api", "repos/{owner}/{repo}/milestones", "-f", f"title={title}"])
    for req in active:
        if req.id in existing_ids:
            continue
        spec = issue_spec(req)
        command = ["issue", "create", "--title", spec.title, "--body", spec.body]
        for label in spec.labels:
            command += ["--label", label]
        commands.append([*command, "--milestone", spec.milestone])
    return commands


def sync(gh: Gh, reqs: Mapping[str, Requirement], apply: bool) -> list[list[str]]:
    titles = gh(["issue", "list", "--state", "all", "--limit", "1000", "--json", "title",
                 "--jq", ".[].title"]).splitlines()
    milestones = gh(["api", "repos/{owner}/{repo}/milestones?state=all", "--paginate",
                     "--jq", ".[].title"]).splitlines()
    commands = plan_sync(reqs, titles, milestones)
    if apply:
        for command in commands:
            gh(command)
    return commands


def _gh(args: Sequence[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def main(argv: Sequence[str] | None = None, gh: Gh = _gh) -> int:
    parser = argparse.ArgumentParser(prog="pericles_tools.backlog")
    parser.add_argument("--apply", action="store_true", help="create on GitHub (default: dry run)")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    reqs = load_catalog(args.root / "docs/requirements")
    commands = sync(gh, reqs, apply=args.apply)
    issues = sum(c[:2] == ["issue", "create"] for c in commands)
    milestones = sum(c[0] == "api" for c in commands)
    mode = "applied" if args.apply else "dry run"
    print(f"{mode}: {issues} issue(s), {milestones} milestone(s), labels refreshed")
    if not args.apply:
        for command in commands:
            if command[:2] == ["issue", "create"]:
                print(f"  would create: {command[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Note: `main` with the fake gh in the dry-run test still calls `issue list` and the milestones `api` query (both read-only), and never `create`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/tools/test_backlog.py -q && uv run mypy && uv run ruff check . && uv run ruff format --check .`
Expected: 7 passed; clean.

- [ ] **Step 5: Commit**

```bash
git add tools/pericles_tools/backlog.py tests/tools/test_backlog.py
git commit -m "feat(tools): GitHub backlog sync from the requirements catalog"
```

- [ ] **Step 6: Dry run against the real repository**

Run: `PYTHONPATH=tools uv run python -m pericles_tools.backlog`
Expected: `dry run: 89 issue(s), 6 milestone(s), labels refreshed` and 89 `would create:` lines.

- [ ] **Step 7: Create the backlog (outward-facing: confirm with the user first)**

Ask the user to confirm creating 89 issues, 6 milestones and the labels on `ettoreferranti/Pericles`. Only after an explicit yes:

Run: `PYTHONPATH=tools uv run python -m pericles_tools.backlog --apply`
Expected: `applied: 89 issue(s), 6 milestone(s), labels refreshed`. Re-running prints `applied: 0 issue(s), 0 milestone(s)`.

---

### Task 10: Developer guide and closing M0

**Files:**
- Create: `CLAUDE.md`
- Modify: `README.md` (add a Development section), `docs/requirements/milestones.md` (M0 → done), `docs/requirements/nfr.md` (M0 requirements → Implemented)

- [ ] **Step 1: Create `CLAUDE.md`**

````markdown
# Pericles — working agreements

Read first: `docs/superpowers/specs/2026-11-22-pericles-design.md`, `docs/requirements/README.md`, `docs/adr/README.md`.

## Commands

```bash
uv sync                                                   # install
uv run pytest                                             # tests (slow excluded; `-m slow` for Ollama contract tests)
uv run mypy && uv run ruff check . && uv run ruff format --check .
PYTHONPATH=tools uv run python -m pericles_tools.traceability check    # requirement ↔ test rules
PYTHONPATH=tools uv run python -m pericles_tools.traceability matrix   # writes docs/requirements/traceability.md
PYTHONPATH=tools uv run python -m pericles_tools.adr check
PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run [--changed-since origin/main]
PYTHONPATH=tools uv run python -m pericles_tools.backlog [--apply]     # GitHub issues from requirements
cd viewer && pnpm test && pnpm typecheck && pnpm lint && pnpm mutation
```

## Rules

- TDD: failing test first. Every test that verifies a requirement carries
  `@pytest.mark.req("REQ-…")` (literal IDs; `pytest.mark.req` spelled out) and names the AC in its docstring.
- Product tests live in `tests/pericles/` (these run under mutmut). Tooling tests live in `tests/tools/`.
- `pericles.core` never imports `agents`, `llm`, `experiment`, `server` or `analysis`. The engine is deterministic: no wall clock, no unseeded randomness.
- Significant design decisions get an ADR (`docs/adr/`, next number, add to the index). ADRs are amended or superseded, never deleted.
- Requirement changes follow `docs/requirements/README.md` → "Revising requirements". Mark a milestone done in `milestones.md` only when all its requirements have passing tests.
- Mutation thresholds: core ≥ 80%, agents/llm ≥ 70%, viewer ≥ 70%. Fix surviving mutants by adding tests. Never lower thresholds without an ADR.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
````

- [ ] **Step 2: Add a Development section to `README.md`**

Append:

````markdown
## Development

Requirements: macOS or Linux, Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/), Node ≥ 20 with pnpm, and [Ollama](https://ollama.com) for live runs.

```bash
uv sync && uv run pytest
cd viewer && pnpm install && pnpm dev
```

See [CLAUDE.md](CLAUDE.md) for all commands and working agreements.
````

- [ ] **Step 3: Mark M0 done and its requirements Implemented**

In `docs/requirements/milestones.md` change `| M0 | Foundations | no |` to `| M0 | Foundations | yes |`.
In `docs/requirements/nfr.md` change the status line of REQ-NFR-002, REQ-NFR-005, REQ-NFR-006, REQ-NFR-007 and REQ-NFR-008 from `Must · M0 · Accepted` to `Must · M0 · Implemented`.

- [ ] **Step 4: Run every gate**

Run:

```bash
uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check . \
  && PYTHONPATH=tools uv run python -m pericles_tools.traceability check \
  && PYTHONPATH=tools uv run python -m pericles_tools.adr check \
  && PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run \
  && (cd viewer && pnpm test && pnpm typecheck && pnpm lint && pnpm build)
```

Expected: everything passes. The traceability check prints `89 requirements, 5 covered, 84 open gaps` and exits 0. If it reports an M0 requirement without tests, add the missing test rather than reverting the status.

- [ ] **Step 5: Commit, push and mark the PR ready**

```bash
git add CLAUDE.md README.md docs/requirements/milestones.md docs/requirements/nfr.md
git commit -m "docs: developer guide; close milestone M0"
git push
gh pr checks --watch
gh pr ready
```

Expected: all checks green. Merging is the user's call (use superpowers:finishing-a-development-branch).
