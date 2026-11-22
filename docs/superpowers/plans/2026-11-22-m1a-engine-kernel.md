# M1a Engine Kernel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The deterministic foundation of the simulation. Data-driven content packs with validation, a modifier system, a calendar, seeded map generation, A* pathfinding, a tick engine with villager movement, an append-only event log in a run directory, and snapshots with crash-safe resume.

**Architecture:** `pericles.core` is a pure, deterministic engine. Content comes from YAML packs, validated by pydantic into an immutable `Registry`. The world state (`WorldState`) holds the map, villagers, active modifiers and the single seeded RNG. `Engine.step(state, intents)` resolves intents in a seeded canonical order, mutates the state in place and returns typed events. `pericles.experiment` owns persistence: `RunDirectory` (config, meta, `events.sqlite`, snapshots) and a `run` / `resume` loop.

**Tech Stack:** Python ≥ 3.12, pydantic 2, PyYAML, sqlite3 (stdlib), pytest, Hypothesis, mutmut.

**Spec:** `docs/superpowers/specs/2026-11-22-pericles-design.md` (§3.2, §4.1, §4.2, §7, §10). Requirements: `docs/requirements/sim.md` (REQ-SIM-001, -002, -003 AC1, -004 AC1–2, -005, -006) and `docs/requirements/exp.md` (REQ-EXP-003 AC2–3, AC1 except metrics).

**Follow-up:** M1b (gameplay) gets its own plan after this one is merged. It completes REQ-SIM-003 AC2, REQ-SIM-004 AC3, REQ-SIM-007…018, REQ-ECO-001, REQ-AGT-008, REQ-NFR-003.

## Global Constraints

- Work on branch `m1a-engine-kernel` (`git switch -c m1a-engine-kernel` before Task 1) and land it via a PR to `main`.
- `pericles.core` imports nothing from `pericles.agents`, `pericles.llm`, `pericles.experiment`, `pericles.server` or `pericles.analysis`, and never imports `time`, `datetime`, `uuid` or `secrets`. A test enforces this (Task 1).
- Determinism: all randomness in `core` comes from an explicitly seeded `random.Random`, either a local `random.Random(seed)` in map generation or `WorldState.rng` in the engine. No module-level `random.*` calls and no wall clock.
- `pericles.core` source contains no content IDs as string literals (REQ-SIM-005 AC4). A test enforces this (Task 3).
- Content models use pydantic with `extra="forbid"` and `frozen=True`. Content IDs match `^[a-z][a-z0-9_]*$`.
- Every test for a requirement carries `@pytest.mark.req("REQ-…")` (literal IDs) and names the AC in its docstring. Product tests live in `tests/pericles/`.
- Mutation score for `pericles.core` must be ≥ 80% (`PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run`). Each core task ends by mutating its own module and adding tests for survivors.
- Gates before every commit: `uv run ruff format .` first (the plan's code blocks are not pre-formatted), then `uv run pytest -q`, `uv run mypy`, `uv run ruff check .`, `uv run ruff format --check .`. Never pipe a gate into `tail`/`grep` in a way that hides its exit code.
- Engine movement semantics (Task 8) are binding: a `MoveTo` sets the path, and movement advances **in the same tick**. A villager on cost-1 terrain therefore moves one tile on the tick its intent is processed.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Content files with plausible mistakes**, such as a misspelt key (`duraton_ticks`), a string where a number belongs, a negative duration, or a top-level list instead of a mapping. These must fail with the file, the definition ID and the field path. They must never load with a default silently applied. Tests are in Task 2.
2. **Map parameters that cannot be honoured**, such as shares not summing to 1, a vein whose host terrain isn't a band, an unknown terrain ID, a non-walkable start terrain, a start radius larger than the map, or a 1×1 or non-square map. These must raise `ValueError` with the reason, or work by clipping the start area. They must never produce a half-assigned map (empty terrain strings) or crash with `IndexError`. Tests are in Task 6.
3. **An unreachable goal on a full-size map** (an island). A* must return `None` after exhausting the reachable region, not loop and not raise. Tests are in Task 7.
4. **A crash in the middle of a tick**, for example an exception from the intent source or a failing database write. The log must never contain a partial tick, and a resumed run must end with the same state digest and the same event-log digest as an uninterrupted run. Tests are in Tasks 9–10.
5. **Re-using a run directory by accident:** creating a run in a directory that already holds a run must fail, not overwrite or append. Tests are in Task 9.

---

## File Structure

```
pyproject.toml                                   # + pydantic, pyyaml runtime deps; pydantic mypy plugin
docs/adr/0013-engine-kernel-conventions.md       # + index row in docs/adr/README.md
src/pericles/core/geometry.py                    # Coord
src/pericles/core/canonical.py                   # canonical JSON + sha256 digest
src/pericles/core/content/__init__.py            # re-exports
src/pericles/core/content/schema.py              # pydantic models for pack files
src/pericles/core/content/loader.py              # load_pack, ContentError, Pack
src/pericles/core/content/registry.py            # Registry, build_registry, load_registry, base_pack_path
src/pericles/content/__init__.py                 # package marker for data
src/pericles/content/base/*.yaml                 # base content pack (terrain, items, nodes, needs, traits, actions)
src/pericles/core/modifiers.py                   # Modifier, Target, Scope, resolve, expire
src/pericles/core/calendar.py                    # Calendar, Season, GameTime
src/pericles/core/mapgen.py                      # MapParams, Band, Vein, TileMap, generate_map, start_area
src/pericles/core/pathfinding.py                 # CostField, TerrainCostField, find_path, path_cost
src/pericles/core/events.py                      # Event, EventSink
src/pericles/core/intents.py                     # Intent, MoveTo, Wait
src/pericles/core/state.py                       # Villager, WorldState
src/pericles/core/engine.py                      # Engine
src/pericles/experiment/eventlog.py              # EventLog (sqlite)
src/pericles/experiment/rundir.py                # RunDirectory, RunDirectoryError
src/pericles/experiment/runner.py                # run, resume, IntentSource
tests/pericles/conftest.py                       # registry, map_params, small_map fixtures
tests/pericles/test_*.py
```

---

### Task 1: Kernel conventions: dependencies, ADR, geometry, canonical digest, import boundaries

**Files:**
- Modify: `pyproject.toml`, `docs/adr/README.md`
- Create: `docs/adr/0013-engine-kernel-conventions.md`, `src/pericles/core/geometry.py`, `src/pericles/core/canonical.py`
- Test: `tests/pericles/test_geometry.py`, `tests/pericles/test_canonical.py`, `tests/pericles/test_core_boundaries.py`

**Interfaces:**
- Produces:
  - `class Coord(NamedTuple): x: int; y: int` with `neighbours4() -> tuple[Coord, Coord, Coord, Coord]` (order: up, right, down, left, i.e. (x,y-1), (x+1,y), (x,y+1), (x-1,y)) and `manhattan(other: Coord) -> int`
  - `canonical_json(value: object) -> str` (sorted keys, separators `(",", ":")`, `ensure_ascii=False`, `allow_nan=False`)
  - `digest(value: object) -> str` (hex sha256 of `canonical_json(value)` encoded as UTF-8)

- [ ] **Step 1: Add runtime dependencies and the pydantic mypy plugin**

In `pyproject.toml` set:

```toml
dependencies = [
    "pydantic>=2.9,<3",
    "pyyaml>=6.0",
]
```

Remove `"pyyaml>=6.0",` from the `dev` dependency group (keep `types-PyYAML`). In `[tool.mypy]` add `plugins = ["pydantic.mypy"]`. Run `uv sync`.

- [ ] **Step 2: Write ADR-0013**

`docs/adr/0013-engine-kernel-conventions.md`:

```markdown
# ADR-0013: Engine kernel conventions

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

The engine must be deterministic (REQ-SIM-002), fast enough for 1000 ticks/s with 150 scripted villagers (REQ-NFR-003), and driven by validated, data-driven content (ADR-0005). Spec §3.1 allowed only the stdlib and numpy in `core`. Content validation with precise error messages (REQ-SIM-005 AC1) is a large amount of hand-written code without a schema library.

## Decision

1. `pericles.core` may depend on **pydantic 2** (content schemas) and **PyYAML** (content files) in addition to the stdlib. numpy is not used until a measured need exists.
2. `Engine.step(state, intents)` **mutates `state` in place** and returns it together with the tick's events. Copying the world every tick is too slow. Determinism is guaranteed by construction: canonical intent order, then a shuffle with the state's RNG.
3. The world state owns **one seeded `random.Random`** (`WorldState.rng`, seeded from the string `"pericles-world-<seed>"`). Its full state is part of every snapshot. Map generation uses its own `random.Random(seed)`. Nothing in `core` uses module-level `random` functions, the wall clock, `uuid` or `secrets`.
4. State and event identity is defined by **canonical JSON** (sorted keys, compact separators, no NaN) hashed with SHA-256 (`digest`). Determinism tests compare digests.
5. An event's `tick` is the tick being processed. After `step`, `state.tick` is incremented, so a state with `tick == T` has processed ticks `0 … T-1`, and a snapshot at `T` pairs with log events `tick < T`.

## Consequences

+ Fast ticks; exact replay comparisons by digest; precise content errors almost for free.
− In-place mutation means a crashed `step` leaves an inconsistent in-memory state. Recovery is always via the last snapshot (REQ-EXP-003 AC3).
− pydantic becomes part of the core's public surface (content model types).
```

In `docs/superpowers/specs/2026-11-22-pericles-design.md`, change the `pericles.core` row's dependency cell from `nothing (stdlib + numpy)` to `nothing (stdlib + pydantic + PyYAML; ADR-0013)`.

Add to `docs/adr/README.md` after the 0012 row:

```markdown
| [0013](0013-engine-kernel-conventions.md) | Engine kernel conventions | Accepted |
```

- [ ] **Step 3: Write the failing tests**

`tests/pericles/test_geometry.py`:

```python
import pytest

from pericles.core.geometry import Coord

pytestmark = pytest.mark.req("REQ-SIM-004")


def test_neighbours4_order_is_up_right_down_left() -> None:
    """AC1 (support): neighbour order is fixed, which keeps A* deterministic."""
    assert Coord(5, 5).neighbours4() == (Coord(5, 4), Coord(6, 5), Coord(5, 6), Coord(4, 5))


def test_manhattan() -> None:
    assert Coord(1, 2).manhattan(Coord(4, -2)) == 7
    assert Coord(3, 3).manhattan(Coord(3, 3)) == 0
```

`tests/pericles/test_canonical.py`:

```python
import hashlib
import math

import pytest

from pericles.core.canonical import canonical_json, digest

pytestmark = pytest.mark.req("REQ-SIM-002")


def test_canonical_json_sorts_keys_and_is_compact() -> None:
    """AC1 (support): equal values serialise to identical bytes."""
    assert canonical_json({"b": 1, "a": [1, 2], "c": {"z": None, "y": True}}) == (
        '{"a":[1,2],"b":1,"c":{"y":true,"z":null}}'
    )


def test_canonical_json_keeps_unicode() -> None:
    assert canonical_json({"name": "Periklés"}) == '{"name":"Periklés"}'


def test_canonical_json_rejects_nan() -> None:
    with pytest.raises(ValueError):
        canonical_json({"x": math.nan})


def test_digest_is_sha256_of_canonical_utf8() -> None:
    value = {"b": "é", "a": 1}
    expected = hashlib.sha256('{"a":1,"b":"é"}'.encode()).hexdigest()
    assert digest(value) == expected
    assert digest({"a": 1, "b": "é"}) == expected
```

`tests/pericles/test_core_boundaries.py`:

```python
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
```

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/pericles/test_geometry.py tests/pericles/test_canonical.py tests/pericles/test_core_boundaries.py -q`
Expected: the geometry and canonical tests FAIL with `ModuleNotFoundError`; the boundary test passes (nothing to offend yet).

- [ ] **Step 5: Implement**

`src/pericles/core/geometry.py`:

```python
"""Grid coordinates."""

from __future__ import annotations

from typing import NamedTuple


class Coord(NamedTuple):
    x: int
    y: int

    def neighbours4(self) -> tuple[Coord, Coord, Coord, Coord]:
        """Up, right, down, left (fixed order keeps searches deterministic)."""
        x, y = self
        return (Coord(x, y - 1), Coord(x + 1, y), Coord(x, y + 1), Coord(x - 1, y))

    def manhattan(self, other: Coord) -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)
```

`src/pericles/core/canonical.py`:

```python
"""Canonical JSON and digests: the identity of states and events (ADR-0013)."""

from __future__ import annotations

import hashlib
import json


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


def digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
```

- [ ] **Step 6: Run the gates and the ADR check**

Run: `uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check . && PYTHONPATH=tools uv run python -m pericles_tools.adr check`
Expected: all pass; `ADRs OK`.

- [ ] **Step 7: Mutation-test the new modules**

Run: `rm -rf mutants && uv run mutmut run "pericles.core.geometry.*" "pericles.core.canonical.*" ; uv run mutmut results --all true`
Expected: every listed mutant `killed`. For any `survived` mutant, inspect it with `uv run mutmut show <name>`, add a test that kills it, and re-run.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock docs/adr docs/superpowers/specs src/pericles/core tests/pericles
git commit -m "feat(core): kernel conventions, Coord, canonical digest, import boundaries (ADR-0013)"
```

---

### Task 2: Content schema and pack loader

**Files:**
- Create: `src/pericles/core/content/__init__.py`, `src/pericles/core/content/schema.py`, `src/pericles/core/content/loader.py`
- Test: `tests/pericles/test_content_loader.py`

**Interfaces:**
- Produces (in `pericles.core.content.schema`): `Model` (pydantic base, `extra="forbid"`, `frozen=True`), `TargetDef`, `ModifierDef`, `TerrainDef`, `ItemDef`, `NodeDef`, `NeedDef`, `RequiresDef`, `LocationDef`, `ActionDef`, `RecipeDef`, `BuildingDef`, `TechDef`, `TraitDef`, `PackFile`, `SECTIONS: tuple[str, ...]`, `TARGET_SECTION: dict[str, str]`. Field names and types exactly as in Step 3.
- Produces (in `pericles.core.content.loader`): `class ContentError(Exception)`; `@dataclass(frozen=True) class Pack: name: str; path: Path; defs: Mapping[str, Mapping[str, Model]]` (section → id → definition); `load_pack(path: Path) -> Pack`.

A pack is a directory. Every `*.yaml` file in it (sorted by name) is a mapping whose keys are section names from `SECTIONS`. Each section is a list of definitions.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_content_loader.py`:

```python
from pathlib import Path

import pytest

from pericles.core.content.loader import ContentError, load_pack
from pericles.core.content.schema import ActionDef, TerrainDef

pytestmark = pytest.mark.req("REQ-SIM-005")

VALID = """
terrains:
  - {id: grass, walkable: true, move_cost: 1.0, color: "#8fb35a"}
  - {id: water, walkable: false, color: "#3b6ea5"}
items:
  - {id: wood, weight: 2.0}
actions:
  - id: fell
    duration_ticks: 60
    outputs: {wood: 2}
    skill: woodcutting
"""


def pack(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "mypack"
    root.mkdir()
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_loads_sections_from_all_yaml_files(tmp_path: Path) -> None:
    """AC1: a valid pack loads; definitions are typed and keyed by id."""
    loaded = load_pack(pack(tmp_path, {"a.yaml": VALID, "b.yaml": "items:\n  - {id: stone}\n"}))
    assert loaded.name == "mypack"
    assert sorted(loaded.defs["items"]) == ["stone", "wood"]
    grass = loaded.defs["terrains"]["grass"]
    assert isinstance(grass, TerrainDef) and grass.walkable is True
    fell = loaded.defs["actions"]["fell"]
    assert isinstance(fell, ActionDef)
    assert fell.outputs == {"wood": 2}
    assert fell.inputs == {}
    assert loaded.defs["recipes"] == {}


def test_defaults_are_applied(tmp_path: Path) -> None:
    loaded = load_pack(pack(tmp_path, {"a.yaml": VALID}))
    water = loaded.defs["terrains"]["water"]
    assert isinstance(water, TerrainDef) and water.move_cost == 1.0


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        (
            VALID.replace("duration_ticks: 60", "duraton_ticks: 60"),
            "actions[fell].duraton_ticks: Extra inputs are not permitted",
        ),
        (VALID.replace("duration_ticks: 60", "duration_ticks: -5"), "actions[fell].duration_ticks"),
        (VALID.replace("duration_ticks: 60", "duration_ticks: soon"), "actions[fell].duration_ticks"),
        (VALID.replace("weight: 2.0", "weight: -1"), "items[wood].weight"),
        (VALID.replace("id: fell", "id: Fell"), "actions[Fell].id"),
        (VALID.replace('"#8fb35a"', "green"), "terrains[grass].color"),
        (VALID.replace("outputs: {wood: 2}", "outputs: {wood: 0}"), "actions[fell].outputs.wood"),
        ("monsters:\n  - {id: x}\n", "monsters: Extra inputs are not permitted"),
    ],
    ids=["typo-key", "negative", "wrong-type", "negative-weight", "bad-id", "bad-color",
         "zero-count", "unknown-section"],
)
def test_invalid_definitions_name_file_definition_and_field(
    tmp_path: Path, text: str, fragment: str
) -> None:
    """AC1: invalid packs are rejected with file, path and problem."""
    root = pack(tmp_path, {"a.yaml": text})
    with pytest.raises(ContentError) as excinfo:
        load_pack(root)
    message = str(excinfo.value)
    assert str(root / "a.yaml") in message
    assert fragment in message


def test_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match=r"a\.yaml: invalid YAML"):
        load_pack(pack(tmp_path, {"a.yaml": "items: [\n"}))


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="top level must be a mapping"):
        load_pack(pack(tmp_path, {"a.yaml": "- id: wood\n"}))


def test_empty_file_is_allowed(tmp_path: Path) -> None:
    loaded = load_pack(pack(tmp_path, {"a.yaml": VALID, "empty.yaml": ""}))
    assert "wood" in loaded.defs["items"]


def test_duplicate_id_within_pack(tmp_path: Path) -> None:
    root = pack(tmp_path, {"a.yaml": VALID, "b.yaml": "items:\n  - {id: wood}\n"})
    with pytest.raises(ContentError, match=r"b\.yaml: items\[wood\]: duplicate id"):
        load_pack(root)


def test_pack_without_yaml_files(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="no .yaml files"):
        load_pack(pack(tmp_path, {"notes.txt": "x"}))


def test_pack_must_be_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="must be a directory"):
        load_pack(tmp_path / "missing")
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pericles/test_content_loader.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.core.content'`

- [ ] **Step 3: Implement the schema**

`src/pericles/core/content/__init__.py`:

```python
"""Data-driven content: schemas, pack loading and the registry (ADR-0005)."""
```

`src/pericles/core/content/schema.py`:

```python
"""Pydantic schemas for content pack files (REQ-SIM-005, ADR-0005, ADR-0013)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Count = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegative = Annotated[float, Field(ge=0)]
Bundle = dict[Id, Count]
TargetKind = Literal["action", "recipe", "building", "need", "item", "node"]

SECTIONS: tuple[str, ...] = (
    "terrains",
    "items",
    "nodes",
    "needs",
    "actions",
    "recipes",
    "buildings",
    "technologies",
    "traits",
)
TARGET_SECTION: dict[str, str] = {
    "action": "actions",
    "recipe": "recipes",
    "building": "buildings",
    "need": "needs",
    "item": "items",
    "node": "nodes",
}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TargetDef(Model):
    kind: TargetKind
    id: Id | None = None
    tag: Id | None = None


class ModifierDef(Model):
    target: TargetDef
    attribute: Id
    op: Literal["add", "mul", "set"]
    value: float


class TerrainDef(Model):
    id: Id
    walkable: bool
    move_cost: float = Field(default=1.0, gt=0)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class ItemDef(Model):
    id: Id
    weight: NonNegative = 1.0
    nutrition: NonNegative = 0.0
    tags: tuple[Id, ...] = ()
    durability: Count | None = None
    modifiers: tuple[ModifierDef, ...] = ()


class NodeDef(Model):
    id: Id
    yields: Id
    terrains: tuple[Id, ...] = Field(min_length=1)
    density: float = Field(gt=0, le=1)
    stock: Count
    regrowth_per_day: NonNegative = 0.0


class NeedDef(Model):
    id: Id
    rate_per_hour: NonNegative
    critical: float = Field(default=100.0, gt=0, le=100)


class RequiresDef(Model):
    tools: tuple[Id, ...] = ()
    skill: Id | None = None
    min_skill: NonNegative = 0.0
    knowledge: bool = False


class LocationDef(Model):
    node: Id | None = None
    building: Id | None = None
    terrains: tuple[Id, ...] = ()


class ActionDef(Model):
    id: Id
    duration_ticks: Count
    inputs: Bundle = Field(default_factory=dict)
    outputs: Bundle = Field(default_factory=dict)
    skill: Id | None = None
    requires: RequiresDef = RequiresDef()
    location: LocationDef = LocationDef()
    tags: tuple[Id, ...] = ()


class RecipeDef(Model):
    id: Id
    building: Id
    inputs: Bundle = Field(default_factory=dict)
    outputs: Bundle = Field(min_length=1)
    work_ticks: Count
    skill: Id | None = None


class BuildingDef(Model):
    id: Id
    cost: Bundle = Field(default_factory=dict)
    build_work: Count
    footprint: tuple[Count, Count] = (1, 1)
    workers: NonNegativeInt = 0
    housing: NonNegativeInt = 0
    storage: NonNegativeInt = 0
    entrance: bool = True
    tags: tuple[Id, ...] = ()


class TechDef(Model):
    id: Id
    building: Id
    cost: Bundle = Field(default_factory=dict)
    research_ticks: Count
    scope: Literal["villager", "village"] = "villager"
    unlocks_recipes: tuple[Id, ...] = ()
    unlocks_buildings: tuple[Id, ...] = ()
    modifiers: tuple[ModifierDef, ...] = ()


class TraitDef(Model):
    id: Id
    description: str = Field(min_length=1)
    modifiers: tuple[ModifierDef, ...] = ()


class PackFile(Model):
    terrains: tuple[TerrainDef, ...] = ()
    items: tuple[ItemDef, ...] = ()
    nodes: tuple[NodeDef, ...] = ()
    needs: tuple[NeedDef, ...] = ()
    actions: tuple[ActionDef, ...] = ()
    recipes: tuple[RecipeDef, ...] = ()
    buildings: tuple[BuildingDef, ...] = ()
    technologies: tuple[TechDef, ...] = ()
    traits: tuple[TraitDef, ...] = ()
```

- [ ] **Step 4: Implement the loader**

`src/pericles/core/content/loader.py`:

```python
"""Load and validate one content pack directory (REQ-SIM-005 AC1)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from pericles.core.content.schema import SECTIONS, Model, PackFile


class ContentError(Exception):
    """Content is invalid; the message names file, definition and field."""


@dataclass(frozen=True)
class Pack:
    name: str
    path: Path
    defs: Mapping[str, Mapping[str, Model]]


def load_pack(path: Path) -> Pack:
    if not path.is_dir():
        raise ContentError(f"{path}: content pack must be a directory")
    files = sorted(path.glob("*.yaml"))
    if not files:
        raise ContentError(f"{path}: content pack has no .yaml files")
    defs: dict[str, dict[str, Model]] = {section: {} for section in SECTIONS}
    for file in files:
        raw = _read_yaml(file)
        try:
            parsed = PackFile.model_validate(raw)
        except ValidationError as exc:
            raise ContentError(_describe(file, raw, exc)) from None
        for section in SECTIONS:
            for definition in getattr(parsed, section):
                if definition.id in defs[section]:
                    raise ContentError(
                        f"{file}: {section}[{definition.id}]: duplicate id within pack "
                        f"{path.name!r}"
                    )
                defs[section][definition.id] = definition
    return Pack(name=path.name, path=path, defs=defs)


def _read_yaml(file: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ContentError(f"{file}: invalid YAML: {exc}") from None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ContentError(
            f"{file}: top level must be a mapping of sections, got {type(raw).__name__}"
        )
    return raw


def _describe(file: Path, raw: dict[str, Any], exc: ValidationError) -> str:
    return "\n".join(
        f"{file}: {_location(raw, error['loc'])}: {error['msg']}" for error in exc.errors()
    )


def _location(raw: dict[str, Any], loc: Sequence[int | str]) -> str:
    """Render a pydantic location, replacing list indexes by definition ids."""
    parts: list[str] = []
    node: Any = raw
    for key in loc:
        if isinstance(key, int) and isinstance(node, list) and 0 <= key < len(node):
            item = node[key]
            ident = item.get("id") if isinstance(item, dict) else None
            label = f"[{ident}]" if isinstance(ident, str) else f"[{key}]"
            if parts:
                parts[-1] += label
            else:
                parts.append(label)
            node = item
        else:
            parts.append(str(key))
            node = node.get(key) if isinstance(node, dict) else None
    return ".".join(parts)
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/pericles/test_content_loader.py -q`
Expected: all pass (16 tests). If the `zero-count` case renders the key differently (pydantic reports dict value errors at `outputs.wood`), adjust only `_location`, never the expectation.

- [ ] **Step 6: Gates, mutation, commit**

Run: `uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check .`
Run: `rm -rf mutants && uv run mutmut run "pericles.core.content.*" ; uv run mutmut results --all true`
Expected: no `survived` mutants in `loader` (kill survivors with tests). Schema classes have no functions and produce no mutants.

```bash
git add src/pericles/core/content tests/pericles/test_content_loader.py
git commit -m "feat(core): content pack schema and validating loader"
```

---

### Task 3: Registry: layering, referential integrity, base pack, no hard-coded IDs

**Files:**
- Create: `src/pericles/core/content/registry.py`, `src/pericles/content/__init__.py`, `src/pericles/content/base/terrain.yaml`, `items.yaml`, `nodes.yaml`, `needs.yaml`, `traits.yaml`, `actions.yaml`, `tests/pericles/conftest.py`
- Test: `tests/pericles/test_registry.py`

**Interfaces:**
- Consumes: `Pack`, `load_pack`, `ContentError` (Task 2); schema classes, `SECTIONS`, `TARGET_SECTION` (Task 2).
- Produces:
  - `@dataclass(frozen=True) class Override: section: str; id: str; previous_pack: str; pack: str`
  - `@dataclass(frozen=True) class Registry` with fields `terrains: Mapping[str, TerrainDef]`, `items: Mapping[str, ItemDef]`, `nodes: Mapping[str, NodeDef]`, `needs: Mapping[str, NeedDef]`, `actions: Mapping[str, ActionDef]`, `recipes: Mapping[str, RecipeDef]`, `buildings: Mapping[str, BuildingDef]`, `technologies: Mapping[str, TechDef]`, `traits: Mapping[str, TraitDef]`, `packs: tuple[str, ...]`, `origins: Mapping[tuple[str, str], str]`, `overrides: tuple[Override, ...]`; methods `section(name: str) -> Mapping[str, Model]` and `all_ids() -> frozenset[str]`
  - `build_registry(packs: Sequence[Pack]) -> Registry`
  - `load_registry(paths: Sequence[Path]) -> Registry`
  - `base_pack_path() -> Path`
  - pytest fixture `registry` (session scope, base pack) in `tests/pericles/conftest.py`

- [ ] **Step 1: Write the base pack**

`src/pericles/content/__init__.py`:

```python
"""Content packs shipped with Pericles (data only)."""
```

`src/pericles/content/base/terrain.yaml`:

```yaml
terrains:
  - {id: water, walkable: false, color: "#3b6ea5"}
  - {id: fertile_soil, walkable: true, move_cost: 1.0, color: "#6b8f3e"}
  - {id: grass, walkable: true, move_cost: 1.0, color: "#8fb35a"}
  - {id: forest, walkable: true, move_cost: 2.0, color: "#2f5d2e"}
  - {id: rock, walkable: true, move_cost: 3.0, color: "#8a8178"}
  - {id: iron_vein, walkable: true, move_cost: 3.0, color: "#7a5a4a"}
  - {id: gold_vein, walkable: true, move_cost: 3.0, color: "#b8963e"}
```

`src/pericles/content/base/items.yaml`:

```yaml
items:
  - {id: berries, weight: 0.2, nutrition: 15, tags: [food]}
  - {id: grain, weight: 0.5, nutrition: 10, tags: [food]}
  - {id: meat, weight: 1.0, nutrition: 30, tags: [food]}
  - {id: fish, weight: 0.8, nutrition: 25, tags: [food]}
  - {id: wood, weight: 2.0, tags: [material]}
  - {id: stone, weight: 3.0, tags: [material]}
  - {id: iron_ore, weight: 3.0, tags: [ore]}
  - {id: gold_ore, weight: 3.0, tags: [ore]}
  - {id: hide, weight: 1.0, tags: [material]}
```

`src/pericles/content/base/nodes.yaml`:

```yaml
nodes:
  - {id: berry_bush, yields: berries, terrains: [grass, fertile_soil], density: 0.03, stock: 20, regrowth_per_day: 4}
  - {id: tree, yields: wood, terrains: [forest], density: 0.5, stock: 10, regrowth_per_day: 0.2}
  - {id: boulder, yields: stone, terrains: [rock], density: 0.3, stock: 30}
  - {id: iron_deposit, yields: iron_ore, terrains: [iron_vein], density: 0.6, stock: 50}
  - {id: gold_deposit, yields: gold_ore, terrains: [gold_vein], density: 0.6, stock: 25}
  - {id: fish_shoal, yields: fish, terrains: [water], density: 0.02, stock: 40, regrowth_per_day: 5}
  - {id: game, yields: meat, terrains: [forest, grass], density: 0.005, stock: 3, regrowth_per_day: 0.5}
```

`src/pericles/content/base/needs.yaml`:

```yaml
needs:
  - {id: hunger, rate_per_hour: 4.0, critical: 100}
  - {id: fatigue, rate_per_hour: 6.0, critical: 100}
  - {id: cold, rate_per_hour: 0.0, critical: 100}
```

`src/pericles/content/base/traits.yaml`:

```yaml
traits:
  - {id: greedy, description: "Wants to own more than others."}
  - {id: rebellious, description: "Distrusts rules and authority."}
  - {id: dutiful, description: "Feels bound by agreements and rules."}
  - {id: altruistic, description: "Puts others' needs before their own."}
  - {id: fearful, description: "Avoids risk and conflict."}
  - id: industrious
    description: "Works harder and faster than most."
    modifiers:
      - {target: {kind: action, tag: labour}, attribute: work_speed, op: mul, value: 1.1}
```

`src/pericles/content/base/actions.yaml`:

```yaml
actions:
  - {id: gather_berries, duration_ticks: 30, outputs: {berries: 3}, skill: foraging, location: {node: berry_bush}, tags: [labour]}
  - {id: fell_tree, duration_ticks: 60, outputs: {wood: 2}, skill: woodcutting, location: {node: tree}, tags: [labour]}
  - {id: quarry_stone, duration_ticks: 90, outputs: {stone: 2}, skill: masonry, location: {node: boulder}, tags: [labour]}
  - {id: mine_iron, duration_ticks: 120, outputs: {iron_ore: 1}, skill: mining, location: {node: iron_deposit}, tags: [labour]}
  - {id: mine_gold, duration_ticks: 150, outputs: {gold_ore: 1}, skill: mining, location: {node: gold_deposit}, tags: [labour]}
  - {id: catch_fish, duration_ticks: 60, outputs: {fish: 1}, skill: fishing, location: {node: fish_shoal}, tags: [labour]}
  - {id: hunt, duration_ticks: 120, outputs: {meat: 4, hide: 1}, skill: hunting, location: {node: game}, tags: [labour]}
```

`tests/pericles/conftest.py`:

```python
import pytest

from pericles.core.content.registry import Registry, base_pack_path, load_registry


@pytest.fixture(scope="session")
def registry() -> Registry:
    return load_registry([base_pack_path()])
```

- [ ] **Step 2: Write the failing tests**

`tests/pericles/test_registry.py`:

```python
import ast
import logging
from pathlib import Path

import pytest

import pericles.core
from pericles.core.content.loader import ContentError, load_pack
from pericles.core.content.registry import Registry, build_registry, load_registry

CORE = Path(pericles.core.__file__).parent

BASE = """
terrains:
  - {id: grass, walkable: true, color: "#8fb35a"}
items:
  - {id: wood, tags: [material]}
  - {id: axe, tags: [tool]}
nodes:
  - {id: tree, yields: wood, terrains: [grass], density: 0.5, stock: 10}
needs:
  - {id: hunger, rate_per_hour: 4}
actions:
  - {id: fell, duration_ticks: 60, outputs: {wood: 2}, location: {node: tree},
     requires: {tools: [tool]}, tags: [labour]}
buildings:
  - {id: hut, cost: {wood: 5}, build_work: 100, tags: [home]}
recipes:
  - {id: plank, building: hut, inputs: {wood: 1}, outputs: {wood: 1}, work_ticks: 10}
technologies:
  - {id: carpentry, building: hut, cost: {wood: 3}, research_ticks: 50,
     unlocks_recipes: [plank], unlocks_buildings: [hut]}
traits:
  - id: strong
    description: Strong.
    modifiers:
      - {target: {kind: action, tag: labour}, attribute: work_speed, op: mul, value: 1.2}
"""


def make_pack(tmp_path: Path, name: str, text: str) -> Path:
    root = tmp_path / name
    root.mkdir()
    (root / "content.yaml").write_text(text, encoding="utf-8")
    return root


@pytest.mark.req("REQ-SIM-005")
def test_base_pack_loads(registry: Registry) -> None:
    """AC1/AC2: the shipped base pack is valid and referentially complete."""
    assert registry.packs == ("base",)
    assert registry.terrains["water"].walkable is False
    assert registry.nodes["tree"].yields == "wood"
    assert {"hunger", "fatigue", "cold"} <= registry.needs.keys()
    assert {"greedy", "rebellious", "dutiful", "altruistic", "fearful"} <= registry.traits.keys()


@pytest.mark.req("REQ-SIM-005")
def test_valid_custom_pack(tmp_path: Path) -> None:
    """AC2: every kind of reference resolves."""
    registry = load_registry([make_pack(tmp_path, "p", BASE)])
    assert registry.technologies["carpentry"].unlocks_recipes == ("plank",)
    assert registry.section("items") is registry.items
    assert {"grass", "wood", "axe", "tree", "fell", "hut", "carpentry"} <= registry.all_ids()


@pytest.mark.req("REQ-SIM-005")
@pytest.mark.parametrize(
    ("old", "new", "fragment"),
    [
        ("yields: wood", "yields: plank_x", "nodes[tree].yields: unknown items id 'plank_x'"),
        ("terrains: [grass]", "terrains: [sand]", "nodes[tree].terrains: unknown terrains id 'sand'"),
        ("outputs: {wood: 2}", "outputs: {gold: 2}", "actions[fell].outputs: unknown items id 'gold'"),
        ("location: {node: tree}", "location: {node: bush}", "actions[fell].location.node"),
        ("tools: [tool]", "tools: [hammer]", "actions[fell].requires.tools: no items have tag 'hammer'"),
        ("cost: {wood: 5}", "cost: {clay: 5}", "buildings[hut].cost: unknown items id 'clay'"),
        ("building: hut, inputs", "building: mill, inputs", "recipes[plank].building"),
        ("unlocks_recipes: [plank]", "unlocks_recipes: [bread]", "technologies[carpentry].unlocks_recipes"),
        ("tag: labour}", "tag: magic}", "traits[strong].modifiers.target.tag: no actions have tag 'magic'"),
        ("{kind: action, tag: labour}", "{kind: need, id: thirst}", "traits[strong].modifiers.target.id"),
    ],
    ids=["node-yield", "node-terrain", "action-output", "action-node", "tool-tag",
         "building-cost", "recipe-building", "tech-unlock", "modifier-tag", "modifier-id"],
)
def test_dangling_references_are_rejected(tmp_path: Path, old: str, new: str, fragment: str) -> None:
    """AC2: dangling references are rejected, naming pack, definition and field."""
    assert old in BASE
    with pytest.raises(ContentError) as excinfo:
        load_registry([make_pack(tmp_path, "p", BASE.replace(old, new))])
    assert fragment in str(excinfo.value)
    assert str(excinfo.value).startswith("p: ")


@pytest.mark.req("REQ-SIM-005")
def test_all_problems_are_reported_together(tmp_path: Path) -> None:
    text = BASE.replace("yields: wood", "yields: x1").replace("cost: {wood: 5}", "cost: {x2: 5}")
    with pytest.raises(ContentError) as excinfo:
        load_registry([make_pack(tmp_path, "p", text)])
    assert "'x1'" in str(excinfo.value) and "'x2'" in str(excinfo.value)


@pytest.mark.req("REQ-SIM-005")
def test_layered_packs_override_and_log(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """AC3: later packs add or override ids; overrides are recorded and logged."""
    first = load_pack(make_pack(tmp_path, "base", BASE))
    extra = "items:\n  - {id: wood, weight: 9.0, tags: [material]}\n  - {id: clay}\n"
    second = load_pack(make_pack(tmp_path, "mod", extra))
    with caplog.at_level(logging.INFO, logger="pericles.core.content"):
        registry = build_registry([first, second])
    assert registry.items["wood"].weight == 9.0
    assert "clay" in registry.items
    assert registry.packs == ("base", "mod")
    assert registry.origins[("items", "wood")] == "mod"
    assert registry.origins[("items", "axe")] == "base"
    assert [(o.section, o.id, o.previous_pack, o.pack) for o in registry.overrides] == [
        ("items", "wood", "base", "mod")
    ]
    assert "items[wood]" in caplog.text and "'mod'" in caplog.text


@pytest.mark.req("REQ-SIM-005")
def test_at_least_one_pack_is_required() -> None:
    with pytest.raises(ContentError, match="at least one content pack"):
        build_registry([])


@pytest.mark.req("REQ-SIM-005")
def test_core_has_no_hard_coded_content_ids(registry: Registry) -> None:
    """AC4: the engine contains no hard-coded content ids."""
    ids = registry.all_ids()
    offenders = []
    for path in sorted(CORE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in ids:
                offenders.append(f"{path.relative_to(CORE)}:{node.lineno}: {node.value!r}")
    assert offenders == []
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/pericles/test_registry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.core.content.registry'` (raised from `conftest.py`).

- [ ] **Step 4: Implement `src/pericles/core/content/registry.py`**

```python
"""Merge content packs into an immutable, referentially checked registry (REQ-SIM-005)."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import cast

from pericles.core.content.loader import ContentError, Pack, load_pack
from pericles.core.content.schema import (
    SECTIONS,
    TARGET_SECTION,
    ActionDef,
    BuildingDef,
    ItemDef,
    Model,
    ModifierDef,
    NeedDef,
    NodeDef,
    RecipeDef,
    TechDef,
    TerrainDef,
    TraitDef,
)

logger = logging.getLogger("pericles.core.content")


@dataclass(frozen=True)
class Override:
    section: str
    id: str
    previous_pack: str
    pack: str


@dataclass(frozen=True)
class Registry:
    terrains: Mapping[str, TerrainDef]
    items: Mapping[str, ItemDef]
    nodes: Mapping[str, NodeDef]
    needs: Mapping[str, NeedDef]
    actions: Mapping[str, ActionDef]
    recipes: Mapping[str, RecipeDef]
    buildings: Mapping[str, BuildingDef]
    technologies: Mapping[str, TechDef]
    traits: Mapping[str, TraitDef]
    packs: tuple[str, ...]
    origins: Mapping[tuple[str, str], str]
    overrides: tuple[Override, ...]

    def section(self, name: str) -> Mapping[str, Model]:
        if name not in SECTIONS:
            raise KeyError(name)
        return cast(Mapping[str, Model], getattr(self, name))

    def all_ids(self) -> frozenset[str]:
        return frozenset(ident for name in SECTIONS for ident in self.section(name))


def base_pack_path() -> Path:
    return Path(str(files("pericles.content").joinpath("base")))


def load_registry(paths: Sequence[Path]) -> Registry:
    return build_registry([load_pack(path) for path in paths])


def build_registry(packs: Sequence[Pack]) -> Registry:
    if not packs:
        raise ContentError("at least one content pack is required")
    merged: dict[str, dict[str, Model]] = {section: {} for section in SECTIONS}
    origins: dict[tuple[str, str], str] = {}
    overrides: list[Override] = []
    for pack in packs:
        for section in SECTIONS:
            for ident, definition in pack.defs[section].items():
                if ident in merged[section]:
                    previous = origins[(section, ident)]
                    overrides.append(Override(section, ident, previous, pack.name))
                    logger.info(
                        "content override: %s[%s] from pack %r replaced by pack %r",
                        section,
                        ident,
                        previous,
                        pack.name,
                    )
                merged[section][ident] = definition
                origins[(section, ident)] = pack.name

    def view(section: str) -> Mapping[str, Model]:
        return MappingProxyType(merged[section])

    registry = Registry(
        terrains=cast(Mapping[str, TerrainDef], view("terrains")),
        items=cast(Mapping[str, ItemDef], view("items")),
        nodes=cast(Mapping[str, NodeDef], view("nodes")),
        needs=cast(Mapping[str, NeedDef], view("needs")),
        actions=cast(Mapping[str, ActionDef], view("actions")),
        recipes=cast(Mapping[str, RecipeDef], view("recipes")),
        buildings=cast(Mapping[str, BuildingDef], view("buildings")),
        technologies=cast(Mapping[str, TechDef], view("technologies")),
        traits=cast(Mapping[str, TraitDef], view("traits")),
        packs=tuple(pack.name for pack in packs),
        origins=MappingProxyType(origins),
        overrides=tuple(overrides),
    )
    problems = check_references(registry)
    if problems:
        raise ContentError("\n".join(problems))
    return registry


def check_references(registry: Registry) -> list[str]:
    problems: list[str] = []

    def where(section: str, ident: str, field: str) -> str:
        return f"{registry.origins[(section, ident)]}: {section}[{ident}].{field}"

    def refs(section: str, ident: str, field: str, target: str, values: Iterable[str]) -> None:
        known = registry.section(target)
        for value in values:
            if value not in known:
                problems.append(f"{where(section, ident, field)}: unknown {target} id {value!r}")

    def tags(section: str, ident: str, field: str, target: str, values: Iterable[str]) -> None:
        for value in values:
            if not any(value in getattr(d, "tags", ()) for d in registry.section(target).values()):
                problems.append(f"{where(section, ident, field)}: no {target} have tag {value!r}")

    def modifiers(section: str, ident: str, mods: Iterable[ModifierDef]) -> None:
        for mod in mods:
            target = TARGET_SECTION[mod.target.kind]
            if mod.target.id is not None:
                refs(section, ident, "modifiers.target.id", target, [mod.target.id])
            if mod.target.tag is not None:
                tags(section, ident, "modifiers.target.tag", target, [mod.target.tag])

    for ident, node in registry.nodes.items():
        refs("nodes", ident, "yields", "items", [node.yields])
        refs("nodes", ident, "terrains", "terrains", node.terrains)
    for ident, item in registry.items.items():
        modifiers("items", ident, item.modifiers)
    for ident, action in registry.actions.items():
        refs("actions", ident, "inputs", "items", action.inputs)
        refs("actions", ident, "outputs", "items", action.outputs)
        tags("actions", ident, "requires.tools", "items", action.requires.tools)
        if action.location.node is not None:
            refs("actions", ident, "location.node", "nodes", [action.location.node])
        if action.location.building is not None:
            refs("actions", ident, "location.building", "buildings", [action.location.building])
        refs("actions", ident, "location.terrains", "terrains", action.location.terrains)
    for ident, recipe in registry.recipes.items():
        refs("recipes", ident, "building", "buildings", [recipe.building])
        refs("recipes", ident, "inputs", "items", recipe.inputs)
        refs("recipes", ident, "outputs", "items", recipe.outputs)
    for ident, building in registry.buildings.items():
        refs("buildings", ident, "cost", "items", building.cost)
    for ident, tech in registry.technologies.items():
        refs("technologies", ident, "building", "buildings", [tech.building])
        refs("technologies", ident, "cost", "items", tech.cost)
        refs("technologies", ident, "unlocks_recipes", "recipes", tech.unlocks_recipes)
        refs("technologies", ident, "unlocks_buildings", "buildings", tech.unlocks_buildings)
        modifiers("technologies", ident, tech.modifiers)
    for ident, trait in registry.traits.items():
        modifiers("traits", ident, trait.modifiers)
    return problems
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass. If `base_pack_path()` fails because the YAML files are not packaged, check `src/pericles/content/base/` exists and `uv sync` re-installed the package. Hatch includes non-Python files inside `src/pericles` by default.

- [ ] **Step 6: Gates, mutation, commit**

Run the four gates. Then: `rm -rf mutants && uv run mutmut run "pericles.core.content.*" ; uv run mutmut results --all true`
Expected: no `survived` mutants in `registry`/`loader`. Kill survivors with tests in `test_registry.py`/`test_content_loader.py`. If mutmut cannot find the YAML base pack inside `mutants/`, add `also_copy = ["src/pericles/content"]` under `[tool.mutmut]`. Record that as a ruling.

```bash
git add src/pericles/core/content src/pericles/content tests/pericles
git commit -m "feat(core): content registry with layering, reference checks and base pack"
```

---

### Task 4: Modifier system

**Files:**
- Create: `src/pericles/core/modifiers.py`
- Test: `tests/pericles/test_modifiers.py`

**Interfaces:**
- Consumes: `ModifierDef` (Task 2).
- Produces:
  - `class Op(StrEnum): ADD = "add"; MUL = "mul"; SET = "set"`
  - `@dataclass(frozen=True) class Target: kind: str; id: str | None = None; tag: str | None = None`, with `matches(kind: str, ident: str, tags: Iterable[str] = ()) -> bool`
  - `@dataclass(frozen=True) class Scope: villager: str | None = None; building: str | None = None; until_tick: int | None = None`, with `applies(tick: int, villager: str | None, building: str | None) -> bool` and `active_at(tick: int) -> bool`
  - `@dataclass(frozen=True) class Modifier: target: Target; attribute: str; op: Op; value: float; source: str; scope: Scope = field(default_factory=Scope)`, with `to_dict() -> dict[str, Any]`, `from_dict(data: Mapping[str, Any]) -> Modifier` (classmethod) and `from_def(definition: ModifierDef, source: str, scope: Scope | None = None) -> Modifier` (classmethod)
  - `@dataclass(frozen=True) class Effective: attribute: str; base: float; value: float; contributions: tuple[Modifier, ...]`, with `explain() -> str`
  - `resolve(modifiers: Iterable[Modifier], *, kind: str, ident: str, attribute: str, base: float, tick: int, tags: Iterable[str] = (), villager: str | None = None, building: str | None = None) -> Effective`
  - `expire(modifiers: Iterable[Modifier], tick: int) -> tuple[Modifier, ...]`

Stacking (REQ-SIM-006 AC2): all matching `set` modifiers apply first in the given order (the last one wins), then all `add`, then all `mul`.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_modifiers.py`:

```python
import pytest

from pericles.core.content.schema import ModifierDef, TargetDef
from pericles.core.modifiers import Effective, Modifier, Op, Scope, Target, expire, resolve

pytestmark = pytest.mark.req("REQ-SIM-006")

def effective(
    mods: list[Modifier],
    tick: int = 0,
    base: float = 10.0,
    villager: str | None = None,
    building: str | None = None,
) -> Effective:
    return resolve(
        mods,
        kind="action",
        ident="fell_tree",
        tags=("labour",),
        attribute="work_speed",
        base=base,
        tick=tick,
        villager=villager,
        building=building,
    )


def value(
    mods: list[Modifier],
    tick: int = 0,
    villager: str | None = None,
    building: str | None = None,
) -> float:
    return effective(mods, tick=tick, villager=villager, building=building).value


def mod(op: Op, value: float, source: str = "s", attribute: str = "work_speed",
        target: Target | None = None, scope: Scope | None = None) -> Modifier:
    return Modifier(
        target=target or Target(kind="action", id="fell_tree"),
        attribute=attribute,
        op=op,
        value=value,
        source=source,
        scope=scope or Scope(),
    )


def test_no_modifiers_returns_base() -> None:
    result = effective([])
    assert (result.base, result.value, result.contributions) == (10.0, 10.0, ())


def test_stacking_order_is_set_then_add_then_mul() -> None:
    """AC2: deterministic stacking order regardless of list order."""
    mods = [mod(Op.MUL, 1.5, "tool"), mod(Op.ADD, 2, "skill"), mod(Op.SET, 4, "law")]
    assert value(mods) == pytest.approx((4 + 2) * 1.5)
    assert value(list(reversed(mods))) == pytest.approx((4 + 2) * 1.5)


def test_last_set_wins() -> None:
    assert value([mod(Op.SET, 4), mod(Op.SET, 7)]) == 7


def test_adds_and_muls_accumulate() -> None:
    assert value([mod(Op.ADD, 1), mod(Op.ADD, 2), mod(Op.MUL, 2), mod(Op.MUL, 3)]) == 78


@pytest.mark.parametrize(
    ("target", "matches"),
    [
        (Target(kind="action"), True),
        (Target(kind="action", id="fell_tree"), True),
        (Target(kind="action", id="quarry_stone"), False),
        (Target(kind="action", tag="labour"), True),
        (Target(kind="action", tag="leisure"), False),
        (Target(kind="action", id="fell_tree", tag="leisure"), False),
        (Target(kind="recipe", id="fell_tree"), False),
    ],
)
def test_selector_matching(target: Target, matches: bool) -> None:
    """AC1: modifiers apply to matching targets only."""
    assert (value([mod(Op.ADD, 5, target=target)]) == 15) is matches


def test_other_attribute_is_ignored() -> None:
    assert value([mod(Op.ADD, 5, attribute="yield")]) == 10


def test_villager_and_building_scopes() -> None:
    """AC4: scoped modifiers apply only within their scope."""
    mine = mod(Op.ADD, 5, scope=Scope(villager="ana"))
    assert value([mine], villager="ana") == 15
    assert value([mine], villager="bo") == 10
    assert value([mine]) == 10
    hut = mod(Op.ADD, 5, scope=Scope(building="b1"))
    assert value([hut], building="b1") == 15
    assert value([hut], building="b2") == 10


def test_time_limited_scope_applies_until_exclusive_tick() -> None:
    """AC4: time-limited modifiers expire."""
    drought = mod(Op.MUL, 0.5, scope=Scope(until_tick=100))
    assert value([drought], tick=99) == 5
    assert value([drought], tick=100) == 10
    assert expire([drought, mod(Op.ADD, 1)], tick=99) == (drought, mod(Op.ADD, 1))
    assert expire([drought, mod(Op.ADD, 1)], tick=100) == (mod(Op.ADD, 1),)


def test_explain_lists_base_and_sources_in_application_order() -> None:
    """AC3: every effective value is explainable."""
    mods = [mod(Op.MUL, 1.5, "axe"), mod(Op.ADD, 2, "skill:woodcutting")]
    result = effective(mods)
    assert [m.source for m in result.contributions] == ["skill:woodcutting", "axe"]
    assert result.explain() == "work_speed base 10 → +2 (skill:woodcutting) → ×1.5 (axe) = 18"


def test_explain_without_modifiers() -> None:
    assert effective([], base=3.0).explain() == "work_speed base 3 = 3"


def test_explain_set() -> None:
    assert effective([mod(Op.SET, 4, "law")], base=3.0).explain() == (
        "work_speed base 3 → =4 (law) = 4"
    )


def test_from_def_and_round_trip() -> None:
    definition = ModifierDef(
        target=TargetDef(kind="action", tag="labour"), attribute="work_speed", op="mul", value=1.1
    )
    modifier = Modifier.from_def(definition, source="trait:industrious", scope=Scope(villager="a"))
    assert modifier.op is Op.MUL
    assert modifier.target == Target(kind="action", tag="labour")
    assert Modifier.from_dict(modifier.to_dict()) == modifier
    assert modifier.to_dict() == {
        "target": {"kind": "action", "id": None, "tag": "labour"},
        "attribute": "work_speed",
        "op": "mul",
        "value": 1.1,
        "source": "trait:industrious",
        "scope": {"villager": "a", "building": None, "until_tick": None},
    }
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pericles/test_modifiers.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.core.modifiers'`

- [ ] **Step 3: Implement `src/pericles/core/modifiers.py`**

```python
"""Modifiers: the single mechanism through which effects alter the world (REQ-SIM-006)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pericles.core.content.schema import ModifierDef


class Op(StrEnum):
    ADD = "add"
    MUL = "mul"
    SET = "set"


ORDER = (Op.SET, Op.ADD, Op.MUL)
SYMBOL = {Op.SET: "=", Op.ADD: "+", Op.MUL: "×"}


@dataclass(frozen=True)
class Target:
    kind: str
    id: str | None = None
    tag: str | None = None

    def matches(self, kind: str, ident: str, tags: Iterable[str] = ()) -> bool:
        return (
            self.kind == kind
            and (self.id is None or self.id == ident)
            and (self.tag is None or self.tag in tuple(tags))
        )


@dataclass(frozen=True)
class Scope:
    villager: str | None = None
    building: str | None = None
    until_tick: int | None = None

    def active_at(self, tick: int) -> bool:
        return self.until_tick is None or tick < self.until_tick

    def applies(self, tick: int, villager: str | None, building: str | None) -> bool:
        return (
            self.active_at(tick)
            and (self.villager is None or self.villager == villager)
            and (self.building is None or self.building == building)
        )


@dataclass(frozen=True)
class Modifier:
    target: Target
    attribute: str
    op: Op
    value: float
    source: str
    scope: Scope = field(default_factory=Scope)

    @classmethod
    def from_def(cls, definition: ModifierDef, source: str, scope: Scope | None = None) -> Modifier:
        return cls(
            target=Target(definition.target.kind, definition.target.id, definition.target.tag),
            attribute=definition.attribute,
            op=Op(definition.op),
            value=definition.value,
            source=source,
            scope=scope if scope is not None else Scope(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": {"kind": self.target.kind, "id": self.target.id, "tag": self.target.tag},
            "attribute": self.attribute,
            "op": self.op.value,
            "value": self.value,
            "source": self.source,
            "scope": {
                "villager": self.scope.villager,
                "building": self.scope.building,
                "until_tick": self.scope.until_tick,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Modifier:
        target, scope = data["target"], data["scope"]
        return cls(
            target=Target(target["kind"], target["id"], target["tag"]),
            attribute=data["attribute"],
            op=Op(data["op"]),
            value=float(data["value"]),
            source=data["source"],
            scope=Scope(scope["villager"], scope["building"], scope["until_tick"]),
        )


def _fmt(number: float) -> str:
    return f"{number:g}"


@dataclass(frozen=True)
class Effective:
    attribute: str
    base: float
    value: float
    contributions: tuple[Modifier, ...]

    def explain(self) -> str:
        steps = "".join(
            f" → {SYMBOL[m.op]}{_fmt(m.value)} ({m.source})" for m in self.contributions
        )
        return f"{self.attribute} base {_fmt(self.base)}{steps} = {_fmt(self.value)}"


def resolve(
    modifiers: Iterable[Modifier],
    *,
    kind: str,
    ident: str,
    attribute: str,
    base: float,
    tick: int,
    tags: Iterable[str] = (),
    villager: str | None = None,
    building: str | None = None,
) -> Effective:
    tag_tuple = tuple(tags)
    active = [
        m
        for m in modifiers
        if m.attribute == attribute
        and m.target.matches(kind, ident, tag_tuple)
        and m.scope.applies(tick, villager, building)
    ]
    ordered = tuple(m for op in ORDER for m in active if m.op is op)
    value = base
    for m in ordered:
        if m.op is Op.SET:
            value = m.value
        elif m.op is Op.ADD:
            value += m.value
        else:
            value *= m.value
    return Effective(attribute=attribute, base=base, value=value, contributions=ordered)


def expire(modifiers: Iterable[Modifier], tick: int) -> tuple[Modifier, ...]:
    return tuple(m for m in modifiers if m.scope.active_at(tick))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/pericles/test_modifiers.py -q`
Expected: all pass.

- [ ] **Step 5: Gates, mutation, commit**

Run the four gates; then `rm -rf mutants && uv run mutmut run "pericles.core.modifiers.*" ; uv run mutmut results --all true`. Kill all survivors with tests (≥ 80% required, aim for 100%).

```bash
git add src/pericles/core/modifiers.py tests/pericles/test_modifiers.py
git commit -m "feat(core): modifier system with deterministic stacking, scopes and explanations"
```

---

### Task 5: Calendar (time of day and seasons)

**Files:**
- Create: `src/pericles/core/calendar.py`
- Test: `tests/pericles/test_calendar.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Season: name: str; days: int`
  - `@dataclass(frozen=True) class GameTime: tick: int; day: int; minute_of_day: int; year: int; season: str; day_of_season: int; is_daytime: bool`
  - `@dataclass(frozen=True) class Calendar: seasons: tuple[Season, ...]; tick_minutes: int = 1; day_minutes: int = 1440; sunrise_minute: int = 360; sunset_minute: int = 1200`, with properties `ticks_per_day: int` and `days_per_year: int`, and method `time_of(tick: int) -> GameTime`. Validation errors raise `ValueError`.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_calendar.py`:

```python
import pytest

from pericles.core.calendar import Calendar, GameTime, Season

SEASONS = (Season("spring", 2), Season("summer", 2), Season("autumn", 1), Season("winter", 3))


@pytest.mark.req("REQ-SIM-002")
def test_each_tick_advances_time_by_tick_minutes() -> None:
    """AC3: one tick = tick_minutes of in-game time."""
    calendar = Calendar(seasons=SEASONS, tick_minutes=10)
    assert calendar.ticks_per_day == 144
    assert calendar.time_of(1).minute_of_day == 10
    assert calendar.time_of(7).minute_of_day == 70
    assert calendar.time_of(144) == GameTime(
        tick=144, day=1, minute_of_day=0, year=0, season="spring", day_of_season=1, is_daytime=False
    )


@pytest.mark.req("REQ-SIM-003")
@pytest.mark.parametrize(
    ("day", "season", "day_of_season", "year"),
    [(0, "spring", 0, 0), (1, "spring", 1, 0), (2, "summer", 0, 0), (4, "autumn", 0, 0),
     (5, "winter", 0, 0), (7, "winter", 2, 0), (8, "spring", 0, 1), (13, "winter", 0, 1)],
)
def test_seasons_cycle(day: int, season: str, day_of_season: int, year: int) -> None:
    """AC1: the season can be derived from the tick."""
    calendar = Calendar(seasons=SEASONS)
    time = calendar.time_of(day * calendar.ticks_per_day + 5)
    assert (time.day, time.season, time.day_of_season, time.year) == (
        day, season, day_of_season, year
    )
    assert calendar.days_per_year == 8


@pytest.mark.req("REQ-SIM-003")
@pytest.mark.parametrize(
    ("minute", "daytime"), [(0, False), (359, False), (360, True), (1199, True), (1200, False)]
)
def test_day_and_night(minute: int, daytime: bool) -> None:
    """AC1: day length is a parameter and time of day is derivable."""
    assert Calendar(seasons=SEASONS).time_of(minute).is_daytime is daytime


@pytest.mark.req("REQ-SIM-003")
def test_custom_day_length() -> None:
    calendar = Calendar(seasons=SEASONS, tick_minutes=5, day_minutes=100, sunrise_minute=20,
                        sunset_minute=80)
    assert calendar.ticks_per_day == 20
    assert calendar.time_of(21).day == 1
    assert calendar.time_of(21).minute_of_day == 5


@pytest.mark.req("REQ-SIM-003")
@pytest.mark.parametrize(
    "kwargs",
    [
        {"seasons": ()},
        {"seasons": (Season("x", 0),)},
        {"seasons": SEASONS, "tick_minutes": 0},
        {"seasons": SEASONS, "tick_minutes": 7},
        {"seasons": SEASONS, "sunrise_minute": 1300},
        {"seasons": SEASONS, "sunrise_minute": -1},
        {"seasons": SEASONS, "sunset_minute": 1441},
    ],
)
def test_invalid_calendars_are_rejected(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        Calendar(**kwargs)  # type: ignore[arg-type]


@pytest.mark.req("REQ-SIM-003")
def test_negative_tick_is_rejected() -> None:
    with pytest.raises(ValueError):
        Calendar(seasons=SEASONS).time_of(-1)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pericles/test_calendar.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.core.calendar'`

- [ ] **Step 3: Implement `src/pericles/core/calendar.py`**

```python
"""In-game time: ticks, days, day/night and seasons (REQ-SIM-002 AC3, REQ-SIM-003 AC1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Season:
    name: str
    days: int


@dataclass(frozen=True)
class GameTime:
    tick: int
    day: int
    minute_of_day: int
    year: int
    season: str
    day_of_season: int
    is_daytime: bool


@dataclass(frozen=True)
class Calendar:
    seasons: tuple[Season, ...]
    tick_minutes: int = 1
    day_minutes: int = 1440
    sunrise_minute: int = 360
    sunset_minute: int = 1200

    def __post_init__(self) -> None:
        if not self.seasons:
            raise ValueError("calendar needs at least one season")
        if any(season.days <= 0 for season in self.seasons):
            raise ValueError("every season must last at least one day")
        if self.tick_minutes <= 0 or self.day_minutes % self.tick_minutes != 0:
            raise ValueError("tick_minutes must be positive and divide day_minutes")
        if not 0 <= self.sunrise_minute < self.sunset_minute <= self.day_minutes:
            raise ValueError("need 0 <= sunrise_minute < sunset_minute <= day_minutes")

    @property
    def ticks_per_day(self) -> int:
        return self.day_minutes // self.tick_minutes

    @property
    def days_per_year(self) -> int:
        return sum(season.days for season in self.seasons)

    def time_of(self, tick: int) -> GameTime:
        if tick < 0:
            raise ValueError("tick must be non-negative")
        day, minute = divmod(tick * self.tick_minutes, self.day_minutes)
        year, day_of_year = divmod(day, self.days_per_year)
        season, day_of_season = self.seasons[-1], 0
        for candidate in self.seasons:
            if day_of_year < candidate.days:
                season, day_of_season = candidate, day_of_year
                break
            day_of_year -= candidate.days
        return GameTime(
            tick=tick,
            day=day,
            minute_of_day=minute,
            year=year,
            season=season.name,
            day_of_season=day_of_season,
            is_daytime=self.sunrise_minute <= minute < self.sunset_minute,
        )
```

- [ ] **Step 4: Run the tests, gates, mutation, commit**

Run: `uv run pytest tests/pericles/test_calendar.py -q` → all pass. Run the four gates. Run `rm -rf mutants && uv run mutmut run "pericles.core.calendar.*" ; uv run mutmut results --all true` and kill survivors.

```bash
git add src/pericles/core/calendar.py tests/pericles/test_calendar.py
git commit -m "feat(core): calendar with ticks, day/night and seasons"
```

---

### Task 6: Seeded map generation

**Files:**
- Create: `src/pericles/core/mapgen.py`
- Modify: `tests/pericles/conftest.py` (add `map_params` fixture)
- Test: `tests/pericles/test_mapgen.py`

**Interfaces:**
- Consumes: `Registry` (Task 3), `Coord` (Task 1), `digest` (Task 1).
- Produces:
  - `@dataclass(frozen=True) class Band: terrain: str; share: float`
  - `@dataclass(frozen=True) class Vein: terrain: str; share: float; host: str`
  - `@dataclass(frozen=True) class MapParams: width: int; height: int; bands: tuple[Band, ...]; start_terrain: str; veins: tuple[Vein, ...] = (); start_radius: int = 8; feature_size: int = 16; octaves: int = 3`
  - `class TileMap` with `__init__(width: int, height: int, terrain: list[str], elevation: list[float])`, attributes `width`, `height`, `terrain`, `elevation`, and methods `in_bounds(c: Coord) -> bool`, `terrain_at(c: Coord) -> str`, `counts() -> dict[str, int]`, `start() -> Coord` (the centre `(width // 2, height // 2)`), `to_dict() -> dict[str, Any]`, `from_dict(data) -> TileMap` (classmethod), `digest() -> str`
  - `start_area(width: int, height: int, radius: int) -> list[Coord]` (tiles within Euclidean `radius` of the centre, clipped to the map, row-major order)
  - `generate_map(seed: int, params: MapParams, registry: Registry) -> TileMap`

Algorithm:
1. Build an elevation field with seeded multi-octave value noise.
2. Rank the tiles by `(elevation, index)` and assign the bands in order by exact share (low elevation first, so water first).
3. For each vein, rank its host tiles by a separate noise field and convert the top `round(share * n)` tiles.
4. Convert every non-walkable tile in the start area to `start_terrain`.

- [ ] **Step 1: Add the fixture**

Append to `tests/pericles/conftest.py`:

```python
from pericles.core.mapgen import Band, MapParams, Vein


@pytest.fixture
def map_params() -> MapParams:
    return MapParams(
        width=64,
        height=64,
        bands=(
            Band("water", 0.12),
            Band("fertile_soil", 0.18),
            Band("grass", 0.35),
            Band("forest", 0.25),
            Band("rock", 0.10),
        ),
        veins=(Vein("iron_vein", 0.02, "rock"), Vein("gold_vein", 0.005, "rock")),
        start_terrain="grass",
        start_radius=6,
    )
```

(Move the new `import` to the top of the file next to the existing imports.)

- [ ] **Step 2: Write the failing tests**

`tests/pericles/test_mapgen.py`:

```python
from collections import deque
from dataclasses import replace

import pytest

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import Band, MapParams, TileMap, Vein, generate_map, start_area

pytestmark = pytest.mark.req("REQ-SIM-001")


def test_same_seed_same_map(registry: Registry, map_params: MapParams) -> None:
    """AC1: same seed and parameters produce an identical map."""
    a = generate_map(7, map_params, registry)
    b = generate_map(7, map_params, registry)
    assert a.digest() == b.digest()
    assert a.terrain == b.terrain


def test_different_seeds_differ(registry: Registry, map_params: MapParams) -> None:
    """AC2."""
    digests = {generate_map(seed, map_params, registry).digest() for seed in range(5)}
    assert len(digests) == 5


def test_full_size_proportions_within_five_points(registry: Registry, map_params: MapParams) -> None:
    """AC3: every requested terrain is present, within ±5 percentage points."""
    params = replace(map_params, width=128, height=128, start_radius=10)
    tilemap = generate_map(3, params, registry)
    counts = tilemap.counts()
    n = 128 * 128
    expected = {band.terrain: band.share for band in params.bands}
    for vein in params.veins:
        expected[vein.terrain] = vein.share
        expected[vein.host] -= vein.share
    assert set(counts) == set(expected)
    for terrain, share in expected.items():
        assert counts[terrain] > 0
        assert abs(counts[terrain] / n - share) <= 0.05, terrain


def test_every_tile_is_assigned(registry: Registry, map_params: MapParams) -> None:
    tilemap = generate_map(1, map_params, registry)
    assert len(tilemap.terrain) == 64 * 64
    assert all(t in registry.terrains for t in tilemap.terrain)
    assert len(tilemap.elevation) == 64 * 64
    assert all(0.0 <= e <= 1.0 for e in tilemap.elevation)


@pytest.mark.parametrize("seed", range(10))
def test_start_area_is_walkable_and_connected(
    registry: Registry, map_params: MapParams, seed: int
) -> None:
    """AC4: all walkable tiles of the starting area are mutually reachable."""
    tilemap = generate_map(seed, map_params, registry)
    area = set(start_area(64, 64, map_params.start_radius))
    assert all(registry.terrains[tilemap.terrain_at(c)].walkable for c in area)
    seen = {tilemap.start()}
    queue = deque([tilemap.start()])
    while queue:
        for nb in queue.popleft().neighbours4():
            if nb in area and nb not in seen:
                seen.add(nb)
                queue.append(nb)
    assert seen == area


def test_start_area_shape_and_clipping() -> None:
    area = start_area(5, 5, 1)
    assert area == [Coord(2, 1), Coord(1, 2), Coord(2, 2), Coord(3, 2), Coord(2, 3)]
    assert len(start_area(3, 3, 10)) == 9
    assert start_area(1, 1, 0) == [Coord(0, 0)]


def test_tiny_and_non_square_maps(registry: Registry, map_params: MapParams) -> None:
    for width, height in [(1, 1), (2, 9), (17, 5)]:
        params = replace(map_params, width=width, height=height, start_radius=50)
        tilemap = generate_map(0, params, registry)
        assert len(tilemap.terrain) == width * height
        assert all(registry.terrains[t].walkable for t in tilemap.terrain)


def test_tilemap_accessors_and_round_trip(registry: Registry, map_params: MapParams) -> None:
    tilemap = generate_map(5, map_params, registry)
    assert tilemap.in_bounds(Coord(0, 0)) and tilemap.in_bounds(Coord(63, 63))
    assert not tilemap.in_bounds(Coord(64, 0)) and not tilemap.in_bounds(Coord(0, -1))
    assert tilemap.terrain_at(Coord(3, 2)) == tilemap.terrain[2 * 64 + 3]
    assert tilemap.start() == Coord(32, 32)
    clone = TileMap.from_dict(tilemap.to_dict())
    assert clone.digest() == tilemap.digest()
    assert clone.terrain == tilemap.terrain and clone.elevation == tilemap.elevation


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"bands": (Band("grass", 0.5), Band("water", 0.4))}, "sum to 1"),
        ({"bands": (Band("grass", 1.2), Band("water", -0.2))}, "non-negative"),
        ({"bands": ()}, "at least one band"),
        ({"bands": (Band("lava", 1.0),)}, "unknown terrain 'lava'"),
        ({"veins": (Vein("iron_vein", 0.01, "desert"),)}, "host 'desert' is not a band"),
        ({"veins": (Vein("iron_vein", 0.5, "rock"),)}, "more than their host"),
        ({"start_terrain": "water"}, "start_terrain 'water' is not walkable"),
        ({"width": 0}, "width and height"),
        ({"start_radius": -1}, "start_radius"),
        ({"feature_size": 0}, "feature_size"),
        ({"octaves": 0}, "octaves"),
    ],
)
def test_invalid_parameters_are_rejected(
    registry: Registry, map_params: MapParams, change: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        generate_map(0, replace(map_params, **change), registry)  # type: ignore[arg-type]
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/pericles/test_mapgen.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.core.mapgen'` (from conftest).

- [ ] **Step 4: Implement `src/pericles/core/mapgen.py`**

```python
"""Seeded procedural tile maps (REQ-SIM-001)."""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pericles.core.canonical import digest
from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord


@dataclass(frozen=True)
class Band:
    terrain: str
    share: float


@dataclass(frozen=True)
class Vein:
    terrain: str
    share: float
    host: str


@dataclass(frozen=True)
class MapParams:
    width: int
    height: int
    bands: tuple[Band, ...]
    start_terrain: str
    veins: tuple[Vein, ...] = ()
    start_radius: int = 8
    feature_size: int = 16
    octaves: int = 3


class TileMap:
    def __init__(self, width: int, height: int, terrain: list[str], elevation: list[float]):
        if len(terrain) != width * height or len(elevation) != width * height:
            raise ValueError("terrain and elevation must have width * height entries")
        self.width = width
        self.height = height
        self.terrain = terrain
        self.elevation = elevation

    def in_bounds(self, c: Coord) -> bool:
        return 0 <= c.x < self.width and 0 <= c.y < self.height

    def terrain_at(self, c: Coord) -> str:
        if not self.in_bounds(c):
            raise IndexError(f"{c} is outside a {self.width}x{self.height} map")
        return self.terrain[c.y * self.width + c.x]

    def counts(self) -> dict[str, int]:
        return dict(Counter(self.terrain))

    def start(self) -> Coord:
        return Coord(self.width // 2, self.height // 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "terrain": list(self.terrain),
            "elevation": list(self.elevation),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TileMap:
        return cls(
            int(data["width"]),
            int(data["height"]),
            [str(t) for t in data["terrain"]],
            [float(e) for e in data["elevation"]],
        )

    def digest(self) -> str:
        return digest(self.to_dict())


def start_area(width: int, height: int, radius: int) -> list[Coord]:
    cx, cy = width // 2, height // 2
    return [
        Coord(x, y)
        for y in range(max(0, cy - radius), min(height, cy + radius + 1))
        for x in range(max(0, cx - radius), min(width, cx + radius + 1))
        if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius
    ]


def _smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def value_noise(
    rng: random.Random, width: int, height: int, feature_size: int, octaves: int
) -> list[float]:
    """Multi-octave value noise in [0, 1], fully determined by `rng`."""
    result = [0.0] * (width * height)
    amplitude, total, cell = 1.0, 0.0, feature_size
    for _ in range(octaves):
        cell = max(1, cell)
        grid_w = width // cell + 2
        lattice = [rng.random() for _ in range(grid_w * (height // cell + 2))]
        for y in range(height):
            gy, fy = divmod(y, cell)
            ty = _smooth(fy / cell)
            for x in range(width):
                gx, fx = divmod(x, cell)
                tx = _smooth(fx / cell)
                i = gy * grid_w + gx
                top = lattice[i] + (lattice[i + 1] - lattice[i]) * tx
                bottom = lattice[i + grid_w] + (lattice[i + grid_w + 1] - lattice[i + grid_w]) * tx
                result[y * width + x] += amplitude * (top + (bottom - top) * ty)
        total += amplitude
        amplitude *= 0.5
        cell //= 2
    return [v / total for v in result]


def _validate(params: MapParams, registry: Registry) -> None:
    if params.width < 1 or params.height < 1:
        raise ValueError("width and height must be at least 1")
    if params.start_radius < 0:
        raise ValueError("start_radius must be non-negative")
    if params.feature_size < 1:
        raise ValueError("feature_size must be at least 1")
    if params.octaves < 1:
        raise ValueError("octaves must be at least 1")
    if not params.bands:
        raise ValueError("map needs at least one band")
    if any(band.share < 0 for band in params.bands):
        raise ValueError("band shares must be non-negative")
    if abs(sum(band.share for band in params.bands) - 1.0) > 1e-9:
        raise ValueError("band shares must sum to 1")
    names = [b.terrain for b in params.bands] + [v.terrain for v in params.veins]
    for name in [*names, params.start_terrain]:
        if name not in registry.terrains:
            raise ValueError(f"unknown terrain {name!r}")
    band_share = {band.terrain: band.share for band in params.bands}
    vein_share: dict[str, float] = {}
    for vein in params.veins:
        if vein.host not in band_share:
            raise ValueError(f"vein {vein.terrain!r}: host {vein.host!r} is not a band")
        if vein.share < 0:
            raise ValueError(f"vein {vein.terrain!r}: share must be non-negative")
        vein_share[vein.host] = vein_share.get(vein.host, 0.0) + vein.share
    for host, share in vein_share.items():
        if share > band_share[host] + 1e-9:
            raise ValueError(f"veins on {host!r} take more than their host band's share")
    if not registry.terrains[params.start_terrain].walkable:
        raise ValueError(f"start_terrain {params.start_terrain!r} is not walkable")


def generate_map(seed: int, params: MapParams, registry: Registry) -> TileMap:
    _validate(params, registry)
    width, height = params.width, params.height
    n = width * height
    rng = random.Random(seed)
    elevation = value_noise(rng, width, height, params.feature_size, params.octaves)
    order = sorted(range(n), key=lambda i: (elevation[i], i))
    terrain = [""] * n
    start, cumulative = 0, 0.0
    for k, band in enumerate(params.bands):
        cumulative += band.share
        end = n if k == len(params.bands) - 1 else min(n, round(cumulative * n))
        for i in order[start:end]:
            terrain[i] = band.terrain
        start = max(start, end)
    for vein in params.veins:
        noise = value_noise(
            rng, width, height, max(1, params.feature_size // 2), params.octaves
        )
        hosts = sorted((i for i in range(n) if terrain[i] == vein.host), key=lambda i: (-noise[i], i))
        for i in hosts[: min(len(hosts), round(vein.share * n))]:
            terrain[i] = vein.terrain
    for c in start_area(width, height, params.start_radius):
        i = c.y * width + c.x
        if not registry.terrains[terrain[i]].walkable:
            terrain[i] = params.start_terrain
    return TileMap(width, height, terrain, [round(e, 6) for e in elevation])
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/pericles/test_mapgen.py -q`
Expected: all pass. If `test_full_size_proportions_within_five_points` fails for one terrain, check the start-area conversion. With radius 10 it may move at most ~2% of the map from water to grass. Never widen the tolerance.

- [ ] **Step 6: Gates, mutation, commit**

Run the four gates; `rm -rf mutants && uv run mutmut run "pericles.core.mapgen.*" ; uv run mutmut results --all true`. Kill survivors. Equivalent mutants (for example `max(1, cell)` vs `max(0, cell)` when cell is never 0) may be marked with a `# pragma: no mutate` comment on that line only, with a ruling explaining why they are equivalent.

```bash
git add src/pericles/core/mapgen.py tests/pericles/conftest.py tests/pericles/test_mapgen.py
git commit -m "feat(core): seeded map generation with exact band shares, veins and safe start area"
```

---

### Task 7: A* pathfinding

**Files:**
- Create: `src/pericles/core/pathfinding.py`
- Test: `tests/pericles/test_pathfinding.py`

**Interfaces:**
- Consumes: `Coord` (Task 1), `TileMap` (Task 6), `Registry` (Task 3).
- Produces:
  - `class CostField(Protocol)`: attributes `width: int`, `height: int`, `min_cost: float`; method `cost(c: Coord) -> float | None` (the cost of entering `c`; `None` = impassable or out of bounds)
  - `class TerrainCostField` implementing `CostField`: `__init__(tilemap: TileMap, registry: Registry, blocked: Callable[[Coord], bool] | None = None)`
  - `find_path(field: CostField, start: Coord, goal: Coord) -> list[Coord] | None` (includes `start` and `goal`; `[start]` when equal; `None` when unreachable, out of bounds or the goal is impassable)
  - `path_cost(field: CostField, path: Sequence[Coord]) -> float` (sum of entering costs, excluding `start`)

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_pathfinding.py`:

```python
from collections.abc import Sequence

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import Band, MapParams, TileMap, generate_map
from pericles.core.pathfinding import TerrainCostField, find_path, path_cost

pytestmark = pytest.mark.req("REQ-SIM-004")


class Grid:
    """A test cost field from rows of costs (None = wall)."""

    def __init__(self, rows: Sequence[Sequence[float | None]]):
        self.rows = rows
        self.height = len(rows)
        self.width = len(rows[0])
        costs = [c for row in rows for c in row if c is not None]
        self.min_cost = min(costs) if costs else 1.0

    def cost(self, c: Coord) -> float | None:
        if not (0 <= c.x < self.width and 0 <= c.y < self.height):
            return None
        return self.rows[c.y][c.x]


def dijkstra(field: Grid, start: Coord, goal: Coord) -> float | None:
    best = {start: 0.0}
    frontier = [start]
    while frontier:
        nxt = []
        for cur in frontier:
            for nb in cur.neighbours4():
                step = field.cost(nb)
                if step is None:
                    continue
                cand = best[cur] + step
                if cand < best.get(nb, float("inf")) - 1e-12:
                    best[nb] = cand
                    nxt.append(nb)
        frontier = nxt
    return best.get(goal)


def assert_valid(field: Grid, path: list[Coord], start: Coord, goal: Coord) -> None:
    assert path[0] == start and path[-1] == goal
    for a, b in zip(path, path[1:], strict=False):
        assert a.manhattan(b) == 1
        assert field.cost(b) is not None


def test_straight_line() -> None:
    field = Grid([[1, 1, 1, 1]])
    assert find_path(field, Coord(0, 0), Coord(3, 0)) == [
        Coord(0, 0), Coord(1, 0), Coord(2, 0), Coord(3, 0)
    ]


def test_prefers_cheaper_detour() -> None:
    """AC1: shortest *cost* path, not shortest step count."""
    field = Grid([[1, 9, 1], [1, 1, 1]])
    path = find_path(field, Coord(0, 0), Coord(2, 0))
    assert path is not None
    assert path_cost(field, path) == 4
    assert Coord(1, 0) not in path


def test_start_equals_goal() -> None:
    assert find_path(Grid([[1]]), Coord(0, 0), Coord(0, 0)) == [Coord(0, 0)]


def test_unreachable_goal_returns_none() -> None:
    """AC2: an unreachable target returns no path."""
    field = Grid([[1, None, 1], [1, None, 1]])
    assert find_path(field, Coord(0, 0), Coord(2, 0)) is None


@pytest.mark.parametrize("goal", [Coord(5, 0), Coord(-1, 0), Coord(1, 0)])
def test_out_of_bounds_or_impassable_goal(goal: Coord) -> None:
    assert find_path(Grid([[1, None, 1]]), Coord(0, 0), goal) is None


def test_out_of_bounds_start() -> None:
    assert find_path(Grid([[1, 1]]), Coord(-1, 0), Coord(1, 0)) is None


def test_path_cost() -> None:
    field = Grid([[5, 2, 3]])
    assert path_cost(field, [Coord(0, 0), Coord(1, 0), Coord(2, 0)]) == 5
    assert path_cost(field, [Coord(0, 0)]) == 0


@settings(max_examples=150, deadline=None)
@given(
    st.integers(1, 7).flatmap(
        lambda w: st.lists(
            st.lists(st.sampled_from([None, 1.0, 2.0, 5.0]), min_size=w, max_size=w),
            min_size=1,
            max_size=7,
        )
    ),
    st.data(),
)
def test_matches_dijkstra_on_random_grids(rows: list[list[float | None]], data: st.DataObject) -> None:
    """AC1/AC2: A* cost equals brute-force optimum; unreachable ⇔ None."""
    field = Grid(rows)
    start = Coord(data.draw(st.integers(0, field.width - 1)), data.draw(st.integers(0, field.height - 1)))
    goal = Coord(data.draw(st.integers(0, field.width - 1)), data.draw(st.integers(0, field.height - 1)))
    path = find_path(field, start, goal)
    if start == goal:
        assert path == [start]
        return
    expected = dijkstra(field, start, goal) if field.cost(goal) is not None else None
    if expected is None:
        assert path is None
    else:
        assert path is not None
        assert_valid(field, path, start, goal)
        assert path_cost(field, path) == pytest.approx(expected)


def test_deterministic_tie_breaking() -> None:
    field = Grid([[1, 1, 1], [1, 1, 1], [1, 1, 1]])
    paths = {tuple(find_path(field, Coord(0, 0), Coord(2, 2)) or []) for _ in range(5)}
    assert len(paths) == 1


def test_terrain_cost_field(registry: Registry) -> None:
    """AC3: water is not walkable; blocked tiles (later: buildings) are impassable."""
    tilemap = TileMap(3, 1, ["grass", "forest", "water"], [0.0, 0.0, 0.0])
    field = TerrainCostField(tilemap, registry)
    assert (field.width, field.height, field.min_cost) == (3, 1, 1.0)
    assert field.cost(Coord(0, 0)) == registry.terrains["grass"].move_cost
    assert field.cost(Coord(1, 0)) == registry.terrains["forest"].move_cost
    assert field.cost(Coord(2, 0)) is None
    assert field.cost(Coord(3, 0)) is None
    blocked = TerrainCostField(tilemap, registry, blocked=lambda c: c == Coord(1, 0))
    assert blocked.cost(Coord(1, 0)) is None
    assert blocked.cost(Coord(0, 0)) == 1.0


def test_terrain_field_without_walkable_tiles(registry: Registry) -> None:
    field = TerrainCostField(TileMap(1, 1, ["water"], [0.0]), registry)
    assert field.min_cost == 1.0


def test_unreachable_on_full_size_map(registry: Registry) -> None:
    """AC2: an island goal on a 128x128 map returns None without hanging."""
    params = MapParams(width=128, height=128, bands=(Band("grass", 1.0),), start_terrain="grass")
    tilemap = generate_map(0, params, registry)
    island = Coord(100, 100)
    walls = set(island.neighbours4())
    field = TerrainCostField(tilemap, registry, blocked=lambda c: c in walls)
    assert find_path(field, Coord(0, 0), island) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pericles/test_pathfinding.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.core.pathfinding'`

- [ ] **Step 3: Implement `src/pericles/core/pathfinding.py`**

```python
"""A* pathfinding over tile costs (REQ-SIM-004)."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Sequence
from typing import Protocol

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap


class CostField(Protocol):
    width: int
    height: int
    min_cost: float

    def cost(self, c: Coord) -> float | None: ...


class TerrainCostField:
    def __init__(
        self,
        tilemap: TileMap,
        registry: Registry,
        blocked: Callable[[Coord], bool] | None = None,
    ) -> None:
        self.width = tilemap.width
        self.height = tilemap.height
        self._costs: list[float | None] = []
        for name in tilemap.terrain:
            terrain = registry.terrains[name]
            self._costs.append(terrain.move_cost if terrain.walkable else None)
        walkable = [c for c in self._costs if c is not None]
        self.min_cost = min(walkable) if walkable else 1.0
        self._blocked = blocked

    def cost(self, c: Coord) -> float | None:
        if not (0 <= c.x < self.width and 0 <= c.y < self.height):
            return None
        if self._blocked is not None and self._blocked(c):
            return None
        return self._costs[c.y * self.width + c.x]


def _in_bounds(field: CostField, c: Coord) -> bool:
    return 0 <= c.x < field.width and 0 <= c.y < field.height


def find_path(field: CostField, start: Coord, goal: Coord) -> list[Coord] | None:
    if not (_in_bounds(field, start) and _in_bounds(field, goal)):
        return None
    if start == goal:
        return [start]
    if field.cost(goal) is None:
        return None
    best: dict[Coord, float] = {start: 0.0}
    came_from: dict[Coord, Coord] = {}
    closed: set[Coord] = set()
    frontier: list[tuple[float, float, Coord]] = [(0.0, 0.0, start)]
    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current in closed:
            continue
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path[::-1]
        closed.add(current)
        for nb in current.neighbours4():
            if nb in closed:
                continue
            step = field.cost(nb)
            if step is None:
                continue
            cost = best[current] + step
            if cost < best.get(nb, float("inf")):
                best[nb] = cost
                came_from[nb] = current
                h = nb.manhattan(goal) * field.min_cost
                heapq.heappush(frontier, (cost + h, h, nb))
    return None


def path_cost(field: CostField, path: Sequence[Coord]) -> float:
    total = 0.0
    for c in path[1:]:
        step = field.cost(c)
        if step is None:
            raise ValueError(f"path enters impassable tile {c}")
        total += step
    return total
```

- [ ] **Step 4: Run the tests, gates, mutation, commit**

Run: `uv run pytest tests/pericles/test_pathfinding.py -q` → all pass. Run the four gates. Run `rm -rf mutants && uv run mutmut run "pericles.core.pathfinding.*" ; uv run mutmut results --all true` and kill survivors. If the heuristic multiplier mutant survives, add a test where an inadmissible heuristic would give a suboptimal path.

```bash
git add src/pericles/core/pathfinding.py tests/pericles/test_pathfinding.py
git commit -m "feat(core): deterministic A* pathfinding over terrain costs"
```

---

### Task 8: World state, intents, events and the deterministic engine step

**Files:**
- Create: `src/pericles/core/events.py`, `src/pericles/core/intents.py`, `src/pericles/core/state.py`, `src/pericles/core/engine.py`
- Modify: `tests/pericles/conftest.py` (add `small_map` fixture)
- Test: `tests/pericles/test_state.py`, `tests/pericles/test_engine.py`

**Interfaces:**
- Consumes: `Coord`, `digest`, `canonical_json` (Task 1); `Registry` (Task 3); `Modifier`, `expire` (Task 4); `TileMap` (Task 6); `TerrainCostField`, `find_path` (Task 7).
- Produces:
  - `events.py`: `@dataclass(frozen=True) class Event: tick: int; seq: int; kind: str; data: Mapping[str, Any]` with `to_dict() -> dict[str, Any]`, `from_dict(d) -> Event` (classmethod); `class EventSink` with `__init__(tick: int)`, attribute `events: list[Event]`, `emit(kind: str, **data: Any) -> Event` (seq = index within the tick)
  - `intents.py`: `@dataclass(frozen=True) class Intent: actor: str` with `kind: ClassVar[str]` and `sort_key() -> tuple[str, str, str]`; `@dataclass(frozen=True) class MoveTo(Intent): target: Coord` (`kind = "move_to"`); `@dataclass(frozen=True) class Wait(Intent)` (`kind = "wait"`)
  - `state.py`: `@dataclass class Villager: id: str; name: str; pos: Coord; path: list[Coord] = []; move_progress: float = 0.0` with `to_dict`/`from_dict`; `@dataclass class WorldState: seed: int; tick: int; tilemap: TileMap; villagers: dict[str, Villager]; modifiers: tuple[Modifier, ...]; rng: random.Random` with `new(seed: int, tilemap: TileMap, villagers: Iterable[Villager] = ()) -> WorldState` (classmethod; `rng = random.Random(f"pericles-world-{seed}")`), `to_dict() -> dict[str, Any]`, `from_dict(d) -> WorldState` (classmethod), `digest() -> str`
  - `engine.py`: `Handler = Callable[[WorldState, Intent, EventSink], None]`; `class Engine` with `__init__(registry: Registry)`, `register(intent_type: type[Intent], handler: Handler) -> None` and `step(state: WorldState, intents: Sequence[Intent]) -> tuple[WorldState, list[Event]]`

Event kinds emitted in M1a (data keys in parentheses):
- `intent_rejected` (`actor`, `intent`, `reason`: `unknown_actor` | `duplicate_intent` | `unknown_intent`)
- `move_started` (`actor`, `target`: [x, y], `steps`)
- `move_failed` (`actor`, `target`, `reason`: `no_path` | `blocked`)
- `moved` (`actor`, `to`: [x, y])
- `arrived` (`actor`, `at`: [x, y])
- `stopped` (`actor`, `at`)

Step semantics:
1. Intents are sorted by `sort_key()`, then shuffled with `state.rng`.
2. For each intent: an unknown actor is rejected, a second intent by the same actor in the tick is rejected, otherwise the registered handler runs.
3. Movement advances for all villagers in id order. Each tick adds 1.0 to `move_progress`, and entering the next tile consumes its cost. Several tiles per tick are possible only if costs are below 1.
4. Modifiers expire at `tick + 1`.
5. `state.tick` increments.

Events carry the tick being processed.

- [ ] **Step 1: Add the `small_map` fixture**

Append to `tests/pericles/conftest.py` (imports at top):

```python
from pericles.core.mapgen import TileMap, generate_map


@pytest.fixture
def small_map(registry: Registry) -> TileMap:
    params = MapParams(
        width=24,
        height=24,
        bands=(Band("water", 0.15), Band("grass", 0.6), Band("forest", 0.25)),
        start_terrain="grass",
        start_radius=5,
        feature_size=8,
    )
    return generate_map(11, params, registry)
```

- [ ] **Step 2: Write the failing tests**

`tests/pericles/test_state.py`:

```python
import pytest

from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import Modifier, Op, Scope, Target
from pericles.core.state import Villager, WorldState

pytestmark = pytest.mark.req("REQ-SIM-002")


def make_state(small_map: TileMap) -> WorldState:
    state = WorldState.new(
        42,
        small_map,
        [Villager("b", "Bo", Coord(12, 12)), Villager("a", "Ana", Coord(11, 12))],
    )
    state.villagers["a"].path = [Coord(12, 12)]
    state.villagers["a"].move_progress = 0.5
    state.modifiers = (
        Modifier(Target("action"), "work_speed", Op.MUL, 1.2, "test", Scope(until_tick=10)),
    )
    state.rng.random()
    return state


def test_round_trip_preserves_everything_including_rng(small_map: TileMap) -> None:
    """AC1 (support): a state can be saved and restored exactly."""
    state = make_state(small_map)
    clone = WorldState.from_dict(state.to_dict())
    assert clone.digest() == state.digest()
    assert clone.rng.random() == state.rng.random()
    assert clone.villagers["a"].path == [Coord(12, 12)]
    assert isinstance(clone.villagers["a"].pos, Coord)


def test_new_state_is_seeded_and_ordered(small_map: TileMap) -> None:
    a = WorldState.new(1, small_map, [Villager("b", "Bo", Coord(1, 1)), Villager("a", "A", Coord(2, 2))])
    b = WorldState.new(1, small_map, [Villager("a", "A", Coord(2, 2)), Villager("b", "Bo", Coord(1, 1))])
    c = WorldState.new(2, small_map, [Villager("a", "A", Coord(2, 2)), Villager("b", "Bo", Coord(1, 1))])
    assert a.tick == 0 and a.modifiers == ()
    assert a.digest() == b.digest()
    assert a.digest() != c.digest()
    assert list(a.villagers) == ["a", "b"]


def test_duplicate_villager_ids_are_rejected(small_map: TileMap) -> None:
    with pytest.raises(ValueError, match="duplicate villager id 'a'"):
        WorldState.new(1, small_map, [Villager("a", "A", Coord(1, 1)), Villager("a", "B", Coord(2, 2))])


def test_digest_changes_with_any_field(small_map: TileMap) -> None:
    base = make_state(small_map).digest()
    for mutate in (
        lambda s: setattr(s, "tick", 1),
        lambda s: setattr(s.villagers["b"], "pos", Coord(0, 0)),
        lambda s: setattr(s.villagers["a"], "move_progress", 0.75),
        lambda s: setattr(s, "modifiers", ()),
        lambda s: s.rng.random(),
    ):
        state = make_state(small_map)
        mutate(state)
        assert state.digest() != base
```

`tests/pericles/test_engine.py`:

```python
import itertools
from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pericles.core.content.registry import Registry, base_pack_path, load_registry
from pericles.core.engine import Engine
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo, Wait
from pericles.core.mapgen import Band, MapParams, TileMap, generate_map
from pericles.core.modifiers import Modifier, Op, Scope, Target
from pericles.core.state import Villager, WorldState


def fresh(small_map: TileMap, seed: int = 5) -> WorldState:
    return WorldState.new(
        seed,
        small_map,
        [Villager(v, v.upper(), Coord(10 + i, 12)) for i, v in enumerate(["a", "b", "c"])],
    )


def walkable_targets(small_map: TileMap, registry: Registry) -> list[Coord]:
    return [
        Coord(x, y)
        for y in range(small_map.height)
        for x in range(small_map.width)
        if registry.terrains[small_map.terrain_at(Coord(x, y))].walkable
    ]


def as_dicts(events: list[Event]) -> list[dict[str, object]]:
    return [e.to_dict() for e in events]


@pytest.mark.req("REQ-SIM-002")
def test_identical_inputs_give_identical_runs(registry: Registry, small_map: TileMap) -> None:
    """AC1: identical state, intents and seed → identical state and events."""
    targets = walkable_targets(small_map, registry)

    def run() -> tuple[str, list[dict[str, object]]]:
        engine, state = Engine(registry), fresh(small_map)
        log: list[dict[str, object]] = []
        for tick in range(60):
            intents: list[Intent] = []
            if tick % 20 == 0:
                intents = [MoveTo(v, targets[(tick * 7 + i * 31) % len(targets)])
                           for i, v in enumerate("abc")]
            state, events = engine.step(state, intents)
            log += as_dicts(events)
        return state.digest(), log

    assert run() == run()


@pytest.mark.req("REQ-SIM-002")
def test_submission_order_does_not_matter(registry: Registry, small_map: TileMap) -> None:
    """AC2: intents in any order resolve identically (including conflicts)."""
    targets = walkable_targets(small_map, registry)
    intents: list[Intent] = [
        MoveTo("a", targets[3]),
        MoveTo("a", targets[40]),
        MoveTo("b", targets[90]),
        Wait("c"),
        MoveTo("ghost", targets[1]),
    ]
    outcomes = set()
    for perm in itertools.permutations(intents):
        state, events = Engine(registry).step(fresh(small_map), list(perm))
        outcomes.add((state.digest(), str(as_dicts(events))))
    assert len(outcomes) == 1


@pytest.mark.req("REQ-SIM-002")
@settings(max_examples=30, deadline=None)
@given(st.permutations(list(range(6))))
def test_submission_order_property(order: list[int]) -> None:
    """AC2 (property): any permutation of a tick's intents gives the same result."""
    registry = load_registry([base_pack_path()])
    tilemap = generate_map(
        1, MapParams(12, 12, (Band("grass", 1.0),), start_terrain="grass"), registry
    )
    villagers = [Villager(f"v{i}", f"V{i}", Coord(i, 0)) for i in range(6)]
    intents = [MoveTo(f"v{i}", Coord(11 - i, 11)) for i in range(6)]
    baseline = Engine(registry).step(WorldState.new(3, tilemap, villagers), intents)
    shuffled = Engine(registry).step(
        WorldState.new(3, tilemap, [Villager(v.id, v.name, v.pos) for v in villagers]),
        [intents[i] for i in order],
    )
    assert shuffled[0].digest() == baseline[0].digest()
    assert as_dicts(shuffled[1]) == as_dicts(baseline[1])


@pytest.mark.req("REQ-SIM-002")
def test_tick_increments_and_events_carry_processed_tick(
    registry: Registry, small_map: TileMap
) -> None:
    """AC3 (support): state.tick counts processed ticks; events carry the tick processed."""
    engine, state = Engine(registry), fresh(small_map)
    state, events = engine.step(state, [MoveTo("ghost", Coord(0, 0))])
    assert state.tick == 1
    assert [(e.tick, e.seq, e.kind) for e in events] == [(0, 0, "intent_rejected")]
    assert events[0].data == {"actor": "ghost", "intent": "move_to", "reason": "unknown_actor"}


@pytest.mark.req("REQ-SIM-004")
def test_villager_walks_path_and_arrives(registry: Registry) -> None:
    """AC1: movement follows the A* path; entering a tile costs its move_cost in ticks."""
    tilemap = TileMap(4, 1, ["grass", "forest", "grass", "grass"], [0.0] * 4)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    # tick 0: path set, progress 1.0 < forest cost 2, so no move yet
    state, events = engine.step(state, [MoveTo("a", Coord(3, 0))])
    assert [e.kind for e in events] == ["move_started"]
    assert events[0].data == {"actor": "a", "target": [3, 0], "steps": 3}
    assert state.villagers["a"].pos == Coord(0, 0)
    kinds: list[list[str]] = []
    for _ in range(4):
        state, events = engine.step(state, [])
        kinds.append([e.kind for e in events])
    # tick 1: progress 2 enters forest; ticks 2 and 3 enter grass (cost 1); tick 4: idle
    assert kinds == [["moved"], ["moved"], ["moved", "arrived"], []]
    assert state.villagers["a"].pos == Coord(3, 0)
    assert state.villagers["a"].path == []
    assert state.villagers["a"].move_progress == 0.0


@pytest.mark.req("REQ-SIM-004")
def test_unreachable_target_fails_cleanly(registry: Registry) -> None:
    """AC2: no path → a move_failed event, no exception."""
    tilemap = TileMap(3, 1, ["grass", "water", "grass"], [0.0] * 3)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    state, events = Engine(registry).step(state, [MoveTo("a", Coord(2, 0))])
    assert [(e.kind, e.data) for e in events] == [
        ("move_failed", {"actor": "a", "target": [2, 0], "reason": "no_path"})
    ]
    assert state.villagers["a"].path == []


@pytest.mark.req("REQ-SIM-004")
def test_move_to_own_tile_arrives_immediately(registry: Registry) -> None:
    tilemap = TileMap(2, 1, ["grass", "grass"], [0.0] * 2)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(1, 0))])
    state, events = Engine(registry).step(state, [MoveTo("a", Coord(1, 0))])
    assert [(e.kind, e.data) for e in events] == [("arrived", {"actor": "a", "at": [1, 0]})]


@pytest.mark.req("REQ-SIM-004")
def test_path_blocked_after_terrain_change(registry: Registry) -> None:
    # forest (cost 2) at (1, 0) keeps the villager at (0, 0) after tick 0
    tilemap = TileMap(3, 1, ["grass", "forest", "grass"], [0.0] * 3)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    state, _ = engine.step(state, [MoveTo("a", Coord(2, 0))])
    assert state.villagers["a"].pos == Coord(0, 0)
    state.tilemap = TileMap(3, 1, ["grass", "water", "grass"], [0.0] * 3)
    state, events = engine.step(state, [])
    assert [(e.kind, e.data) for e in events] == [
        ("move_failed", {"actor": "a", "target": [2, 0], "reason": "blocked"})
    ]
    assert state.villagers["a"].path == [] and state.villagers["a"].pos == Coord(0, 0)


@pytest.mark.req("REQ-SIM-002")
def test_wait_stops_movement(registry: Registry) -> None:
    tilemap = TileMap(5, 1, ["grass"] * 5, [0.0] * 5)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    state, events = engine.step(state, [MoveTo("a", Coord(4, 0))])
    assert [e.kind for e in events] == ["move_started", "moved"]
    state, events = engine.step(state, [Wait("a")])
    assert [(e.kind, e.data) for e in events] == [("stopped", {"actor": "a", "at": [1, 0]})]
    assert state.villagers["a"].pos == Coord(1, 0)
    state, events = engine.step(state, [Wait("a")])
    assert events == []


@pytest.mark.req("REQ-SIM-002")
def test_duplicate_and_unknown_intents_are_rejected(registry: Registry, small_map: TileMap) -> None:
    @dataclass(frozen=True)
    class Dance(Intent):
        kind = "dance"

    state, events = Engine(registry).step(
        fresh(small_map), [Wait("a"), Wait("a"), Dance("b")]
    )
    reasons = sorted(e.data["reason"] for e in events if e.kind == "intent_rejected")
    assert reasons == ["duplicate_intent", "unknown_intent"]


@pytest.mark.req("REQ-SIM-002")
def test_register_custom_handler(registry: Registry, small_map: TileMap) -> None:
    @dataclass(frozen=True)
    class Shout(Intent):
        kind = "shout"

    def handle(state: WorldState, intent: Intent, sink: EventSink) -> None:
        sink.emit("shouted", actor=intent.actor)

    engine = Engine(registry)
    engine.register(Shout, handle)
    _, events = engine.step(fresh(small_map), [Shout("a")])
    assert [(e.kind, e.data) for e in events] == [("shouted", {"actor": "a"})]


@pytest.mark.req("REQ-SIM-006")
def test_step_expires_modifiers(registry: Registry, small_map: TileMap) -> None:
    """AC4: time-limited modifiers disappear when their tick passes."""
    state = fresh(small_map)
    keep = Modifier(Target("action"), "work_speed", Op.ADD, 1, "keep")
    temp = Modifier(Target("action"), "work_speed", Op.ADD, 1, "temp", Scope(until_tick=2))
    state.modifiers = (keep, temp)
    engine = Engine(registry)
    state, _ = engine.step(state, [])
    assert state.modifiers == (keep, temp)
    state, _ = engine.step(state, [])
    assert state.modifiers == (keep,)


def test_event_round_trip() -> None:
    sink = EventSink(4)
    first = sink.emit("moved", actor="a", to=[1, 2])
    second = sink.emit("arrived", actor="a", at=[1, 2])
    assert (first.seq, second.seq) == (0, 1)
    assert sink.events == [first, second]
    assert Event.from_dict(first.to_dict()) == first
    assert first.to_dict() == {"tick": 4, "seq": 0, "kind": "moved", "data": {"actor": "a", "to": [1, 2]}}


def test_intent_sort_key_is_canonical() -> None:
    assert MoveTo("a", Coord(1, 2)).sort_key() == ("a", "move_to", '{"actor":"a","target":[1,2]}')
    assert Wait("b").sort_key() == ("b", "wait", '{"actor":"b"}')
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/pericles/test_state.py tests/pericles/test_engine.py -q`
Expected: FAIL with `ModuleNotFoundError` for `pericles.core.state` / `pericles.core.engine`.

- [ ] **Step 4: Implement `events.py` and `intents.py`**

`src/pericles/core/events.py`:

```python
"""Typed simulation events (ADR-0004)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    tick: int
    seq: int
    kind: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"tick": self.tick, "seq": self.seq, "kind": self.kind, "data": dict(self.data)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Event:
        return cls(int(data["tick"]), int(data["seq"]), str(data["kind"]), dict(data["data"]))


class EventSink:
    """Collects one tick's events and numbers them."""

    def __init__(self, tick: int) -> None:
        self.tick = tick
        self.events: list[Event] = []

    def emit(self, kind: str, **data: Any) -> Event:
        event = Event(self.tick, len(self.events), kind, data)
        self.events.append(event)
        return event
```

`src/pericles/core/intents.py`:

```python
"""What villagers ask the engine to do (spec §3.2: intents, not mutations)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar

from pericles.core.canonical import canonical_json
from pericles.core.geometry import Coord


@dataclass(frozen=True)
class Intent:
    actor: str
    kind: ClassVar[str] = "intent"

    def sort_key(self) -> tuple[str, str, str]:
        return (self.actor, self.kind, canonical_json(asdict(self)))


@dataclass(frozen=True)
class MoveTo(Intent):
    target: Coord
    kind: ClassVar[str] = "move_to"


@dataclass(frozen=True)
class Wait(Intent):
    kind: ClassVar[str] = "wait"
```

- [ ] **Step 5: Implement `state.py`**

`src/pericles/core/state.py`:

```python
"""The complete, serialisable world state (ADR-0013)."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pericles.core.canonical import digest
from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import Modifier


@dataclass
class Villager:
    id: str
    name: str
    pos: Coord
    path: list[Coord] = field(default_factory=list)
    move_progress: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "pos": list(self.pos),
            "path": [list(c) for c in self.path],
            "move_progress": self.move_progress,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Villager:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            pos=Coord(*data["pos"]),
            path=[Coord(*c) for c in data["path"]],
            move_progress=float(data["move_progress"]),
        )


def _rng_to_json(rng: random.Random) -> dict[str, Any]:
    version, internal, gauss = rng.getstate()
    return {"version": version, "internal": list(internal), "gauss": gauss}


def _rng_from_json(data: Mapping[str, Any]) -> random.Random:
    rng = random.Random()
    rng.setstate((data["version"], tuple(data["internal"]), data["gauss"]))
    return rng


@dataclass
class WorldState:
    seed: int
    tick: int
    tilemap: TileMap
    villagers: dict[str, Villager]
    modifiers: tuple[Modifier, ...]
    rng: random.Random

    @classmethod
    def new(cls, seed: int, tilemap: TileMap, villagers: Iterable[Villager] = ()) -> WorldState:
        by_id: dict[str, Villager] = {}
        for villager in sorted(villagers, key=lambda v: v.id):
            if villager.id in by_id:
                raise ValueError(f"duplicate villager id {villager.id!r}")
            by_id[villager.id] = villager
        return cls(
            seed=seed,
            tick=0,
            tilemap=tilemap,
            villagers=by_id,
            modifiers=(),
            rng=random.Random(f"pericles-world-{seed}"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "tick": self.tick,
            "tilemap": self.tilemap.to_dict(),
            "villagers": [self.villagers[k].to_dict() for k in sorted(self.villagers)],
            "modifiers": [m.to_dict() for m in self.modifiers],
            "rng": _rng_to_json(self.rng),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorldState:
        villagers = [Villager.from_dict(v) for v in data["villagers"]]
        return cls(
            seed=int(data["seed"]),
            tick=int(data["tick"]),
            tilemap=TileMap.from_dict(data["tilemap"]),
            villagers={v.id: v for v in villagers},
            modifiers=tuple(Modifier.from_dict(m) for m in data["modifiers"]),
            rng=_rng_from_json(data["rng"]),
        )

    def digest(self) -> str:
        return digest(self.to_dict())
```

- [ ] **Step 6: Implement `engine.py`**

`src/pericles/core/engine.py`:

```python
"""The deterministic tick loop (REQ-SIM-002, ADR-0001, ADR-0013)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pericles.core.content.registry import Registry
from pericles.core.events import Event, EventSink
from pericles.core.intents import Intent, MoveTo, Wait
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import expire
from pericles.core.pathfinding import TerrainCostField, find_path
from pericles.core.state import WorldState

Handler = Callable[[WorldState, Intent, EventSink], None]


class Engine:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._handlers: dict[type[Intent], Handler] = {
            MoveTo: self._move_to,
            Wait: self._wait,
        }
        self._field_map: TileMap | None = None
        self._field: TerrainCostField | None = None

    def register(self, intent_type: type[Intent], handler: Handler) -> None:
        self._handlers[intent_type] = handler

    def step(self, state: WorldState, intents: Sequence[Intent]) -> tuple[WorldState, list[Event]]:
        sink = EventSink(state.tick)
        ordered = sorted(intents, key=lambda i: i.sort_key())
        state.rng.shuffle(ordered)
        acted: set[str] = set()
        for intent in ordered:
            reason = None
            if intent.actor not in state.villagers:
                reason = "unknown_actor"
            elif intent.actor in acted:
                reason = "duplicate_intent"
            elif type(intent) not in self._handlers:
                reason = "unknown_intent"
            if reason is not None:
                sink.emit("intent_rejected", actor=intent.actor, intent=intent.kind, reason=reason)
                continue
            acted.add(intent.actor)
            self._handlers[type(intent)](state, intent, sink)
        self._advance_movement(state, sink)
        state.modifiers = expire(state.modifiers, state.tick + 1)
        state.tick += 1
        return state, sink.events

    def _cost_field(self, state: WorldState) -> TerrainCostField:
        if self._field is None or self._field_map is not state.tilemap:
            self._field = TerrainCostField(state.tilemap, self.registry)
            self._field_map = state.tilemap
        return self._field

    def _move_to(self, state: WorldState, intent: Intent, sink: EventSink) -> None:
        assert isinstance(intent, MoveTo)
        villager = state.villagers[intent.actor]
        path = find_path(self._cost_field(state), villager.pos, intent.target)
        villager.move_progress = 0.0
        if path is None:
            villager.path = []
            sink.emit("move_failed", actor=villager.id, target=list(intent.target), reason="no_path")
        elif len(path) == 1:
            villager.path = []
            sink.emit("arrived", actor=villager.id, at=list(villager.pos))
        else:
            villager.path = path[1:]
            sink.emit("move_started", actor=villager.id, target=list(intent.target), steps=len(path) - 1)

    def _wait(self, state: WorldState, intent: Intent, sink: EventSink) -> None:
        villager = state.villagers[intent.actor]
        if villager.path:
            villager.path = []
            villager.move_progress = 0.0
            sink.emit("stopped", actor=villager.id, at=list(villager.pos))

    def _advance_movement(self, state: WorldState, sink: EventSink) -> None:
        field = self._cost_field(state)
        for vid in sorted(state.villagers):
            villager = state.villagers[vid]
            if not villager.path:
                continue
            villager.move_progress += 1.0
            while villager.path:
                cost = field.cost(villager.path[0])
                if cost is None:
                    target = villager.path[-1]
                    villager.path = []
                    villager.move_progress = 0.0
                    sink.emit("move_failed", actor=vid, target=list(target), reason="blocked")
                    break
                if villager.move_progress < cost:
                    break
                villager.move_progress -= cost
                villager.pos = villager.path.pop(0)
                sink.emit("moved", actor=vid, to=list(villager.pos))
                if not villager.path:
                    villager.move_progress = 0.0
                    sink.emit("arrived", actor=vid, at=list(villager.pos))
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass. In `test_villager_walks_path_and_arrives`, if the per-tick event kinds differ, re-derive by hand from the step semantics above. Fix the engine to match the semantics, and change neither the semantics nor the expectation silently. Any change needs a ruling.

- [ ] **Step 8: Gates, mutation, commit**

Run the four gates. Run `rm -rf mutants && uv run mutmut run "pericles.core.events.*" "pericles.core.intents.*" "pericles.core.state.*" "pericles.core.engine.*" ; uv run mutmut results --all true`. Kill survivors (≥ 80% for each module).

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): world state, intents, events and deterministic engine step with movement"
```

---

### Task 9: Event log and run directory

**Files:**
- Create: `src/pericles/experiment/eventlog.py`, `src/pericles/experiment/rundir.py`
- Test: `tests/pericles/test_eventlog.py`, `tests/pericles/test_rundir.py`

**Interfaces:**
- Consumes: `Event` (Task 8), `canonical_json` (Task 1), `WorldState` (Task 8).
- Produces:
  - `class EventLog` with:
    - `__init__(path: Path)` (creates tables `events(tick, seq, kind, data)` with primary key `(tick, seq)`, and `ticks(tick PRIMARY KEY)`)
    - `append_tick(tick: int, events: Sequence[Event]) -> None` (one transaction; ticks must be contiguous starting at 0, or after `last_tick()`; every event's `tick` must equal `tick`)
    - `last_tick() -> int | None`
    - `events(start: int = 0, end: int | None = None) -> Iterator[Event]` (`start <= tick < end`, ordered by tick then seq)
    - `truncate_after(tick: int) -> None` (deletes ticks `> tick`; `-1` deletes all)
    - `digest() -> str`
    - `close() -> None`
  - `class RunDirectoryError(Exception)`
  - `class RunDirectory` with:
    - `SCHEMA_VERSION = 1`
    - `create(path: Path, config: Mapping[str, Any], seed: int) -> RunDirectory` (classmethod)
    - `open(path: Path) -> RunDirectory` (classmethod)
    - attribute `path`, properties `config: dict[str, Any]`, `meta: dict[str, Any]`, `event_log: EventLog`
    - `save_snapshot(state: WorldState) -> Path`, `latest_snapshot() -> dict[str, Any] | None`, `snapshot_ticks() -> list[int]`, `close() -> None`

Run directory layout (REQ-EXP-003 AC1; metrics arrive in M4): `config.yaml`, `meta.json`, `events.sqlite`, `snapshots/tick-<10-digit tick>.json`, `llm_cache/`.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_eventlog.py`:

```python
import sqlite3
from pathlib import Path

import pytest

from pericles.core.events import Event
from pericles.experiment.eventlog import EventLog

pytestmark = pytest.mark.req("REQ-EXP-003")


def ev(tick: int, seq: int, kind: str = "moved", **data: object) -> Event:
    return Event(tick, seq, kind, data)


def test_append_and_read_back(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.sqlite")
    assert log.last_tick() is None
    log.append_tick(0, [ev(0, 0, actor="a", to=[1, 2]), ev(0, 1, "arrived", actor="a")])
    log.append_tick(1, [])
    log.append_tick(2, [ev(2, 0, actor="b")])
    assert log.last_tick() == 2
    assert [e.to_dict() for e in log.events()] == [
        {"tick": 0, "seq": 0, "kind": "moved", "data": {"actor": "a", "to": [1, 2]}},
        {"tick": 0, "seq": 1, "kind": "arrived", "data": {"actor": "a"}},
        {"tick": 2, "seq": 0, "kind": "moved", "data": {"actor": "b"}},
    ]
    assert [e.tick for e in log.events(start=1, end=2)] == []
    assert [e.tick for e in log.events(start=2)] == [2]
    assert [e.tick for e in log.events(end=1)] == [0, 0]
    log.close()


def test_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite"
    log = EventLog(path)
    log.append_tick(0, [ev(0, 0)])
    log.close()
    reopened = EventLog(path)
    assert reopened.last_tick() == 0
    assert len(list(reopened.events())) == 1


def test_ticks_must_be_contiguous_from_zero(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.sqlite")
    with pytest.raises(ValueError, match="expected tick 0"):
        log.append_tick(1, [])
    log.append_tick(0, [])
    with pytest.raises(ValueError, match="expected tick 1"):
        log.append_tick(0, [])
    with pytest.raises(ValueError, match="expected tick 1"):
        log.append_tick(3, [])


def test_event_tick_must_match(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.sqlite")
    with pytest.raises(ValueError, match="event tick 5"):
        log.append_tick(0, [ev(5, 0)])


def test_failed_tick_is_rolled_back_entirely(tmp_path: Path) -> None:
    """AC2: event writes are transactional per tick."""
    log = EventLog(tmp_path / "e.sqlite")
    log.append_tick(0, [ev(0, 0)])
    with pytest.raises(sqlite3.IntegrityError):
        log.append_tick(1, [ev(1, 0), ev(1, 0)])
    assert log.last_tick() == 0
    assert [e.tick for e in log.events()] == [0]
    log.append_tick(1, [ev(1, 0)])
    assert log.last_tick() == 1


def test_unserialisable_data_writes_nothing(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.sqlite")
    with pytest.raises(ValueError):
        log.append_tick(0, [ev(0, 0, x=float("nan"))])
    assert log.last_tick() is None


def test_truncate_after(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.sqlite")
    for t in range(5):
        log.append_tick(t, [ev(t, 0)])
    log.truncate_after(2)
    assert log.last_tick() == 2
    assert [e.tick for e in log.events()] == [0, 1, 2]
    log.append_tick(3, [])
    log.truncate_after(-1)
    assert log.last_tick() is None


def test_digest_reflects_content_and_order(tmp_path: Path) -> None:
    a, b, c = (EventLog(tmp_path / f"{n}.sqlite") for n in "abc")
    a.append_tick(0, [ev(0, 0, x=1), ev(0, 1, x=2)])
    b.append_tick(0, [ev(0, 0, x=1), ev(0, 1, x=2)])
    c.append_tick(0, [ev(0, 0, x=2), ev(0, 1, x=1)])
    assert a.digest() == b.digest()
    assert a.digest() != c.digest()
    empty = EventLog(tmp_path / "d.sqlite")
    assert empty.digest() != a.digest()
```

`tests/pericles/test_rundir.py`:

```python
import json
from pathlib import Path

import pytest
import yaml

import pericles
from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap
from pericles.core.state import Villager, WorldState
from pericles.experiment.rundir import RunDirectory, RunDirectoryError

pytestmark = pytest.mark.req("REQ-EXP-003")

CONFIG = {"seed": 9, "map": {"width": 24}, "name": "test"}


def test_create_writes_layout(tmp_path: Path) -> None:
    """AC1: config snapshot, events.sqlite, snapshots/, llm_cache/ and meta.json."""
    run = RunDirectory.create(tmp_path / "run1", CONFIG, seed=9)
    root = tmp_path / "run1"
    assert yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) == CONFIG
    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == RunDirectory.SCHEMA_VERSION
    assert meta["seed"] == 9
    assert meta["pericles_version"] == pericles.__version__
    assert "created_utc" in meta and "python" in meta
    assert (root / "events.sqlite").exists()
    assert (root / "snapshots").is_dir() and (root / "llm_cache").is_dir()
    assert run.config == CONFIG and run.meta == meta
    run.close()


def test_create_into_empty_existing_directory(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    RunDirectory.create(tmp_path / "run", CONFIG, seed=1).close()


def test_refuses_to_reuse_a_non_empty_directory(tmp_path: Path) -> None:
    RunDirectory.create(tmp_path / "run", CONFIG, seed=1).close()
    with pytest.raises(RunDirectoryError, match="not empty"):
        RunDirectory.create(tmp_path / "run", CONFIG, seed=1)


def test_open_existing_and_validate(tmp_path: Path) -> None:
    RunDirectory.create(tmp_path / "run", CONFIG, seed=1).close()
    run = RunDirectory.open(tmp_path / "run")
    assert run.config == CONFIG
    run.close()
    with pytest.raises(RunDirectoryError, match="not a run directory"):
        RunDirectory.open(tmp_path)
    meta_path = tmp_path / "run" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["schema_version"] = 999
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(RunDirectoryError, match="schema version 999"):
        RunDirectory.open(tmp_path / "run")


def make_state(tick: int) -> WorldState:
    state = WorldState.new(3, TileMap(2, 1, ["grass", "grass"], [0.0, 0.5]), [Villager("a", "A", Coord(0, 0))])
    state.tick = tick
    return state


def test_snapshots_save_and_latest(tmp_path: Path) -> None:
    run = RunDirectory.create(tmp_path / "run", CONFIG, seed=3)
    assert run.latest_snapshot() is None
    first = run.save_snapshot(make_state(0))
    run.save_snapshot(make_state(20))
    run.save_snapshot(make_state(10))
    assert first.name == "tick-0000000000.json"
    assert run.snapshot_ticks() == [0, 10, 20]
    latest = run.latest_snapshot()
    assert latest is not None and latest["tick"] == 20
    assert WorldState.from_dict(latest).digest() == make_state(20).digest()
    assert not list((tmp_path / "run" / "snapshots").glob("*.tmp"))
    run.close()


def test_event_log_is_shared(tmp_path: Path) -> None:
    run = RunDirectory.create(tmp_path / "run", CONFIG, seed=3)
    assert run.event_log is run.event_log
    run.event_log.append_tick(0, [])
    run.close()
    reopened = RunDirectory.open(tmp_path / "run")
    assert reopened.event_log.last_tick() == 0
    reopened.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pericles/test_eventlog.py tests/pericles/test_rundir.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.experiment.eventlog'`

- [ ] **Step 3: Implement `src/pericles/experiment/eventlog.py`**

```python
"""Append-only, per-tick transactional event log in SQLite (ADR-0004, REQ-EXP-003 AC2)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path

from pericles.core.canonical import canonical_json
from pericles.core.events import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    tick INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (tick, seq)
);
CREATE TABLE IF NOT EXISTS ticks (tick INTEGER PRIMARY KEY);
"""


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def last_tick(self) -> int | None:
        row = self._conn.execute("SELECT MAX(tick) FROM ticks").fetchone()
        return None if row[0] is None else int(row[0])

    def append_tick(self, tick: int, events: Sequence[Event]) -> None:
        last = self.last_tick()
        expected = 0 if last is None else last + 1
        if tick != expected:
            raise ValueError(f"expected tick {expected}, got {tick}")
        rows = []
        for event in events:
            if event.tick != tick:
                raise ValueError(f"event tick {event.tick} does not match tick {tick}")
            rows.append((event.tick, event.seq, event.kind, canonical_json(dict(event.data))))
        with self._conn:
            self._conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", rows)
            self._conn.execute("INSERT INTO ticks VALUES (?)", (tick,))

    def events(self, start: int = 0, end: int | None = None) -> Iterator[Event]:
        query = "SELECT tick, seq, kind, data FROM events WHERE tick >= ?"
        params: list[int] = [start]
        if end is not None:
            query += " AND tick < ?"
            params.append(end)
        for tick, seq, kind, data in self._conn.execute(query + " ORDER BY tick, seq", params):
            yield Event(int(tick), int(seq), str(kind), json.loads(data))

    def truncate_after(self, tick: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM events WHERE tick > ?", (tick,))
            self._conn.execute("DELETE FROM ticks WHERE tick > ?", (tick,))

    def digest(self) -> str:
        hasher = hashlib.sha256()
        hasher.update(f"ticks:{self.last_tick()}\n".encode())
        for event in self.events():
            hasher.update(canonical_json(event.to_dict()).encode("utf-8"))
            hasher.update(b"\n")
        return hasher.hexdigest()

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Implement `src/pericles/experiment/rundir.py`**

```python
"""Run directories: config, meta, event log, snapshots (REQ-EXP-003)."""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

import pericles
from pericles.core.canonical import canonical_json
from pericles.core.state import WorldState
from pericles.experiment.eventlog import EventLog


class RunDirectoryError(Exception):
    """A run directory is missing, foreign or would be overwritten."""


class RunDirectory:
    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self._event_log: EventLog | None = None

    @classmethod
    def create(cls, path: Path, config: Mapping[str, Any], seed: int) -> RunDirectory:
        if path.exists() and any(path.iterdir()):
            raise RunDirectoryError(f"{path}: directory is not empty; refusing to reuse it")
        path.mkdir(parents=True, exist_ok=True)
        (path / "config.yaml").write_text(
            yaml.safe_dump(dict(config), sort_keys=True), encoding="utf-8"
        )
        meta = {
            "schema_version": cls.SCHEMA_VERSION,
            "pericles_version": pericles.__version__,
            "python": platform.python_version(),
            "seed": seed,
            "created_utc": datetime.now(UTC).isoformat(),
        }
        (path / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (path / "snapshots").mkdir()
        (path / "llm_cache").mkdir()
        run = cls(path)
        _ = run.event_log
        return run

    @classmethod
    def open(cls, path: Path) -> RunDirectory:
        meta_path = path / "meta.json"
        if not meta_path.exists():
            raise RunDirectoryError(f"{path}: not a run directory (no meta.json)")
        version = json.loads(meta_path.read_text(encoding="utf-8")).get("schema_version")
        if version != cls.SCHEMA_VERSION:
            raise RunDirectoryError(
                f"{path}: schema version {version} is not supported "
                f"(expected {cls.SCHEMA_VERSION})"
            )
        return cls(path)

    @property
    def config(self) -> dict[str, Any]:
        loaded = yaml.safe_load((self.path / "config.yaml").read_text(encoding="utf-8"))
        return dict(loaded or {})

    @property
    def meta(self) -> dict[str, Any]:
        return dict(json.loads((self.path / "meta.json").read_text(encoding="utf-8")))

    @property
    def event_log(self) -> EventLog:
        if self._event_log is None:
            self._event_log = EventLog(self.path / "events.sqlite")
        return self._event_log

    def save_snapshot(self, state: WorldState) -> Path:
        target = self.path / "snapshots" / f"tick-{state.tick:010d}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(canonical_json(state.to_dict()), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def snapshot_ticks(self) -> list[int]:
        return sorted(int(p.stem.removeprefix("tick-")) for p in (self.path / "snapshots").glob("tick-*.json"))

    def latest_snapshot(self) -> dict[str, Any] | None:
        ticks = self.snapshot_ticks()
        if not ticks:
            return None
        path = self.path / "snapshots" / f"tick-{ticks[-1]:010d}.json"
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def close(self) -> None:
        if self._event_log is not None:
            self._event_log.close()
            self._event_log = None
```

- [ ] **Step 5: Run the tests and gates, commit**

Run: `uv run pytest tests/pericles/test_eventlog.py tests/pericles/test_rundir.py -q` → all pass. Run the four gates. (`pericles.experiment` is not under the mutation gate, so no mutation step.)

```bash
git add src/pericles/experiment tests/pericles/test_eventlog.py tests/pericles/test_rundir.py
git commit -m "feat(experiment): transactional event log and run directory with snapshots"
```

---

### Task 10: Run loop, crash-safe resume, closing M1a

**Files:**
- Create: `src/pericles/experiment/runner.py`
- Modify: `docs/requirements/sim.md` (statuses), `README.md` (status line)
- Test: `tests/pericles/test_runner.py`

**Interfaces:**
- Consumes: `Engine` (Task 8), `WorldState` (Task 8), `Intent` (Task 8), `RunDirectory` (Task 9).
- Produces:
  - `IntentSource = Callable[[WorldState], Sequence[Intent]]` (must be a pure function of the state)
  - `run(run_dir: RunDirectory, engine: Engine, state: WorldState, source: IntentSource, until_tick: int, snapshot_every: int) -> WorldState`: saves a snapshot of the start state if its tick is a multiple of `snapshot_every` and none exists for it. Then it loops until `state.tick == until_tick`: get intents, step, append the tick's events, and snapshot whenever `state.tick % snapshot_every == 0`.
  - `resume(run_dir: RunDirectory) -> WorldState`: loads the latest snapshot, truncates the log to ticks `< snapshot tick`, and returns the state. Raises `RunDirectoryError` if there is no snapshot.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_runner.py`:

```python
from collections.abc import Sequence
from pathlib import Path

import pytest

from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo
from pericles.core.mapgen import TileMap
from pericles.core.state import Villager, WorldState
from pericles.experiment.rundir import RunDirectory, RunDirectoryError
from pericles.experiment.runner import IntentSource, resume, run

pytestmark = pytest.mark.req("REQ-EXP-003")


def initial(small_map: TileMap, registry: Registry) -> tuple[WorldState, list[Coord]]:
    walkable = [
        Coord(x, y)
        for y in range(small_map.height)
        for x in range(small_map.width)
        if registry.terrains[small_map.terrain_at(Coord(x, y))].walkable
    ]
    start = small_map.start()
    villagers = [Villager(f"v{i}", f"V{i}", start) for i in range(4)]
    return WorldState.new(4, small_map, villagers), walkable


def source_for(walkable: list[Coord]) -> IntentSource:
    def source(state: WorldState) -> Sequence[Intent]:
        if state.tick % 7 != 0:
            return []
        return [MoveTo(v, walkable[(state.tick * 13 + i * 17) % len(walkable)])
                for i, v in enumerate(sorted(state.villagers))]

    return source


def test_run_writes_events_and_snapshots(tmp_path: Path, registry: Registry, small_map: TileMap) -> None:
    """AC1/AC2: a run fills the event log tick by tick and snapshots periodically."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    final = run(run_dir, Engine(registry), state, source_for(walkable), until_tick=25, snapshot_every=10)
    assert final.tick == 25
    assert run_dir.event_log.last_tick() == 24
    assert run_dir.snapshot_ticks() == [0, 10, 20]
    assert any(e.kind == "moved" for e in run_dir.event_log.events())
    run_dir.close()


def test_resume_after_crash_matches_uninterrupted_run(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC3: a run resumes from its last snapshot after a crash, with identical results."""
    state, walkable = initial(small_map, registry)
    source = source_for(walkable)
    clean = RunDirectory.create(tmp_path / "clean", {}, seed=4)
    clean_final = run(clean, Engine(registry), state, source, until_tick=50, snapshot_every=10)

    state2, _ = initial(small_map, registry)
    crashing = RunDirectory.create(tmp_path / "crash", {}, seed=4)

    def exploding(s: WorldState) -> Sequence[Intent]:
        if s.tick == 37:
            raise RuntimeError("power cut")
        return source(s)

    with pytest.raises(RuntimeError, match="power cut"):
        run(crashing, Engine(registry), state2, exploding, until_tick=50, snapshot_every=10)
    assert crashing.event_log.last_tick() == 36
    crashing.close()

    reopened = RunDirectory.open(tmp_path / "crash")
    resumed = resume(reopened)
    assert resumed.tick == 30
    assert reopened.event_log.last_tick() == 29
    final = run(reopened, Engine(registry), resumed, source, until_tick=50, snapshot_every=10)
    assert final.digest() == clean_final.digest()
    assert reopened.event_log.digest() == clean.event_log.digest()
    clean.close()
    reopened.close()


def test_failed_event_write_leaves_no_partial_tick(
    tmp_path: Path, registry: Registry, small_map: TileMap, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2/AC3: a crash while writing a tick loses at most that tick."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=4)
    log = run_dir.event_log
    original = log.append_tick

    def failing(tick: int, events: Sequence[Event]) -> None:
        if tick == 12:
            raise OSError("disk full")
        original(tick, events)

    monkeypatch.setattr(log, "append_tick", failing)
    with pytest.raises(OSError, match="disk full"):
        run(run_dir, Engine(registry), state, source_for(walkable), until_tick=20, snapshot_every=10)
    assert log.last_tick() == 11
    assert run_dir.snapshot_ticks() == [0, 10]
    run_dir.close()


def test_resume_without_snapshot_fails(tmp_path: Path) -> None:
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=1)
    with pytest.raises(RunDirectoryError, match="no snapshot"):
        resume(run_dir)
    run_dir.close()


def test_run_rejects_bad_arguments(tmp_path: Path, registry: Registry, small_map: TileMap) -> None:
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=4)
    with pytest.raises(ValueError, match="snapshot_every"):
        run(run_dir, Engine(registry), state, source_for(walkable), until_tick=5, snapshot_every=0)
    with pytest.raises(ValueError, match="until_tick"):
        run(run_dir, Engine(registry), state, source_for(walkable), until_tick=-1, snapshot_every=5)
    run_dir.close()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/pericles/test_runner.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.experiment.runner'`

- [ ] **Step 3: Implement `src/pericles/experiment/runner.py`**

```python
"""Drive the engine, persist each tick, snapshot, and resume after crashes (REQ-EXP-003)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pericles.core.engine import Engine
from pericles.core.intents import Intent
from pericles.core.state import WorldState
from pericles.experiment.rundir import RunDirectory, RunDirectoryError

IntentSource = Callable[[WorldState], Sequence[Intent]]


def run(
    run_dir: RunDirectory,
    engine: Engine,
    state: WorldState,
    source: IntentSource,
    until_tick: int,
    snapshot_every: int,
) -> WorldState:
    if snapshot_every < 1:
        raise ValueError("snapshot_every must be at least 1")
    if until_tick < state.tick:
        raise ValueError(f"until_tick {until_tick} is before the current tick {state.tick}")
    log = run_dir.event_log
    if state.tick % snapshot_every == 0 and state.tick not in run_dir.snapshot_ticks():
        run_dir.save_snapshot(state)
    while state.tick < until_tick:
        intents = source(state)
        state, events = engine.step(state, intents)
        log.append_tick(state.tick - 1, events)
        if state.tick % snapshot_every == 0:
            run_dir.save_snapshot(state)
    return state


def resume(run_dir: RunDirectory) -> WorldState:
    snapshot = run_dir.latest_snapshot()
    if snapshot is None:
        raise RunDirectoryError(f"{run_dir.path}: no snapshot to resume from")
    state = WorldState.from_dict(snapshot)
    run_dir.event_log.truncate_after(state.tick - 1)
    return state
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass.

- [ ] **Step 5: Update requirement statuses and README**

In `docs/requirements/sim.md` change `Must · M1 · Accepted` to `Must · M1 · Implemented` for **REQ-SIM-001, REQ-SIM-002, REQ-SIM-005, REQ-SIM-006** only. Their acceptance criteria are now all covered by tests. Leave REQ-SIM-003, REQ-SIM-004 and REQ-EXP-003 as Accepted: their remaining ACs arrive in M1b (winter effects, buildings) and M4 (metrics).

In `README.md`, change the status line to `Status: M1a Engine kernel complete; M1b Gameplay next.`

- [ ] **Step 6: Run every gate**

```bash
uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check . \
  && PYTHONPATH=tools uv run python -m pericles_tools.traceability check \
  && PYTHONPATH=tools uv run python -m pericles_tools.adr check \
  && rm -rf mutants && PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run
```

Expected: everything passes. Traceability: no errors. The mutation gate prints `pericles.core: ≥80.0% …` and exits 0. If the core score is below 80%, read `uv run mutmut results --all true`, add tests for the surviving mutants in the module they belong to, and re-run. Never lower the threshold.

- [ ] **Step 7: Commit, push, open the PR**

```bash
git add src/pericles/experiment/runner.py tests/pericles/test_runner.py docs/requirements/sim.md README.md
git commit -m "feat(experiment): run loop with snapshots and crash-safe resume; close M1a"
git push -u origin m1a-engine-kernel
gh pr create --base main --title "M1a Engine kernel" --body "Implements docs/superpowers/plans/2026-11-22-m1a-engine-kernel.md"
gh pr checks --watch
```

Expected: all checks green, including `mutation` (core ≥ 80%). After the merge, close the GitHub issues for REQ-SIM-001, -002, -005 and -006 with a comment referencing the PR.
