# M1d Running Villages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close milestone M1 with villages that run on their own. Scripted villagers survive, build, pair up and grow. A village is described in an `experiment.yaml` and runs headless from the command line. Runs survive crashes, write daily metrics, and meet the speed target.

**Architecture:**
- **Agent layer.** A new `pericles.agents` layer holds a `Controller`. Each tick it asks a *mind* for a decision for every villager that is *due*: idle, or with an urgent need.
- **Scripted minds.** The scripted minds are utility AIs built from small rules, one rule per concern (eat, sleep, shelter, couple, home, deliver, deposit, build, work), and the first rule that fires decides. A rule reads the world through a read-only `View`.
- **Memory and snapshots.** The controller remembers a little per villager: the last target, the job, an idle-until tick and targets to avoid. That memory is saved in every snapshot, so a resumed run continues exactly as an uninterrupted one would.
- **Experiment layer.** `pericles.experiment` loads `experiment.yaml`, builds the world, drives the engine and controller, writes the run directory durably, and computes daily metrics from the config and the event log with `pericles.analysis`.

**Tech Stack:** Python 3.12+, uv, pydantic v2, PyYAML, pyarrow (new; Parquet metrics), pytest, Hypothesis, mypy strict, ruff, mutmut.

**Spec:** `docs/superpowers/specs/2026-11-22-pericles-design.md` (§3, §4.4, §5.5, §7, §8). Requirements: `docs/requirements/agt.md`, `sim.md`, `exp.md`, `nfr.md`. Decisions: ADR-0001, ADR-0004, ADR-0013, ADR-0014, ADR-0015, and the new ADR-0016 written in Task 1.

**User decisions (2026-11-24):**
- The scripted AI is a *village builder*. It eats, sleeps and shelters, gathers by skill, stocks a communal store, builds houses and a storehouse, moves in and forms couples. It is the baseline the LLM experiments will be compared with.
- Metrics go to `metrics.parquet`, and pyarrow is added now.
- REQ-NFR-003 is checked by an opt-in `perf` test and a bench tool, run on the user's Mac and not in CI.

**Requirements in scope:**

| Requirement | In this plan |
|---|---|
| REQ-AGT-008 | All. AC2's "LLM fallback" is the controller's fallback path: a mind that raises `MindFailure` falls back to the scripted mind. M2 plugs the LLM mind into it. |
| REQ-SIM-016 AC1 | Children run on the scripted child mind (stay near a parent, eat, light gathering) and never reach a model mind |
| REQ-EXP-003 | All. Run directory with config snapshot, events, durable snapshots carrying agent memory, `llm_cache/`, `metrics.parquet`, `meta.json`; resume after a crash, falling back past corrupt snapshots |
| REQ-NFR-003 | All: ≥ 1000 ticks/s, 150 scripted villagers, 128×128 map, measured on the user's Mac |
| REQ-EXP-001 | Partly (it is an M4 requirement). `experiment.yaml` covers seed, map, packs, population, engine and agent parameters, with errors that name the field. Initial laws and interventions come in M3/M4. |

When this plan is done, every M1 requirement is Implemented and M1 is marked done in `docs/requirements/milestones.md`.

---

## Global Constraints

- **Branch.** Work on `m1d-running-villages`, which the plan commit creates from `main`. Land it through a PR to `main`.
- **Layering.**
  - `pericles.core` imports nothing from `pericles.agents`, `pericles.llm`, `pericles.experiment`, `pericles.server` or `pericles.analysis`. Existing tests enforce this.
  - `pericles.agents` imports from `pericles.core` only (and `pericles.llm` from M2), and never imports `random`, `time`, `datetime`, `uuid` or `secrets`. Task 1 adds the test for this.
  - `pericles.analysis` imports only `pericles.core.events` and the standard library.
  - `pericles.experiment` may import from all three.
- **Determinism.**
  - Agents use no randomness. Ties break on ids or coordinates.
  - Iterate dicts and sets in sorted order wherever the order affects a decision.
  - The controller decides for villagers in sorted id order.
  - Given the same world state and controller memory, `Controller.intents` returns the same list.
- **No magic values** (the user's rule, 2026-11-23). Every parameter is settable from a file:
  - Engine parameters are `EngineConfig` fields (`engine:` section).
  - Agent parameters are `AgentConfig` fields (`agents:` section).
  - Game values are content-pack YAML.
  - Code in `pericles.core` and `pericles.agents` holds no numeric literal other than `0`, `1` and the allowlists in `tests/pericles/test_core_boundaries.py`, which Task 1 extends to agents.
  - Any new parameter goes into its config class **and** into `src/pericles/experiment/default_settings.yaml`. Tests check that the file lists every field.
- **Content ids.** Neither the agents nor core contain base-pack content ids. Buildings the scripted AI builds are named in `AgentConfig` (`house_building`, `store_building`). Food is any item with `nutrition > 0`. Jobs are node actions. Needs are found by their `relief` kind (`eat`, `sleep`, `shelter`), which is a schema literal, not a content id.
- **Item conservation** (ADR-0014 §4) and the engine tick order (ADR-0015 §12) are unchanged. The agents only submit intents.
- **Tests.**
  - Every test for a requirement carries `@pytest.mark.req("REQ-…")` (literal ids) and names the AC in its docstring.
  - Product tests live in `tests/pericles/`. Tests for the tools live in `tests/tools/`.
  - Tests that need the world use the session `registry` fixture (the base pack) and the `make_world(rows, villagers, nodes)` fixture from `tests/pericles/conftest.py`, where `.` is grass, `~` water and `T` forest.
- **Mutation scores.** `pericles.core` must stay ≥ 80% and `pericles.agents` ≥ 70%. Each task mutates its own modules and adds tests for survivors. `# pragma: no mutate` is allowed only on a line where every possible mutant is equivalent, with the per-mutant reason given in the report.
- **Gates before every commit**, in order. Never hide a gate's exit code behind a pipe.
  1. `uv run ruff format .`
  2. `uv run pytest -q`
  3. `uv run mypy`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `PYTHONPATH=tools uv run python -m pericles_tools.traceability check`
- **Commit messages** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Stuck villagers.**
   - Cases: the target is unreachable (walled in, across water), the node is depleted on arrival, the store is full, the house is full, a site cannot be placed, or a proposal has expired.
   - Expected: each rejection or failed move makes the villager avoid that target for `avoid_ticks`. A rejection with no target, or a `Wait`, sets the villager idle for `idle_ticks`. No villager repeats the same rejected intent every tick, and no villager is re-sent the intent it is already carrying out (that would restart its work and it would never finish).
   - Tests: Task 3 (avoid, idle, redundancy), and Task 12's property test.
2. **Resume equals no crash.**
   - Case: a run stops at any tick and is resumed from the last snapshot.
   - Expected: the event log after resuming matches, event for event, the log of a run that never stopped. This holds for agent memory too, because it lives in the snapshot.
   - Tests: Task 8.
3. **Damaged run directories.**
   - Cases: the newest snapshot is truncated or not JSON, its tick does not match its file name, or the event log is behind it (a crash between the log write and the snapshot write).
   - Expected: resume falls back to the newest usable snapshot that the log covers, truncates the log to it, and says which files it skipped. With no usable snapshot it raises `RunDirectoryError`, never a raw exception.
   - Tests: Task 8.
4. **Experiment-file errors.**
   - Cases: an unknown key, a wrong type, a missing section, an unknown pack path, terrain, trait, item, skill or building, a duplicate villager id, a starting inventory over the carry limit, and bad map shares.
   - Expected: an `ExperimentError` whose message starts with the dotted field path (`population[2].traits[0]: …`), never a raw `KeyError`, `TypeError` or pydantic error.
   - Tests: Task 9.
5. **Winter and scarcity.**
   - Cases: a village with no house when winter comes; food running out; every villager dying.
   - Expected:
     - Homeless villagers place, supply and build a communal house before cold kills them.
     - Hungry villagers eat from their inventory, then from stores, then gather.
     - A run whose population reaches zero stops early, and the CLI reports the day the village died out.
   - Tests: Tasks 6 and 10.

---

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `docs/adr/0016-agent-layer-and-runs.md` | Controller, minds, scripted rules, memory in snapshots, experiment file, metrics, durability, performance check | 1 |
| `src/pericles/agents/config.py` | `AgentConfig`: every scripted-behaviour parameter | 1 |
| `src/pericles/experiment/settings.py` | `agents:` section; `agent_config_from_mapping`, `load_agent_settings` | 1 |
| `src/pericles/experiment/default_settings.yaml` | Adds the `agents:` section | 1 |
| `src/pericles/experiment/defaults.py` | `default_agent_config`, `default_settings_mapping` | 1 |
| `tests/pericles/test_core_boundaries.py` | Agent import rules and no-magic-numbers for agents | 1 |
| `src/pericles/agents/view.py` | `Memory`, `Decision`, `NodeIndex`, `View` (read-only queries) | 2 |
| `src/pericles/agents/controller.py` | `Mind`, `MindFailure`, `Controller` (due villagers, dispatch, fallback, memory) | 3 |
| `src/pericles/agents/rules.py` | The rules: eat, sleep, shelter, deliver, deposit, work, build, home, couple, follow, forage | 4–7 |
| `src/pericles/agents/scripted.py` | `ScriptedMind`, `ChildMind`, `scripted_controller` | 4–7 |
| `src/pericles/experiment/rundir.py` | Snapshots carry agent memory, fsync, corrupt-snapshot fallback, Parquet metrics | 8, 10 |
| `src/pericles/experiment/runner.py` | `Agents` protocol, `run`, `resume` with the log-behind check | 8 |
| `src/pericles/core/mapgen.py` | `_validate` renamed to public `validate` | 9 |
| `src/pericles/experiment/config.py` | `experiment.yaml` → `Experiment`; `build_world` | 9 |
| `experiments/baseline.yaml` | The all-scripted baseline village | 9 |
| `src/pericles/analysis/metrics.py` | Daily survival metrics from the config and event log | 10 |
| `src/pericles/experiment/launch.py` | Start, continue and advance a run directory | 10 |
| `src/pericles/experiment/cli.py` | `pericles run`, `pericles resume` | 10 |
| `src/pericles/core/calendar.py`, `life.py`, `context.py` | Per-tick need-rate and season caching | 11 |
| `tools/pericles_tools/bench.py` | Ticks/s benchmark with an optional profile | 11 |
| `tests/pericles/test_perf.py` | The opt-in REQ-NFR-003 test | 11 |
| `docs/requirements/*.md`, `README.md` | Statuses, M1 done, traceability matrix | 12 |

---

### Task 1: ADR-0016, agent settings, and the agent boundary rules

**Files:**
- Create: `docs/adr/0016-agent-layer-and-runs.md`
- Modify: `docs/adr/README.md` (index row)
- Create: `src/pericles/agents/config.py`
- Modify: `src/pericles/experiment/settings.py`, `src/pericles/experiment/defaults.py`, `src/pericles/experiment/default_settings.yaml`
- Test: `tests/pericles/test_agent_config.py`, `tests/pericles/test_settings.py`, `tests/pericles/test_core_boundaries.py`

**Interfaces:**
- Produces:
  - `pericles.agents.config.AgentConfig` (frozen dataclass, fields below).
  - `RELIEFS = ("eat", "sleep", "shelter")`.
  - `pericles.experiment.settings.agent_config_from_mapping(data: object, where: str = "agents") -> AgentConfig`.
  - `load_agent_settings(path: Path) -> AgentConfig`.
  - `SECTIONS = ("engine", "agents")`.
  - `pericles.experiment.defaults.default_agent_config(**overrides) -> AgentConfig`.
  - `default_settings_mapping() -> dict[str, Any]`, the raw packaged settings file.

- [ ] **Step 1: Write ADR-0016**

Create `docs/adr/0016-agent-layer-and-runs.md`:

```markdown
# ADR-0016: Agent layer, scripted villagers and running villages

- **Status:** Accepted
- **Date:** 2026-11-24
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

M1d closes milestone M1: villages that run on their own (REQ-AGT-008, REQ-SIM-016 AC1, REQ-EXP-003, REQ-NFR-003, part of REQ-EXP-001). The spec (§3.1, §5.5) puts minds, the executor and the scripted child and fallback behaviour in `pericles.agents`. The engine only accepts intents. On 2026-11-24 the user chose a "village builder" scripted AI as the baseline for later LLM experiments, Parquet metrics, and an opt-in performance test.

## Decision

1. **Controller and minds.**
   - A `Controller` turns world state into intents once per tick, before `Engine.step`.
   - A *mind* has one method, `decide(view, villager) -> Decision | None`. A `Decision` holds the intent, the target it is about (a node, building, villager or placement claim) and the job (an action id) if any.
   - Children always use the child mind.
   - An adult uses the mind registered for its `model`. With no mind registered, or `model` unset, it uses the scripted mind.
   - A mind that raises `MindFailure` falls back to the scripted mind, and the controller counts the fallback (REQ-AGT-008 AC2). The M2 LLM mind plugs in here.
2. **Due villagers and memory.**
   - The controller asks for a decision only for a *due* villager: one with no activity, no path and no idle time left, or one whose need level reaches its `urgent_at` level.
   - The controller never sends an intent that repeats what the villager is already doing. Examples are a `MoveTo` to the end of its current path, or a `StartAction` for its current action and target. Such an intent would restart the work.
   - Per villager it remembers:
     - `target` and `job` of the last decision.
     - `idle_until`, set after a `Wait` or a rejection with no target.
     - `avoid`, mapping a target to a tick. A rejected intent or failed move adds the decision's target here for `avoid_ticks`.
   - This memory is part of every snapshot.
3. **Scripted decisions are stateless rules over a read-only `View`.**
   - Each rule looks at the world and the controller memory and returns a decision or nothing. The first rule that fires wins.
   - Adult order: eat → sleep → shelter → couple → home → deliver → deposit → build → work → wait.
   - Child order: eat (inventory or store only) → sleep → shelter → follow a parent → deposit → forage near the parent → wait.
   - Needs are found by their `relief` kind. Thresholds are `act_at[relief]` and `urgent_at[relief]`.
   - The `View` keeps a grid index of nodes by kind, because nodes never move, and caches its per-tick queries.
4. **The village plan is derived, not stored.**
   - **Food demand** is the shortfall of the village's total nutrition below `food_reserve_per_capita` × population, as a fraction.
   - **Material demand** is 1 for every item an unfinished site still needs.
   - **Choosing a job.** A villager takes the doable node action with the highest `demand / (1 + others on that output) × (1 + skill_weight × skill / max_skill)`. Ties go to the action id. The villager then goes to the nearest unavoided node with stock.
   - **Houses.** When homeless villagers outnumber free communal housing plus the housing of open house sites, one villager places a communal `house_building`.
   - **Storehouse.** When communal storage is below `storage_per_capita` × population, one villager places a communal `store_building`.
   - At most one villager claims each placement, recorded as target `place:<kind>`.
   - Sites are supplied by whoever carries what they need. Up to `max_builders` villagers build each site once its materials are in.
   - **Couples.** Unpartnered adults of a compatible sex (exactly one of the pair has `bearing_sex`) propose to the nearest free candidate and accept proposals made to them.
   - **Homes.** Homeless villagers, and partners living apart, move into a house with room, preferring the partner's.
5. **Experiment file.**
   - `experiment.yaml` has the sections `seed`, `packs`, `map`, `population`, `run`, `engine` and `agents`.
   - `engine` and `agents` override the packaged `default_settings.yaml` key by key. A given `calendar` replaces the default calendar whole.
   - The run directory's `config.yaml` is the *resolved* experiment: every engine and agent value, with absolute pack paths. A run can be continued from its directory alone.
   - Villagers start on the walkable start-area tiles nearest the map centre, born `age_days` before tick 0.
6. **Metrics come from the config and the event log only** (ADR-0004).
   - `pericles.analysis.metrics.daily_survival` produces one row per day and metric: population, adults, children, births, deaths, deaths by cause, and food eaten.
   - The rows go to `metrics.parquet` in long format, with columns `day`, `metric` and `value`.
   - Metrics are recomputed from the whole log at the end of every run or resume, so they never drift from it.
7. **Durable run directories.**
   - Snapshots are written to a temporary file, fsynced, renamed, and the directory fsynced.
   - A snapshot holds `{"world": …, "agents": …}`.
   - Resume walks snapshots newest first. It skips files that do not parse or whose tick does not match their name, and snapshots ahead of the event log. It restores the first usable one and truncates the log to it.
   - The run-directory schema version becomes 3.
8. **Performance.** REQ-NFR-003 is checked by `tests/pericles/test_perf.py`, marked `perf` and excluded by default like `slow`, and by `pericles_tools.bench`. Both run on the user's Mac, not in CI. Optimisations must leave the event digest of a pinned scripted run unchanged.

## Consequences

- Scripted villagers make no random choices, so similar villagers in similar places choose alike. Demand-weighted job choice and the "others on this output" term spread them across jobs.
- Agent memory adds a small, versioned part to snapshots. Old run directories (schema 2) are rejected with a version error.
- `pericles.analysis` depends only on the event schema, so the M4 analysis can read any run directory without the engine.
- The scripted village does not farm, craft or research in M1d. Those rules can be added as more rules later without changing the controller.
```

Add the index row to `docs/adr/README.md` after the ADR-0015 row, in the same table format:

```markdown
| [0016](0016-agent-layer-and-runs.md) | Agent layer, scripted villagers and running villages | Accepted |
```

Run: `PYTHONPATH=tools uv run python -m pericles_tools.adr check`
Expected: exit 0.

- [ ] **Step 2: Write the failing AgentConfig tests**

Create `tests/pericles/test_agent_config.py`:

```python
import dataclasses

import pytest

from pericles.agents.config import RELIEFS, AgentConfig


@pytest.mark.req("REQ-AGT-008")
def test_defaults_are_valid_and_cover_every_relief() -> None:
    """AC1: the scripted thresholds name a level for eating, sleeping and shelter."""
    config = AgentConfig()
    assert set(config.act_at) == set(RELIEFS) == set(config.urgent_at)
    assert all(config.act_at[r] <= config.urgent_at[r] for r in RELIEFS)


@pytest.mark.req("REQ-AGT-008")
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"act_at": {"eat": 50.0, "sleep": 70.0}}, "act_at and urgent_at"),
        ({"urgent_at": {"eat": 40.0, "sleep": 90.0, "shelter": 80.0}}, "act_at <= urgent_at"),
        ({"act_at": {"eat": 0.0, "sleep": 70.0, "shelter": 60.0}}, "levels must be in (0, 100]"),
        ({"act_at": {"eat": 50.0, "sleep": 70.0, "shelter": float("nan")}}, "finite"),
        ({"warm_until": 70.0}, "warm_until"),
        ({"deposit_load": 0.0}, "deposit_load"),
        ({"deposit_load": 1.5}, "deposit_load"),
        ({"food_carry": -1.0}, "must be non-negative"),
        ({"food_reserve_per_capita": -1.0}, "must be non-negative"),
        ({"storage_per_capita": -1.0}, "must be non-negative"),
        ({"skill_weight": -1.0}, "must be non-negative"),
        ({"site_search_radius": -1}, "must be non-negative"),
        ({"site_gap": -1}, "must be non-negative"),
        ({"node_search_radius": -1}, "must be non-negative"),
        ({"child_follow_radius": -1}, "must be non-negative"),
        ({"index_cell": 0}, "must be positive"),
        ({"avoid_ticks": 0}, "must be positive"),
        ({"idle_ticks": 0}, "must be positive"),
        ({"max_builders": 0}, "must be positive"),
        ({"house_building": ""}, "building ids must be non-empty"),
        ({"store_building": ""}, "building ids must be non-empty"),
    ],
)
def test_bad_values_are_rejected(overrides: dict[str, object], message: str) -> None:
    """AC1: nonsensical scripted-behaviour parameters fail at construction."""
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        dataclasses.replace(AgentConfig(), **overrides)  # type: ignore[arg-type]
```

Run: `uv run pytest tests/pericles/test_agent_config.py -q`
Expected: FAIL. `ModuleNotFoundError: No module named 'pericles.agents.config'`.

- [ ] **Step 3: Implement AgentConfig**

Create `src/pericles/agents/config.py`:

```python
"""Scripted-behaviour parameters (ADR-0016). Every field is settable from a settings file."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

RELIEFS = ("eat", "sleep", "shelter")
MAX_LEVEL = 100.0


def _act_at() -> dict[str, float]:
    return {"eat": 50.0, "sleep": 75.0, "shelter": 60.0}


def _urgent_at() -> dict[str, float]:
    return {"eat": 85.0, "sleep": 95.0, "shelter": 85.0}


@dataclass(frozen=True)
class AgentConfig:
    # Need levels at which a villager acts, and at which it drops its work (ADR-0016 §2-§3)
    act_at: dict[str, float] = field(default_factory=_act_at)
    urgent_at: dict[str, float] = field(default_factory=_urgent_at)
    warm_until: float = 10.0
    # Carrying and stocking (ADR-0016 §4)
    food_carry: float = 60.0
    deposit_load: float = 0.7
    food_reserve_per_capita: float = 60.0
    storage_per_capita: float = 15.0
    skill_weight: float = 1.0
    # Building
    house_building: str = "house"
    store_building: str = "storehouse"
    site_search_radius: int = 12
    site_gap: int = 1
    max_builders: int = 3
    # Searching and pacing
    node_search_radius: int = 48
    index_cell: int = 8
    avoid_ticks: int = 240
    idle_ticks: int = 15
    # Children and couples
    child_follow_radius: int = 4
    couples: bool = True

    def __post_init__(self) -> None:
        problems = _problems(self)
        if problems:
            raise ValueError("; ".join(problems))


def _problems(c: AgentConfig) -> list[str]:
    if set(c.act_at) != set(RELIEFS) or set(c.urgent_at) != set(RELIEFS):
        return [f"act_at and urgent_at must give a level for each of {RELIEFS}"]
    levels = [*c.act_at.values(), *c.urgent_at.values()]
    reals = [
        *levels,
        c.warm_until,
        c.food_carry,
        c.deposit_load,
        c.food_reserve_per_capita,
        c.storage_per_capita,
        c.skill_weight,
    ]
    if not all(math.isfinite(v) for v in reals):
        return ["numeric parameters must be finite"]
    non_negative = (
        c.food_carry,
        c.food_reserve_per_capita,
        c.storage_per_capita,
        c.skill_weight,
        c.site_search_radius,
        c.site_gap,
        c.node_search_radius,
        c.child_follow_radius,
    )
    positive = (c.index_cell, c.avoid_ticks, c.idle_ticks, c.max_builders)
    checks = [
        (all(0 < v <= MAX_LEVEL for v in levels), "levels must be in (0, 100]"),
        (all(c.act_at[r] <= c.urgent_at[r] for r in RELIEFS), "need act_at <= urgent_at"),
        (0 <= c.warm_until < c.act_at["shelter"], "warm_until must be in [0, act_at.shelter)"),
        (0 < c.deposit_load <= 1, "deposit_load must be in (0, 1]"),
        (all(v >= 0 for v in non_negative), "amounts, weights and radii must be non-negative"),
        (all(v > 0 for v in positive), "cells, tick counts and builder limits must be positive"),
        (bool(c.house_building and c.store_building), "building ids must be non-empty"),
    ]
    return [message for ok, message in checks if not ok]
```

The test patterns `"must be non-negative"` and `"must be positive"` match the two combined messages. `"shelter"` here is a relief kind, a schema literal, not a content id.

Run: `uv run pytest tests/pericles/test_agent_config.py -q`
Expected: PASS.

- [ ] **Step 4: Write the failing settings tests**

Append to `tests/pericles/test_settings.py`. Match the file's existing imports; add `AgentConfig`, `agent_config_from_mapping`, `load_agent_settings`, `default_agent_config`, `DEFAULT_SETTINGS` and `read_yaml` as needed:

```python
@pytest.mark.req("REQ-EXP-001")
def test_agents_section_loads_with_named_errors(tmp_path: Path) -> None:
    """AC2: the agents section is validated; errors name the field."""
    good = agent_config_from_mapping({"idle_ticks": 5, "act_at": {"eat": 40.0, "sleep": 70.0, "shelter": 60.0}})
    assert good.idle_ticks == 5 and good.act_at["eat"] == 40.0
    for data, prefix in [
        ({"idle": 5}, "agents.idle: unknown setting"),
        ({"idle_ticks": "5"}, "agents.idle_ticks:"),
        ({"idle_ticks": True}, "agents.idle_ticks:"),
        ({"act_at": [1.0]}, "agents.act_at:"),
        ({"deposit_load": 2.0}, "agents: deposit_load"),
        ([1, 2], "agents: expected a mapping"),
    ]:
        with pytest.raises(SettingsError) as caught:
            agent_config_from_mapping(data)
        assert str(caught.value).startswith(prefix), str(caught.value)


@pytest.mark.req("REQ-EXP-001")
def test_load_agent_settings_reads_the_agents_section(tmp_path: Path) -> None:
    """AC1: a settings file sets agent parameters; unknown sections are refused."""
    path = tmp_path / "s.yaml"
    path.write_text("agents:\n  idle_ticks: 7\n", encoding="utf-8")
    assert load_agent_settings(path).idle_ticks == 7
    path.write_text("agentz: {}\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="agentz: unknown section"):
        load_agent_settings(path)


@pytest.mark.req("REQ-EXP-001")
def test_default_settings_list_every_agent_parameter() -> None:
    """AC1: the packaged settings file spells out every agent parameter."""
    raw = read_yaml(DEFAULT_SETTINGS)
    assert set(raw["agents"]) == {f.name for f in dataclasses.fields(AgentConfig)}
    assert default_agent_config() == AgentConfig()
    assert default_agent_config(idle_ticks=3).idle_ticks == 3
```

Run: `uv run pytest tests/pericles/test_settings.py -q`
Expected: FAIL with an `ImportError` for `agent_config_from_mapping`.

- [ ] **Step 5: Implement the agents section**

In `src/pericles/experiment/settings.py`:
- import `AgentConfig` from `pericles.agents.config`;
- set `SECTIONS = ("engine", "agents")`;
- replace `load_settings` with the code below.

```python
def agent_config_from_mapping(data: object, where: str = "agents") -> AgentConfig:
    agents = _mapping(data, where)
    values = _values(AgentConfig, agents, where, nested=set())
    try:
        return AgentConfig(**values)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = read_yaml(path)
    except ContentError as error:
        raise SettingsError(str(error)) from None
    for key in sorted(raw):
        if key not in SECTIONS:
            raise SettingsError(f"{key}: unknown section")
    return raw


def load_settings(path: Path) -> EngineConfig:
    return engine_config_from_mapping(_read(path).get("engine", {}))


def load_agent_settings(path: Path) -> AgentConfig:
    return agent_config_from_mapping(_read(path).get("agents", {}))
```

`_values` validates `dict[str, float]` fields with `TypeAdapter(...).validate_python(value, strict=True)`. A list therefore fails with a pydantic message, which `_values` reports as `agents.act_at: …`.

In `src/pericles/experiment/defaults.py`, import `AgentConfig`, `load_agent_settings` and `read_yaml`, and add:

```python
def default_agent_config(**overrides: Any) -> AgentConfig:
    return dataclasses.replace(load_agent_settings(DEFAULT_SETTINGS), **overrides)


def default_settings_mapping() -> dict[str, Any]:
    """The packaged settings file as raw YAML data (ADR-0016 §5)."""
    return read_yaml(DEFAULT_SETTINGS)
```

Append to `src/pericles/experiment/default_settings.yaml`:

```yaml
# Scripted villagers (ADR-0016). Levels are need levels on the 0..critical scale.
agents:
  act_at: {eat: 50.0, sleep: 75.0, shelter: 60.0}
  urgent_at: {eat: 85.0, sleep: 95.0, shelter: 85.0}
  warm_until: 10.0
  food_carry: 60.0
  deposit_load: 0.7
  food_reserve_per_capita: 60.0
  storage_per_capita: 15.0
  skill_weight: 1.0
  house_building: house
  store_building: storehouse
  site_search_radius: 12
  site_gap: 1
  max_builders: 3
  node_search_radius: 48
  index_cell: 8
  avoid_ticks: 240
  idle_ticks: 15
  child_follow_radius: 4
  couples: true
```

Run: `uv run pytest tests/pericles/test_settings.py tests/pericles/test_agent_config.py -q`
Expected: PASS.

- [ ] **Step 6: Write the agent boundary tests**

In `tests/pericles/test_core_boundaries.py`:
- import `pericles.agents`;
- generalise the magic-number test so it scans both packages;
- keep the existing core test name and behaviour.

Add after the existing tests:

```python
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
            bad_package = any(name == p or name.startswith(p + ".") for p in AGENT_FORBIDDEN_PACKAGES)
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
```

Run: `uv run pytest tests/pericles/test_core_boundaries.py -q`
Expected: PASS. The agents package has only `__init__.py` and `config.py` so far, and the new tests guard the coming tasks.

To prove the guard bites, temporarily add `X = 7` to `src/pericles/agents/__init__.py`. The run should FAIL with `__init__.py:… 7 in <module>`. Then remove the line.

- [ ] **Step 7: Run the gates and commit**

Run the six gates from Global Constraints, then:

```bash
git add docs/adr src/pericles/agents src/pericles/experiment tests/pericles
git commit -m "feat(agents): ADR-0016, agent settings section and agent boundary rules

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The View — what a scripted mind may see

**Files:**
- Create: `src/pericles/agents/view.py`
- Test: `tests/pericles/test_agent_view.py`

**Interfaces:**
- Consumes: `AgentConfig` (Task 1); core `Context`, `WorldState`, `Villager`, `Node`, `Building`, `building_tiles`, `footprint`, `near`, `remaining_cost`, `blocked_tiles`, `food_stock`, `occupants`, `life.at_home`.
- Produces (in `pericles.agents.view`):
  - `PLACE = "place:"`: the prefix of placement claims.
  - `CONSTRUCT = "construct"`: the job name for building work.
  - `Memory(target: str | None = None, job: str | None = None, idle_until: int = 0, avoid: dict[str, int] = {})`, with `to_dict()` and `Memory.from_dict(data)`.
  - `Decision(intent: Intent, target: str | None = None, job: str | None = None)`, frozen.
  - `NodeIndex(nodes: Iterable[Node], cell: int)`, with `.nearest(kind: str, origin: Coord, radius: int, accept: Callable[[Node], bool]) -> Node | None`.
  - `View(ctx: Context, state: WorldState, config: AgentConfig, index: NodeIndex, memory: Mapping[str, Memory])`, with:
    - `.tick -> int`
    - `.foods -> tuple[str, ...]`: food item ids by nutrition, highest first, then id.
    - `.level(villager, relief) -> float`
    - `.avoided(villager, target) -> bool`
    - `.nearest_node(villager, kind, origin=None, radius=None) -> Node | None`
    - `.walkable(c) -> bool`
    - `.go(villager, tiles) -> MoveTo | None`
    - `.tiles(building) -> list[Coord]`
    - `.home(villager) -> Building | None`
    - `.at_home(villager) -> bool`
    - `.stores(villager) -> list[Building]`
    - `.room(building) -> int`
    - `.sites() -> list[Building]`
    - `.needed() -> Counter[str]`
    - `.population() -> int`
    - `.food_stock() -> float`
    - `.food_target() -> float`
    - `.workers(item, exclude) -> int`
    - `.builders(site_id, exclude) -> int`
    - `.house_for(villager) -> Building | None`
    - `.housing_shortfall() -> int`
    - `.storage_shortfall() -> float`
    - `.placing(kind, exclude) -> bool`
    - `.center() -> Coord`
    - `.free_origin(kind) -> Coord | None`
    - `.guardian(child) -> Villager | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_agent_view.py`:

```python
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pericles.agents.config import AgentConfig
from pericles.agents.view import Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.intents import MoveTo
from pericles.core.nodes import Node
from pericles.core.state import Pregnancy, Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 12] * 12


def view_of(registry: Registry, state: WorldState, memory: dict[str, Memory] | None = None, **cfg: object) -> View:
    config = AgentConfig(**cfg)  # type: ignore[arg-type]
    ctx = Context.build(registry, default_config())
    return View(ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), memory or {})


def building(state: WorldState, bid: str, kind: str, at: Coord, *, complete: bool = True, owner: str | None = None) -> Building:
    ownership = Ownership("personal", (owner,)) if owner else Ownership("communal")
    state.buildings[bid] = Building(bid, kind, at, ownership, complete=complete)
    return state.buildings[bid]


@given(
    st.lists(st.tuples(st.integers(0, 40), st.integers(0, 40), st.integers(0, 3)), max_size=30),
    st.integers(0, 40),
    st.integers(0, 40),
    st.integers(0, 30),
    st.integers(1, 9),
)
def test_node_index_matches_brute_force(
    spots: list[tuple[int, int, int]], ox: int, oy: int, radius: int, cell: int
) -> None:
    """AC1: the grid index finds the same nearest node (distance, then id) as a full scan."""
    nodes = [Node(f"n{i:02d}", "tree", Coord(x, y), stock) for i, (x, y, stock) in enumerate(spots)]
    origin = Coord(ox, oy)
    expected = min(
        ((origin.manhattan(n.pos), n.id) for n in nodes if n.stock > 0 and origin.manhattan(n.pos) <= radius),
        default=None,
    )
    found = NodeIndex(nodes, cell).nearest("tree", origin, radius, lambda n: n.stock > 0)
    assert (None if found is None else (origin.manhattan(found.pos), found.id)) == expected


def test_nearest_node_skips_depleted_avoided_and_far(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a mind is pointed at the nearest node it can actually use."""
    nodes = [
        Node("n0", "berry_bush", Coord(2, 0), 0),
        Node("n1", "berry_bush", Coord(3, 0), 5),
        Node("n2", "berry_bush", Coord(4, 0), 5),
        Node("n3", "berry_bush", Coord(11, 11), 5),
    ]
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a], nodes)
    memory = {"a": Memory(avoid={"n1": 10})}
    view = view_of(registry, state, memory, node_search_radius=6)
    node = view.nearest_node(a, "berry_bush")
    assert node is not None and node.id == "n2"
    state.tick = 10
    node = view_of(registry, state, memory, node_search_radius=6).nearest_node(a, "berry_bush")
    assert node is not None and node.id == "n1"
    assert view.nearest_node(a, "berry_bush", origin=Coord(11, 10), radius=1) is not None
    assert view.nearest_node(a, "boulder") is None


def test_level_takes_the_highest_need_with_that_relief(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: needs are found by their relief kind, not by content id."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": 40.0, "cold": 70.0})
    view = view_of(registry, make_world(ROWS, [a]))
    assert view.level(a, "eat") == 40.0
    assert view.level(a, "shelter") == 70.0
    assert view.level(a, "sleep") == 0.0


def test_go_targets_the_nearest_walkable_tile_next_to_the_goal(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: movement goals are reachable tiles beside water or a footprint."""
    rows = ["....", "..~~", "..~~", "...."]
    a = Villager("a", "A", Coord(0, 0))
    view = view_of(registry, make_world(rows, [a]))
    assert view.go(a, [Coord(3, 2)]) == MoveTo("a", Coord(3, 3))
    assert view.go(a, [Coord(1, 0)]) is None
    island = ["~~~", "~~~", "~~~", "..."]
    b = Villager("b", "B", Coord(0, 3))
    lost = view_of(registry, make_world(island, [b]))
    assert lost.go(b, [Coord(1, 0)]) == MoveTo("b", Coord(1, 0))


def test_food_items_rank_by_nutrition(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: food is any item with nutrition, best first."""
    view = view_of(registry, make_world(ROWS))
    assert view.foods
    assert list(view.foods) == sorted(view.foods, key=lambda i: (-registry.items[i].nutrition, i))
    assert all(registry.items[f].nutrition > 0 for f in view.foods)
    assert "wood" not in view.foods


def test_stores_are_complete_usable_and_by_distance(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a villager stores and takes only where it may, nearest first."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    building(state, "b0", "storehouse", Coord(8, 8))
    building(state, "b1", "storehouse", Coord(3, 0))
    building(state, "b2", "storehouse", Coord(1, 4), complete=False)
    building(state, "b3", "storehouse", Coord(0, 2), owner="z")
    building(state, "b4", "farm", Coord(5, 5))
    view = view_of(registry, state)
    assert [b.id for b in view.stores(a)] == ["b1", "b0"]
    assert view.room(state.buildings["b1"]) == registry.buildings["storehouse"].storage


def test_house_for_prefers_the_partner_home_and_respects_room(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: homes come from houses the villager may live in that have room."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", Coord(0, 0), sex="female", partner="b", pregnancy=Pregnancy("b", 99))
    b = Villager("b", "B", Coord(0, 0), sex="male", partner="a", home="h2")
    others = [Villager(f"o{i}", "O", Coord(0, 0), home="h1") for i in range(capacity - 1)]
    state = make_world(ROWS, [a, b, *others])
    building(state, "h1", "house", Coord(2, 2))
    building(state, "h2", "house", Coord(8, 8))
    view = view_of(registry, state)
    house = view.house_for(a)
    assert house is not None and house.id == "h2"
    b.home = None
    house = view_of(registry, state).house_for(a)
    assert house is not None and house.id == "h2"  # h1 has one bed left; a needs two
    for i in range(capacity):
        state.villagers[f"p{i}"] = Villager(f"p{i}", "P", Coord(0, 0), home="h2")
    assert view_of(registry, state).house_for(a) is None


def test_shortfalls_count_homeless_and_storage(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: the village plan counts homeless villagers against free housing, open sites included."""
    villagers = [Villager(f"v{i}", "V", Coord(0, 0)) for i in range(6)]
    state = make_world(ROWS, villagers)
    view = view_of(registry, state, storage_per_capita=10.0)
    assert view.housing_shortfall() == 6
    assert view.storage_shortfall() == 60.0
    building(state, "h1", "house", Coord(2, 2), complete=False)
    view = view_of(registry, state, storage_per_capita=10.0)
    assert view.housing_shortfall() == 6 - registry.buildings["house"].housing
    building(state, "s1", "storehouse", Coord(6, 6))
    assert view_of(registry, state, storage_per_capita=10.0).storage_shortfall() == 0.0


def test_free_origin_avoids_nodes_buildings_and_gap(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: placement looks outward from the village centre for a clear footprint."""
    rows = ["." * 9] * 9
    state = make_world(rows, nodes=[Node("n0", "berry_bush", Coord(4, 4), 5)])
    view = view_of(registry, state, site_search_radius=4, site_gap=1)
    origin = view.free_origin("house")
    assert origin is not None
    tiles = {Coord(origin.x + dx, origin.y + dy) for dx in range(2) for dy in range(2)}
    assert Coord(4, 4) not in tiles
    building(state, "b0", "house", origin)
    second = view_of(registry, state, site_search_radius=4, site_gap=1).free_origin("house")
    assert second is not None
    second_tiles = {Coord(second.x + dx, second.y + dy) for dx in range(2) for dy in range(2)}
    assert min(p.manhattan(q) for p in tiles for q in second_tiles) > 1
    tiny = make_world(["..", ".."])
    assert view_of(registry, tiny, site_search_radius=0).free_origin("storehouse") is None


def test_workers_builders_and_placing_read_memory(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: other villagers' jobs and claims spread the work."""
    a = Villager("a", "A", Coord(0, 0))
    b = Villager("b", "B", Coord(0, 0))
    state = make_world(ROWS, [a, b])
    memory = {
        "a": Memory(job="gather_berries"),
        "b": Memory(job="gather_berries", target="place:house"),
    }
    view = view_of(registry, state, memory)
    assert view.workers("berries", exclude="a") == 1
    assert view.workers("wood", exclude="a") == 0
    assert view.placing("house", exclude="a")
    assert not view.placing("house", exclude="b")
    memory["b"] = Memory(job="construct", target="s1")
    assert view_of(registry, state, memory).builders("s1", exclude="a") == 1


def test_guardian_is_the_first_living_parent(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a child follows a living parent."""
    mum = Villager("m", "M", Coord(0, 0))
    kid = Villager("k", "K", Coord(0, 0), adult=False, parents=("d", "m"))
    view = view_of(registry, make_world(ROWS, [mum, kid]))
    guardian = view.guardian(kid)
    assert guardian is not None and guardian.id == "m"
    orphan = Villager("o", "O", Coord(0, 0), adult=False, parents=("x", "y"))
    assert view.guardian(orphan) is None


def test_memory_round_trips() -> None:
    """AC1: controller memory serialises for snapshots."""
    memory = Memory(target="n1", job="fell_tree", idle_until=9, avoid={"n2": 30, "b0": 12})
    assert Memory.from_dict(memory.to_dict()) == memory
    assert list(memory.to_dict()["avoid"]) == ["b0", "n2"]
```

Run: `uv run pytest tests/pericles/test_agent_view.py -q`
Expected: FAIL. `ModuleNotFoundError: No module named 'pericles.agents.view'`.

- [ ] **Step 2: Implement the View**

Create `src/pericles/agents/view.py`:

```python
"""What a scripted mind may see: read-only queries over the world (ADR-0016 §2-§4)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pericles.agents.config import AgentConfig
from pericles.core.buildings import Building, building_tiles, footprint, near, remaining_cost
from pericles.core.construction import blocked_tiles
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo
from pericles.core.life import at_home
from pericles.core.lifecycle import food_stock, occupants
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

PLACE = "place:"
CONSTRUCT = "construct"


@dataclass
class Memory:
    """What the controller remembers about one villager between ticks (ADR-0016 §2)."""

    target: str | None = None
    job: str | None = None
    idle_until: int = 0
    avoid: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "job": self.job,
            "idle_until": self.idle_until,
            "avoid": dict(sorted(self.avoid.items())),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Memory:
        target, job = data["target"], data["job"]
        return cls(
            target=None if target is None else str(target),
            job=None if job is None else str(job),
            idle_until=int(data["idle_until"]),
            avoid={str(k): int(v) for k, v in data["avoid"].items()},
        )


@dataclass(frozen=True)
class Decision:
    intent: Intent
    target: str | None = None
    job: str | None = None


def _ring(cx: int, cy: int, r: int) -> Iterator[tuple[int, int]]:
    if r == 0:
        yield (cx, cy)
        return
    for dx in range(-r, r + 1):
        yield (cx + dx, cy - r)
        yield (cx + dx, cy + r)
    for dy in range(-r + 1, r):
        yield (cx - r, cy + dy)
        yield (cx + r, cy + dy)


class NodeIndex:
    """Nodes bucketed by kind and grid cell; nodes never move (ADR-0016 §3)."""

    def __init__(self, nodes: Iterable[Node], cell: int) -> None:
        self.cell = cell
        self._cells: dict[str, dict[tuple[int, int], list[Node]]] = {}
        for node in sorted(nodes, key=lambda n: n.id):
            bucket = self._cells.setdefault(node.kind, {})
            bucket.setdefault((node.pos.x // cell, node.pos.y // cell), []).append(node)

    def nearest(
        self, kind: str, origin: Coord, radius: int, accept: Callable[[Node], bool]
    ) -> Node | None:
        cells = self._cells.get(kind)
        if not cells:
            return None
        cx, cy = origin.x // self.cell, origin.y // self.cell
        best: Node | None = None
        best_key: tuple[int, str] | None = None
        for ring in range(radius // self.cell + 1 + 1):
            if best_key is not None and (ring - 1) * self.cell >= best_key[0]:
                break
            for key in _ring(cx, cy, ring):
                for node in cells.get(key, ()):
                    distance = origin.manhattan(node.pos)
                    if distance > radius or not accept(node):
                        continue
                    candidate = (distance, node.id)
                    if best_key is None or candidate < best_key:
                        best, best_key = node, candidate
        return best


class View:
    """Per-tick, read-only queries for minds; results are cached for the tick."""

    def __init__(
        self,
        ctx: Context,
        state: WorldState,
        config: AgentConfig,
        index: NodeIndex,
        memory: Mapping[str, Memory],
    ) -> None:
        self.ctx = ctx
        self.state = state
        self.config = config
        self.index = index
        self.memory = memory
        items = ctx.registry.items
        self.foods = tuple(
            sorted((i for i in items if items[i].nutrition > 0), key=lambda i: (-items[i].nutrition, i))
        )
        needs = ctx.registry.needs
        self._relief: dict[str, tuple[str, ...]] = {}
        for need in sorted(needs):
            relief = needs[need].relief
            if relief is not None:
                self._relief[relief] = (*self._relief.get(relief, ()), need)
        self._blocked: frozenset[Coord] | None = None
        self._needed: Counter[str] | None = None
        self._stock: float | None = None
        self._origins: dict[str, Coord | None] = {}

    @property
    def tick(self) -> int:
        return self.state.tick

    def level(self, villager: Villager, relief: str) -> float:
        return max((villager.needs.get(n, 0.0) for n in self._relief.get(relief, ())), default=0.0)

    def avoided(self, villager: Villager, target: str) -> bool:
        memory = self.memory.get(villager.id)
        return memory is not None and memory.avoid.get(target, self.tick) > self.tick

    def nearest_node(
        self, villager: Villager, kind: str, origin: Coord | None = None, radius: int | None = None
    ) -> Node | None:
        return self.index.nearest(
            kind,
            villager.pos if origin is None else origin,
            self.config.node_search_radius if radius is None else radius,
            lambda node: node.stock > 0 and not self.avoided(villager, node.id),
        )

    def _blocked_tiles(self) -> frozenset[Coord]:
        if self._blocked is None:
            self._blocked = blocked_tiles(self.ctx, self.state)
        return self._blocked

    def walkable(self, c: Coord) -> bool:
        tilemap = self.state.tilemap
        return (
            tilemap.in_bounds(c)
            and self.ctx.registry.terrains[tilemap.terrain_at(c)].walkable
            and c not in self._blocked_tiles()
        )

    def go(self, villager: Villager, tiles: Sequence[Coord]) -> MoveTo | None:
        """None if `tiles` are within reach; else a move to the nearest walkable tile by them."""
        if near(villager.pos, tiles):
            return None
        candidates = {c for t in tiles for c in (t, *t.neighbours4()) if self.walkable(c)}
        if not candidates:
            return MoveTo(villager.id, tiles[0])
        return MoveTo(villager.id, min(candidates, key=lambda c: (villager.pos.manhattan(c), c.y, c.x)))

    def tiles(self, building: Building) -> list[Coord]:
        return building_tiles(building, self.ctx.registry)

    def home(self, villager: Villager) -> Building | None:
        home = self.state.buildings.get(villager.home) if villager.home is not None else None
        return home if home is not None and home.complete else None

    def at_home(self, villager: Villager) -> bool:
        return at_home(self.ctx, self.state, villager)

    def stores(self, villager: Villager) -> list[Building]:
        registry = self.ctx.registry
        found = [
            b
            for b in self.state.buildings.values()
            if b.complete
            and registry.buildings[b.kind].storage > 0
            and b.ownership.owned_by(villager.id)
            and not self.avoided(villager, b.id)
        ]
        return sorted(found, key=lambda b: (villager.pos.manhattan(b.origin), b.id))

    def room(self, building: Building) -> int:
        capacity = self.ctx.registry.buildings[building.kind].storage
        return capacity - sum(building.storage.totals().values())

    def sites(self) -> list[Building]:
        return [self.state.buildings[b] for b in sorted(self.state.buildings) if not self.state.buildings[b].complete]

    def needed(self) -> Counter[str]:
        if self._needed is None:
            self._needed = Counter()
            for site in self.sites():
                self._needed.update(remaining_cost(site, self.ctx.registry))
        return self._needed

    def population(self) -> int:
        return len(self.state.villagers)

    def food_stock(self) -> float:
        if self._stock is None:
            self._stock = food_stock(self.ctx, self.state)
        return self._stock

    def food_target(self) -> float:
        return self.config.food_reserve_per_capita * self.population()

    def workers(self, item: str, exclude: str) -> int:
        actions = self.ctx.registry.actions
        return sum(
            1
            for vid, memory in self.memory.items()
            if vid != exclude
            and memory.job in actions
            and item in actions[memory.job].outputs
            and vid in self.state.villagers
        )

    def builders(self, site_id: str, exclude: str) -> int:
        return sum(
            1
            for vid, memory in self.memory.items()
            if vid != exclude and memory.job == CONSTRUCT and memory.target == site_id
            and vid in self.state.villagers
        )

    def placing(self, kind: str, exclude: str) -> bool:
        claim = PLACE + kind
        return any(
            vid != exclude and memory.target == claim and vid in self.state.villagers
            for vid, memory in self.memory.items()
        )

    def house_for(self, villager: Villager) -> Building | None:
        """A complete house this villager may live in with room for it, the partner's first."""
        registry = self.ctx.registry
        buildings = self.state.buildings
        partner = self.state.villagers.get(villager.partner) if villager.partner else None
        incoming = 1 + (1 if villager.pregnancy is not None else 0)

        def fits(b: Building) -> bool:
            housing = registry.buildings[b.kind].housing
            allowed = b.ownership.owned_by(villager.id) or (
                partner is not None and b.ownership.owned_by(partner.id)
            )
            room = villager.home == b.id or occupants(self.state, b.id) + incoming <= housing
            return b.complete and housing > 0 and allowed and room

        if partner is not None and partner.home in buildings and fits(buildings[partner.home]):
            return buildings[partner.home]
        options = sorted(
            (b for b in buildings.values() if fits(b)),
            key=lambda b: (villager.pos.manhattan(b.origin), b.id),
        )
        return options[0] if options else None

    def _communal(self, attribute: str, *, complete: bool) -> int:
        registry = self.ctx.registry
        return sum(
            getattr(registry.buildings[b.kind], attribute)
            for b in self.state.buildings.values()
            if b.complete == complete and b.ownership.kind == "communal"
        )

    def housing_shortfall(self) -> int:
        homeless = sum(1 for v in self.state.villagers.values() if self.home(v) is None)
        registry = self.ctx.registry
        free = sum(
            registry.buildings[b.kind].housing - occupants(self.state, b.id)
            for b in self.state.buildings.values()
            if b.complete and b.ownership.kind == "communal" and registry.buildings[b.kind].housing
        )
        building = self._communal("housing", complete=False)
        return homeless - free - building

    def storage_shortfall(self) -> float:
        storage = self._communal("storage", complete=True) + self._communal("storage", complete=False)
        return max(0.0, self.config.storage_per_capita * self.population() - storage)

    def center(self) -> Coord:
        registry = self.ctx.registry
        stores = sorted(
            (b for b in self.state.buildings.values()
             if b.complete and b.ownership.kind == "communal" and registry.buildings[b.kind].storage),
            key=lambda b: b.id,
        )
        return stores[0].origin if stores else self.state.tilemap.start()

    def free_origin(self, kind: str) -> Coord | None:
        """The clear footprint origin nearest the village centre, with `site_gap` around it."""
        if kind in self._origins:
            return self._origins[kind]
        width, height = self.ctx.registry.buildings[kind].footprint
        gap = self.config.site_gap
        taken = {t for b in self.state.buildings.values() for t in self.tiles(b)}
        nodes = {n.pos for n in self.state.nodes.values()}
        centre = self.center()
        radius = self.config.site_search_radius
        candidates = sorted(
            (Coord(centre.x + dx, centre.y + dy) for dy in range(-radius, radius + 1) for dx in range(-radius, radius + 1)),
            key=lambda c: (centre.manhattan(c), c.y, c.x),
        )
        found: Coord | None = None
        for origin in candidates:
            tiles = footprint(origin, (width, height))
            if not all(self.walkable(t) and t not in nodes for t in tiles):
                continue
            margin = footprint(Coord(origin.x - gap, origin.y - gap), (width + gap + gap, height + gap + gap))
            if any(t in taken for t in margin):
                continue
            found = origin
            break
        self._origins[kind] = found
        return found

    def guardian(self, child: Villager) -> Villager | None:
        for parent in sorted(child.parents):
            if parent in self.state.villagers:
                return self.state.villagers[parent]
        return None
```

Notes for the implementer:
- `"communal"` is an ownership kind defined by `Ownership`. It is not a content id.
- `NodeIndex.nearest` writes `+ 1 + 1` so that no literal `2` appears. The loop scans one ring past `radius // cell`, because a node at distance `radius` can sit one ring further out than `radius // cell`. The early exit is safe: the closest any node in ring `r ≥ 1` can be is `(r − 1) × cell + 1`.
- Some lines are longer than 100 characters. Let `ruff format` wrap them. Do not change any logic to make a line shorter.

Run: `uv run pytest tests/pericles/test_agent_view.py -q`
Expected: PASS.

- [ ] **Step 3: Mutation-test the module**

Run: `PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run --changed-since main`
Expected: `pericles.agents` ≥ 70%. For each surviving mutant, add a test in `test_agent_view.py` that kills it, or explain in the report why it is equivalent.

- [ ] **Step 4: Run the gates and commit**

```bash
git add src/pericles/agents/view.py tests/pericles/test_agent_view.py
git commit -m "feat(agents): read-only View with node index, memory and village queries

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The Controller — due villagers, dispatch, fallback and memory

**Files:**
- Create: `src/pericles/agents/controller.py`
- Test: `tests/pericles/test_controller.py`

**Interfaces:**
- Consumes: `AgentConfig`, `RELIEFS` (Task 1); `Memory`, `Decision`, `NodeIndex`, `View` (Task 2).
- Produces (in `pericles.agents.controller`):
  - `MindFailure(Exception)`.
  - `Mind`, a Protocol with `decide(view: View, villager: Villager) -> Decision | None`.
  - `Controller(ctx: Context, config: AgentConfig, adult: Mind, child: Mind, minds: Mapping[str, Mind] | None = None)`, with:
    - `.intents(state) -> list[Intent]`
    - `.observe(state, events: Sequence[Event]) -> None`
    - `.to_dict() -> dict[str, Any]`
    - `.load(data: Mapping[str, Any]) -> None`
    - `.memory: dict[str, Memory]`
    - `.fallbacks: int`

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_controller.py`:

```python
from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller, MindFailure
from pericles.agents.view import Decision, Memory, View
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import MoveTo, Sleep, StartAction, Wait
from pericles.core.state import Activity, Villager, WorldState
from pericles.experiment.defaults import default_config

MakeWorld = Callable[..., WorldState]
ROWS = ["." * 8] * 8
GOAL = Coord(5, 5)


class Script:
    """A stub mind: returns `make(villager)` and records who asked."""

    def __init__(self, make: Callable[[Villager], Decision | None]) -> None:
        self.make = make
        self.asked: list[str] = []

    def decide(self, view: View, villager: Villager) -> Decision | None:
        self.asked.append(villager.id)
        return self.make(villager)


class Broken:
    def decide(self, view: View, villager: Villager) -> Decision | None:
        raise MindFailure("invalid JSON twice")


def walk(v: Villager) -> Decision:
    return Decision(MoveTo(v.id, GOAL), target="goal")


def controller(registry: Registry, adult: object, child: object | None = None, **kw: object) -> Controller:
    ctx = Context.build(registry, default_config())
    return Controller(ctx, AgentConfig(), adult, child or Script(walk), **kw)  # type: ignore[arg-type]


def gathering() -> Activity:
    return Activity("action", "gather_berries", "n0", 30.0, 0.0, 1.0)


@pytest.mark.req("REQ-AGT-008")
def test_only_due_villagers_are_asked_in_id_order(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: idle villagers decide; walking or working villagers carry on."""
    state = make_world(
        ROWS,
        [
            Villager("c", "C", Coord(0, 0)),
            Villager("a", "A", Coord(0, 0)),
            Villager("b", "B", Coord(0, 0), path=[Coord(1, 0)]),
            Villager("d", "D", Coord(0, 0), activity=gathering()),
        ],
    )
    mind = Script(walk)
    intents = controller(registry, mind).intents(state)
    assert mind.asked == ["a", "c"]
    assert intents == [MoveTo("a", GOAL), MoveTo("c", GOAL)]


@pytest.mark.req("REQ-AGT-008")
def test_an_urgent_need_overrides_work(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a villager drops its work when a need reaches its urgent level."""
    urgent = AgentConfig().urgent_at["eat"]
    state = make_world(ROWS, [Villager("d", "D", Coord(0, 0), activity=gathering(), needs={"hunger": urgent})])
    mind = Script(walk)
    assert controller(registry, mind).intents(state) == [MoveTo("d", GOAL)]


@pytest.mark.req("REQ-AGT-008")
def test_redundant_intents_are_not_sent(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: re-sending the current move, action or sleep would restart it, so it is dropped."""
    hungry = {"hunger": AgentConfig().urgent_at["eat"]}
    state = make_world(
        ROWS,
        [
            Villager("a", "A", Coord(0, 0), path=[Coord(1, 0), GOAL], needs=dict(hungry)),
            Villager("b", "B", Coord(0, 0), activity=gathering(), needs=dict(hungry)),
            Villager("c", "C", Coord(0, 0), activity=Activity("sleep", "sleep", None, 0.0, 0.0, 0.0), needs=dict(hungry)),
            Villager("d", "D", Coord(0, 0), activity=gathering(), needs=dict(hungry)),
        ],
    )
    answers = {
        "a": Decision(MoveTo("a", GOAL)),
        "b": Decision(StartAction("b", "gather_berries", "n0")),
        "c": Decision(Sleep("c")),
        "d": Decision(StartAction("d", "gather_berries", "n9")),
    }
    intents = controller(registry, Script(lambda v: answers[v.id])).intents(state)
    assert intents == [StartAction("d", "gather_berries", "n9")]


@pytest.mark.req("REQ-AGT-008")
def test_wait_idles_the_villager_without_an_intent(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a waiting villager is not asked again until idle_ticks pass, unless urgent."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    mind = Script(lambda v: Decision(Wait(v.id)))
    ctl = controller(registry, mind)
    assert ctl.intents(state) == []
    assert ctl.memory["a"].idle_until == AgentConfig().idle_ticks
    state.tick = AgentConfig().idle_ticks - 1
    ctl.intents(state)
    assert mind.asked == ["a"]
    a.needs["hunger"] = AgentConfig().urgent_at["eat"]
    ctl.intents(state)
    assert mind.asked == ["a", "a"]
    state.tick = ctl.memory["a"].idle_until
    a.needs["hunger"] = 0.0
    ctl.intents(state)
    assert mind.asked == ["a", "a", "a"]


@pytest.mark.req("REQ-SIM-016")
def test_children_never_reach_a_model_mind(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: children run on the scripted child mind; no model mind is ever consulted for them."""
    kid = Villager("k", "K", Coord(0, 0), adult=False, model="llm")
    state = make_world(ROWS, [kid])
    llm, child = Script(walk), Script(walk)
    controller(registry, Script(walk), child, minds={"llm": llm}).intents(state)
    assert llm.asked == []
    assert child.asked == ["k"]


@pytest.mark.req("REQ-AGT-008")
def test_model_minds_with_scripted_fallback(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: an adult uses its model's mind; a failing mind falls back to the scripted one."""
    state = make_world(
        ROWS,
        [
            Villager("a", "A", Coord(0, 0), model="llm"),
            Villager("b", "B", Coord(0, 0), model="broken"),
            Villager("c", "C", Coord(0, 0), model="unknown"),
            Villager("d", "D", Coord(0, 0)),
        ],
    )
    llm, scripted = Script(walk), Script(walk)
    ctl = controller(registry, scripted, minds={"llm": llm, "broken": Broken()})
    ctl.intents(state)
    assert llm.asked == ["a"]
    assert scripted.asked == ["b", "c", "d"]
    assert ctl.fallbacks == 1


@pytest.mark.req("REQ-AGT-008")
def test_failures_are_avoided_or_idled(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a rejected target is avoided for avoid_ticks; a rejection without a target idles."""
    config = AgentConfig()
    state = make_world(ROWS, [Villager("a", "A", Coord(0, 0)), Villager("b", "B", Coord(0, 0))])
    ctl = controller(registry, Script(lambda v: Decision(MoveTo(v.id, GOAL), target="n7" if v.id == "a" else None)))
    ctl.intents(state)
    state.tick = 1
    ctl.observe(
        state,
        [
            Event(0, 0, "move_failed", {"actor": "a", "target": [5, 5], "reason": "no_path"}),
            Event(0, 1, "intent_rejected", {"actor": "b", "intent": "move_to", "reason": "x"}),
            Event(0, 2, "intent_rejected", {"actor": "zz", "intent": "move_to", "reason": "x"}),
        ],
    )
    assert ctl.memory["a"].avoid == {"n7": 1 + config.avoid_ticks}
    assert ctl.memory["a"].target is None
    assert ctl.memory["b"].idle_until == 1 + config.idle_ticks
    state.tick = 1 + config.avoid_ticks
    ctl.observe(state, [])
    assert ctl.memory["a"].avoid == {}


@pytest.mark.req("REQ-EXP-003")
def test_memory_round_trips_and_forgets_the_dead(registry: Registry, make_world: MakeWorld) -> None:
    """AC3: controller memory survives a snapshot; dead villagers' memory is dropped."""
    state = make_world(ROWS, [Villager("a", "A", Coord(0, 0)), Villager("b", "B", Coord(0, 0))])
    ctl = controller(registry, Script(walk))
    ctl.intents(state)
    ctl.memory["a"].avoid["n1"] = 40
    ctl.fallbacks = 2
    copy = controller(registry, Script(walk))
    copy.load(ctl.to_dict())
    assert copy.to_dict() == ctl.to_dict()
    assert copy.memory["a"] == Memory(target="goal", avoid={"n1": 40})
    copy.load({})
    assert copy.memory == {} and copy.fallbacks == 0
    del state.villagers["b"]
    ctl.intents(state)
    assert set(ctl.memory) == {"a"}
```

Run: `uv run pytest tests/pericles/test_controller.py -q`
Expected: FAIL. `ModuleNotFoundError: No module named 'pericles.agents.controller'`.

- [ ] **Step 2: Implement the Controller**

Create `src/pericles/agents/controller.py`:

```python
"""Turns world state into intents for due villagers (ADR-0016 §1-§2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pericles.agents.config import RELIEFS, AgentConfig
from pericles.agents.view import Decision, Memory, NodeIndex, View
from pericles.core.context import Context
from pericles.core.events import Event
from pericles.core.intents import Construct, Intent, MoveTo, Sleep, StartAction, Wait
from pericles.core.life import SLEEP
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

FAILURES = ("intent_rejected", "move_failed")
ACTION, CONSTRUCTION = "action", "construction"


class MindFailure(Exception):
    """A mind could not decide; the scripted mind takes over (REQ-AGT-008 AC2)."""


class Mind(Protocol):
    def decide(self, view: View, villager: Villager) -> Decision | None: ...


def _redundant(villager: Villager, intent: Intent) -> bool:
    """True if the villager is already doing what `intent` asks; sending it would restart it."""
    activity = villager.activity
    if isinstance(intent, MoveTo):
        return bool(villager.path) and villager.path[-1] == intent.target
    if activity is None:
        return False
    if isinstance(intent, StartAction):
        return activity.kind == ACTION and (activity.ident, activity.target) == (
            intent.action,
            intent.target,
        )
    if isinstance(intent, Sleep):
        return activity.kind == SLEEP
    if isinstance(intent, Construct):
        return activity.kind == CONSTRUCTION and activity.target == intent.building
    return False


class Controller:
    def __init__(
        self,
        ctx: Context,
        config: AgentConfig,
        adult: Mind,
        child: Mind,
        minds: Mapping[str, Mind] | None = None,
    ) -> None:
        self.ctx = ctx
        self.config = config
        self.adult = adult
        self.child = child
        self.minds = dict(minds or {})
        self.memory: dict[str, Memory] = {}
        self.fallbacks = 0
        self._index: tuple[dict[str, Node], NodeIndex] | None = None

    def view(self, state: WorldState) -> View:
        if self._index is None or self._index[0] is not state.nodes:
            self._index = (state.nodes, NodeIndex(state.nodes.values(), self.config.index_cell))
        return View(self.ctx, state, self.config, self._index[1], self.memory)

    def intents(self, state: WorldState) -> list[Intent]:
        self.memory = {vid: m for vid, m in self.memory.items() if vid in state.villagers}
        view = self.view(state)
        intents: list[Intent] = []
        for vid in sorted(state.villagers):
            villager = state.villagers[vid]
            memory = self.memory.setdefault(vid, Memory())
            if not self._due(view, villager, memory):
                continue
            decision = self._decide(view, villager)
            if decision is None or _redundant(villager, decision.intent):
                continue
            memory.target, memory.job = decision.target, decision.job
            if isinstance(decision.intent, Wait):
                memory.idle_until = state.tick + self.config.idle_ticks
                continue
            intents.append(decision.intent)
        return intents

    def _due(self, view: View, villager: Villager, memory: Memory) -> bool:
        if any(view.level(villager, r) >= self.config.urgent_at[r] for r in RELIEFS):
            return True
        if villager.path or villager.activity is not None:
            return False
        return view.tick >= memory.idle_until

    def _decide(self, view: View, villager: Villager) -> Decision | None:
        if not villager.adult:
            return self.child.decide(view, villager)
        mind = self.minds.get(villager.model) if villager.model is not None else None
        if mind is None:
            return self.adult.decide(view, villager)
        try:
            return mind.decide(view, villager)
        except MindFailure:
            self.fallbacks += 1
            return self.adult.decide(view, villager)

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        """Learn from the tick's failures: avoid failed targets, idle on untargeted failures."""
        for event in events:
            if event.kind not in FAILURES:
                continue
            memory = self.memory.get(str(event.data.get("actor")))
            if memory is None:
                continue
            if memory.target is not None:
                memory.avoid[memory.target] = state.tick + self.config.avoid_ticks
                memory.target = memory.job = None
            else:
                memory.idle_until = state.tick + self.config.idle_ticks
        for memory in self.memory.values():
            memory.avoid = {t: until for t, until in memory.avoid.items() if until > state.tick}

    def to_dict(self) -> dict[str, Any]:
        return {
            "fallbacks": self.fallbacks,
            "memory": {vid: self.memory[vid].to_dict() for vid in sorted(self.memory)},
        }

    def load(self, data: Mapping[str, Any]) -> None:
        self.fallbacks = int(data.get("fallbacks", 0))
        self.memory = {str(k): Memory.from_dict(v) for k, v in data.get("memory", {}).items()}
```

`"action"` and `"construction"` are the activity kinds that `pericles.core.work` and `pericles.core.construction` create. If those modules expose constants for them, import the constants instead of repeating the strings.

Run: `uv run pytest tests/pericles/test_controller.py -q`
Expected: PASS.

- [ ] **Step 3: Mutation-test, run the gates and commit**

Run the mutation gate (`--changed-since main`) and kill survivors in `test_controller.py`. Then run the six gates and commit:

```bash
git add src/pericles/agents/controller.py tests/pericles/test_controller.py
git commit -m "feat(agents): controller with due villagers, mind dispatch, fallback and memory

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Survival rules and the scripted adult mind

**Files:**
- Create: `src/pericles/agents/rules.py`, `src/pericles/agents/scripted.py`
- Test: `tests/pericles/test_scripted_survival.py`

**Interfaces:**
- Consumes: `View`, `Decision` (Task 2); `Controller` (Task 3).
- Produces:
  - In `pericles.agents.rules`:
    - `EAT, SLEEP, SHELTER` (relief names).
    - `Rule = Callable[[View, Villager], Decision | None]`.
    - `jobs(view, villager, items: Iterable[str]) -> list[ActionDef]`.
    - `skill_score(view, villager, action) -> float`.
    - `fits_output(view, villager, action) -> bool`.
    - `first_reachable(view, villager, ranked, origin=None, radius=None) -> Decision | None`.
    - `gather(view, villager, items, origin=None, radius=None) -> Decision | None`.
    - `portion(view, villager, food) -> int`.
    - `feed(view, villager) -> Decision | None`.
    - The rules `eat`, `sleep`, `shelter` and `wait`.
  - In `pericles.agents.scripted`: `ScriptedMind` with `rules: tuple[Rule, ...]` and `decide(view, villager) -> Decision`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_scripted_survival.py`:

```python
import math
from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller
from pericles.agents.scripted import ScriptedMind
from pericles.agents.view import Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import Eat, MoveTo, Sleep, StartAction, Take, Wait
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 10] * 10
CONFIG = AgentConfig()
EAT_AT, SLEEP_AT, COLD_AT = CONFIG.act_at["eat"], CONFIG.act_at["sleep"], CONFIG.act_at["shelter"]


def decide(registry: Registry, state: WorldState, vid: str = "a", memory: dict[str, Memory] | None = None):  # type: ignore[no-untyped-def]
    ctx = Context.build(registry, default_config())
    view = View(ctx, state, CONFIG, NodeIndex(state.nodes.values(), CONFIG.index_cell), memory or {})
    return ScriptedMind().decide(view, state.villagers[vid])


def store(state: WorldState, at: Coord, items: dict[str, int], registry: Registry, bid: str = "s0") -> Building:
    building = Building(bid, "storehouse", at, Ownership("communal"), complete=True)
    for item, qty in items.items():
        building.storage.add(registry, item, qty)
    state.buildings[bid] = building
    return building


def test_a_hungry_villager_eats_its_own_food_first(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: eat when hungry, from the inventory, enough to cover the hunger."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": EAT_AT + 1})
    a.inventory.add(registry, "berries", 20)
    a.inventory.add(registry, "meat", 1)
    decision = decide(registry, make_world(ROWS, [a]))
    assert decision.intent == Eat("a", "meat", 1)
    a.inventory.remove("meat", 1)
    decision = decide(registry, make_world(ROWS, [a]))
    nutrition = registry.items["berries"].nutrition
    assert decision.intent == Eat("a", "berries", math.ceil((EAT_AT + 1) / nutrition))


def test_then_from_a_store(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: with no food on hand, a hungry villager fetches food from a store it may use."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": EAT_AT})
    state = make_world(ROWS, [a])
    store(state, Coord(6, 6), {"fish": 10}, registry)
    decision = decide(registry, state)
    assert isinstance(decision.intent, MoveTo) and decision.target == "s0"
    a.pos = Coord(5, 6)
    decision = decide(registry, state)
    portion = math.ceil(CONFIG.food_carry / registry.items["fish"].nutrition)
    assert decision.intent == Take("a", "s0", "fish", portion)


def test_then_by_gathering(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: with no food anywhere, a hungry villager gathers it."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": EAT_AT})
    state = make_world(ROWS, [a], [Node("n0", "berry_bush", Coord(4, 0), 5)])
    decision = decide(registry, state)
    assert decision.intent == MoveTo("a", Coord(3, 0))
    assert (decision.target, decision.job) == ("n0", "gather_berries")
    a.pos = Coord(3, 0)
    assert decide(registry, state).intent == StartAction("a", "gather_berries", "n0")


def test_below_the_threshold_nothing_fires(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a sated, rested, warm villager with nothing to do waits."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": EAT_AT - 1, "fatigue": SLEEP_AT - 1, "cold": COLD_AT - 1})
    assert decide(registry, make_world(ROWS, [a])).intent == Wait("a")


def test_tired_villagers_sleep_at_home_if_they_can(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: sleep when tired; walk home first unless exhausted."""
    a = Villager("a", "A", Coord(0, 0), home="h0", needs={"fatigue": SLEEP_AT})
    state = make_world(ROWS, [a])
    state.buildings["h0"] = Building("h0", "house", Coord(6, 6), Ownership("communal"), complete=True)
    decision = decide(registry, state)
    assert isinstance(decision.intent, MoveTo) and decision.target == "h0"
    a.needs["fatigue"] = CONFIG.urgent_at["sleep"]
    assert decide(registry, state).intent == Sleep("a")
    a.needs["fatigue"] = SLEEP_AT
    a.home = None
    assert decide(registry, state).intent == Sleep("a")


def test_cold_villagers_go_home_and_stay_until_warm(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: shelter at home when cold, staying until below warm_until."""
    a = Villager("a", "A", Coord(0, 0), home="h0", needs={"cold": COLD_AT})
    state = make_world(ROWS, [a])
    state.buildings["h0"] = Building("h0", "house", Coord(6, 6), Ownership("communal"), complete=True)
    decision = decide(registry, state)
    assert isinstance(decision.intent, MoveTo) and decision.target == "h0"
    a.pos = Coord(5, 6)
    a.needs["cold"] = CONFIG.warm_until + 1
    assert decide(registry, state).intent == Wait("a")
    a.needs["cold"] = CONFIG.warm_until
    assert decide(registry, state).intent == Wait("a")  # nothing else to do; but not for shelter
    a.home = None
    a.needs["cold"] = COLD_AT
    assert decide(registry, state).intent == Wait("a")


def test_a_scripted_villager_stays_alive(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: left alone for a day and a half by a berry bush, a scripted villager eats and sleeps."""
    a = Villager("a", "A", Coord(1, 1), needs={"hunger": EAT_AT})
    state = make_world(ROWS, [a], [Node("n0", "berry_bush", Coord(3, 1), 20)])
    engine = Engine(registry, default_config(debug_invariants=True))
    ctl = Controller(engine.context, CONFIG, ScriptedMind(), ScriptedMind())
    kinds: set[str] = set()
    for _ in range(2000):
        state, events = engine.step(state, ctl.intents(state))
        ctl.observe(state, events)
        kinds.update(e.kind for e in events)
    assert "a" in state.villagers
    assert {"ate", "fell_asleep", "work_done"} <= kinds
    assert state.villagers["a"].needs["hunger"] < CONFIG.urgent_at["eat"]
```

The third assertion in `test_cold_villagers_go_home_and_stay_until_warm` is explained by its comment. At `warm_until` the shelter rule passes, and with nothing else to do the mind waits. The last case is a homeless cold villager: the shelter rule cannot help it (the build rule in Task 6 will), so it waits.

Run: `uv run pytest tests/pericles/test_scripted_survival.py -q`
Expected: FAIL. `ModuleNotFoundError: No module named 'pericles.agents.scripted'`.

- [ ] **Step 2: Implement the rules and the mind**

Create `src/pericles/agents/rules.py`:

```python
"""Scripted-behaviour rules: each looks at the world and decides, or passes (ADR-0016 §3-§4)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

from pericles.agents.view import Decision, View
from pericles.core.content.schema import ActionDef
from pericles.core.geometry import Coord
from pericles.core.intents import Eat, Sleep, StartAction, Take, Wait
from pericles.core.inventory import capacity_for
from pericles.core.state import Villager

EAT, SLEEP, SHELTER = "eat", "sleep", "shelter"
Rule = Callable[[View, Villager], Decision | None]


def jobs(view: View, villager: Villager, items: Iterable[str]) -> list[ActionDef]:
    """Node actions producing one of `items` that this villager can start now, by id."""
    wanted = set(items)
    config = view.ctx.config
    blocked = config.calendar.season_at(view.tick).blocked_tags
    child_tags = None if villager.adult else set(config.child_action_tags)
    found = []
    for action_id in sorted(view.ctx.registry.actions):
        action = view.ctx.registry.actions[action_id]
        requires = action.requires
        if action.location.node is None or action.location.building is not None:
            continue
        if not wanted & set(action.outputs) or action.inputs:
            continue
        if any(tag in blocked for tag in action.tags):
            continue
        if child_tags is not None and not child_tags & set(action.tags):
            continue
        if requires.tools or requires.knowledge or action.location.terrains:
            continue
        if requires.skill is not None and villager.skills.get(requires.skill, 0.0) < requires.min_skill:
            continue
        found.append(action)
    return found


def skill_score(view: View, villager: Villager, action: ActionDef) -> float:
    level = villager.skills.get(action.skill, 0.0) if action.skill is not None else 0.0
    return 1.0 + view.config.skill_weight * level / view.ctx.config.max_skill


def fits_output(view: View, villager: Villager, action: ActionDef) -> bool:
    limit = view.ctx.config.carry_limit
    registry = view.ctx.registry
    return any(capacity_for(registry, villager.inventory, item, limit) > 0 for item in action.outputs)


def first_reachable(
    view: View,
    villager: Villager,
    ranked: Sequence[ActionDef],
    origin: Coord | None = None,
    radius: int | None = None,
) -> Decision | None:
    """Go to, or start, the first ranked action with a usable node and room for its output."""
    for action in ranked:
        kind = action.location.node
        if kind is None or not fits_output(view, villager, action):
            continue
        node = view.nearest_node(villager, kind, origin, radius)
        if node is None:
            continue
        step = view.go(villager, [node.pos])
        intent = step if step is not None else StartAction(villager.id, action.id, node.id)
        return Decision(intent, target=node.id, job=action.id)
    return None


def gather(
    view: View,
    villager: Villager,
    items: Iterable[str],
    origin: Coord | None = None,
    radius: int | None = None,
) -> Decision | None:
    ranked = sorted(jobs(view, villager, items), key=lambda a: (-skill_score(view, villager, a), a.id))
    return first_reachable(view, villager, ranked, origin, radius)


def portion(view: View, villager: Villager, food: str) -> int:
    """How much of `food` to fetch: enough for `food_carry` nutrition, within the carry limit."""
    registry = view.ctx.registry
    room = capacity_for(registry, villager.inventory, food, view.ctx.config.carry_limit)
    return min(room, math.ceil(view.config.food_carry / registry.items[food].nutrition))


def feed(view: View, villager: Villager) -> Decision | None:
    """Eat from the inventory, else fetch from the nearest store holding food."""
    items = view.ctx.registry.items
    level = view.level(villager, EAT)
    for food in view.foods:
        have = villager.inventory.count(food)
        if have:
            return Decision(Eat(villager.id, food, min(have, math.ceil(level / items[food].nutrition))))
    for building in view.stores(villager):
        for food in view.foods:
            held = building.storage.count(food)
            qty = min(held, portion(view, villager, food))
            if qty <= 0:
                continue
            step = view.go(villager, view.tiles(building))
            if step is not None:
                return Decision(step, target=building.id)
            return Decision(Take(villager.id, building.id, food, qty), target=building.id)
    return None


def eat(view: View, villager: Villager) -> Decision | None:
    if view.level(villager, EAT) < view.config.act_at[EAT]:
        return None
    return feed(view, villager) or gather(view, villager, view.foods)


def sleep(view: View, villager: Villager) -> Decision | None:
    level = view.level(villager, SLEEP)
    if level < view.config.act_at[SLEEP]:
        return None
    home = view.home(villager)
    if home is not None and level < view.config.urgent_at[SLEEP] and not view.at_home(villager):
        step = view.go(villager, view.tiles(home))
        if step is not None:
            return Decision(step, target=home.id)
    return Decision(Sleep(villager.id))


def shelter(view: View, villager: Villager) -> Decision | None:
    home = view.home(villager)
    if home is None:
        return None
    level = view.level(villager, SHELTER)
    if view.at_home(villager):
        return Decision(Wait(villager.id)) if level > view.config.warm_until else None
    if level < view.config.act_at[SHELTER]:
        return None
    step = view.go(villager, view.tiles(home))
    return Decision(step, target=home.id) if step is not None else Decision(Wait(villager.id))


def wait(view: View, villager: Villager) -> Decision:
    return Decision(Wait(villager.id))
```

Create `src/pericles/agents/scripted.py`:

```python
"""The scripted minds: utility AIs built from rules (REQ-AGT-008, REQ-SIM-016 AC1; ADR-0016)."""

from __future__ import annotations

from pericles.agents import rules
from pericles.agents.rules import Rule
from pericles.agents.view import Decision, View
from pericles.core.state import Villager


class ScriptedMind:
    """Keeps an adult alive and productive; the baseline and the LLM fallback."""

    rules: tuple[Rule, ...] = (rules.eat, rules.sleep, rules.shelter)

    def decide(self, view: View, villager: Villager) -> Decision:
        for rule in self.rules:
            decision = rule(view, villager)
            if decision is not None:
                return decision
        return rules.wait(view, villager)
```

Run: `uv run pytest tests/pericles/test_scripted_survival.py -q`
Expected: PASS.

- [ ] **Step 3: Mutation-test, run the gates and commit**

Kill survivors in `test_scripted_survival.py`, then run the gates and commit:

```bash
git add src/pericles/agents tests/pericles/test_scripted_survival.py
git commit -m "feat(agents): survival rules (eat, sleep, shelter) and the scripted adult mind

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Work by skill and demand, deposit, deliver

**Files:**
- Modify: `src/pericles/agents/rules.py`, `src/pericles/agents/scripted.py`
- Test: `tests/pericles/test_scripted_work.py`

**Interfaces:**
- Consumes: Task 4's rules.
- Produces:
  - In `rules`:
    - `demand(view, item) -> float` (0..1).
    - `utility(view, villager, action) -> float`.
    - `surplus(view, villager) -> list[tuple[str, int]]`.
    - The rules `deliver`, `deposit` and `work`.
  - `ScriptedMind.rules = (eat, sleep, shelter, deliver, deposit, work)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_scripted_work.py`:

```python
from collections.abc import Callable

import pytest

from pericles.agents import rules
from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller
from pericles.agents.scripted import ScriptedMind
from pericles.agents.view import Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership, remaining_cost
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import Deliver, Deposit, MoveTo, StartAction, Wait
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 6 + "T" * 6] * 12
CONFIG = AgentConfig()


def view_of(registry: Registry, state: WorldState, memory: dict[str, Memory] | None = None, **cfg: object) -> View:
    ctx = Context.build(registry, default_config())
    config = AgentConfig(**cfg)  # type: ignore[arg-type]
    return View(ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), memory or {})


def site(state: WorldState, kind: str = "house", at: Coord = Coord(1, 8)) -> Building:
    state.buildings["s1"] = Building("s1", kind, at, Ownership("communal"))
    return state.buildings["s1"]


def storehouse(state: WorldState, at: Coord = Coord(1, 1)) -> Building:
    state.buildings["st"] = Building("st", "storehouse", at, Ownership("communal"), complete=True)
    return state.buildings["st"]


TREES = [Node(f"t{i}", "tree", Coord(7 + i, 2), 10) for i in range(3)]
BUSHES = [Node(f"b{i}", "berry_bush", Coord(2 + i, 5), 20) for i in range(2)]


def test_demand_measures_food_shortfall_and_needed_materials(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: the village wants food up to its reserve and whatever open sites still need."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    view = view_of(registry, state, food_reserve_per_capita=100.0)
    assert rules.demand(view, "berries") == 1.0
    assert rules.demand(view, "wood") == 0.0
    a.inventory.add(registry, "berries", 4)  # 60 nutrition of the 100 wanted
    site(state)
    view = view_of(registry, state, food_reserve_per_capita=100.0)
    assert rules.demand(view, "berries") == pytest.approx(0.4)
    assert rules.demand(view, "wood") == 1.0
    assert rules.demand(view, "iron") == 0.0


def test_work_follows_skill_when_demands_tie(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: work by skill: a woodcutter fells trees, a forager picks berries."""
    cutter = Villager("c", "C", Coord(5, 2), skills={"woodcutting": 60.0})
    picker = Villager("p", "P", Coord(5, 2), skills={"foraging": 60.0})
    state = make_world(ROWS, [cutter, picker], [*TREES, *BUSHES])
    site(state)
    mind = ScriptedMind()
    assert mind.decide(view_of(registry, state), cutter).job == "fell_tree"
    assert mind.decide(view_of(registry, state), picker).job == "gather_berries"


def test_work_spreads_over_outputs(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: others already on an output make it less attractive."""
    a = Villager("a", "A", Coord(5, 2))
    b = Villager("b", "B", Coord(5, 2))
    state = make_world(ROWS, [a, b], [*TREES, *BUSHES])
    site(state)
    memory = {"a": Memory(job="fell_tree")}
    decision = ScriptedMind().decide(view_of(registry, state, memory), b)
    assert decision.job == "gather_berries"


def test_work_skips_full_hands_avoided_and_depleted_nodes(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a villager never heads for a node it cannot use or an output it cannot carry."""
    a = Villager("a", "A", Coord(6, 2), skills={"woodcutting": 60.0})
    trees = [Node("t0", "tree", Coord(7, 2), 0), Node("t1", "tree", Coord(8, 2), 10), Node("t2", "tree", Coord(11, 2), 10)]
    state = make_world(ROWS, [a], trees)
    site(state)
    decision = ScriptedMind().decide(view_of(registry, state, {"a": Memory(avoid={"t1": 99})}), a)
    assert decision.target == "t2"
    a.inventory.add(registry, "iron_ore", 10)  # 30 weight: the carry limit; no site needs it
    view = view_of(registry, state, deposit_load=1.0)
    assert ScriptedMind().decide(view, a).intent == Wait("a")


def test_nothing_wanted_means_wait(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: with food stocked and no site open, there is no work to do."""
    a = Villager("a", "A", Coord(5, 2))
    a.inventory.add(registry, "berries", 10)
    state = make_world(ROWS, [a], BUSHES)
    assert ScriptedMind().decide(view_of(registry, state, food_reserve_per_capita=10.0), a).intent == Wait("a")


def test_deliver_brings_what_a_site_needs(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: carried materials go to the first site that needs them."""
    a = Villager("a", "A", Coord(5, 2))
    a.inventory.add(registry, "wood", 12)
    state = make_world(ROWS, [a])
    building = site(state)
    decision = ScriptedMind().decide(view_of(registry, state), a)
    assert isinstance(decision.intent, MoveTo) and decision.target == "s1"
    a.pos = Coord(1, 7)
    need = remaining_cost(building, registry)["wood"]
    assert ScriptedMind().decide(view_of(registry, state), a).intent == Deliver("a", "s1", "wood", need)


def test_deposit_unloads_surplus_but_keeps_food_tools_and_site_needs(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a loaded villager stocks the communal store, keeping a little food and its tools."""
    a = Villager("a", "A", Coord(2, 1))
    a.inventory.add(registry, "berries", 20)
    a.inventory.add(registry, "stone", 7)
    a.inventory.add(registry, "axe", 1)
    state = make_world(ROWS, [a])
    storehouse(state, Coord(3, 1))
    keep = int(CONFIG.food_carry // registry.items["berries"].nutrition)
    view = view_of(registry, state)
    assert rules.surplus(view, a) == [("berries", 20 - keep), ("stone", 7)]
    assert ScriptedMind().decide(view, a).intent == Deposit("a", "st", "berries", 20 - keep)
    site(state)  # the house needs stone: keep it
    assert rules.surplus(view_of(registry, state), a) == [("berries", 20 - keep)]
    light = Villager("l", "L", Coord(2, 1))
    light.inventory.add(registry, "stone", 1)
    state.villagers["l"] = light
    assert rules.deposit(view_of(registry, state), light) is None


def test_scripted_villagers_supply_a_site(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: left alone, scripted villagers gather and deliver everything a site needs."""
    villagers = [Villager(f"v{i}", "V", Coord(5, 4 + i), skills={"woodcutting": 50.0, "masonry": 50.0}) for i in range(3)]
    rows = ["." * 6 + "T" * 6] * 10 + ["." * 12, ".." + "R" * 10]
    state = make_world(rows, villagers, [*TREES, Node("r0", "boulder", Coord(4, 11), 30)])
    storehouse(state)
    building = site(state)
    engine = Engine(registry, default_config(debug_invariants=True))
    ctl = Controller(engine.context, CONFIG, ScriptedMind(), ScriptedMind())
    for _ in range(4000):
        state, events = engine.step(state, ctl.intents(state))
        ctl.observe(state, events)
        if not remaining_cost(building, registry):
            break
    assert remaining_cost(building, registry) == {}
    assert all(v in state.villagers for v in ("v0", "v1", "v2"))
```

The last test needs rock tiles: add `"R": "rock"` to the `TERRAIN` mapping in `tests/pericles/conftest.py`. Rock is walkable in the base pack, with move cost 3.

Run: `uv run pytest tests/pericles/test_scripted_work.py -q`
Expected: FAIL with `AttributeError: module 'pericles.agents.rules' has no attribute 'demand'`.

- [ ] **Step 2: Implement work, deposit and deliver**

Append to `src/pericles/agents/rules.py`, and add `Deliver` and `Deposit` to its intents import and `remaining_cost` from `pericles.core.buildings`:

```python
def demand(view: View, item: str) -> float:
    """How much the village wants `item`, 0..1 (ADR-0016 §4)."""
    if view.ctx.registry.items[item].nutrition > 0:
        target = view.food_target()
        return 0.0 if target <= 0 else max(0.0, target - view.food_stock()) / target
    return 1.0 if view.needed()[item] > 0 else 0.0


def utility(view: View, villager: Villager, action: ActionDef) -> float:
    best = max(demand(view, item) / (1 + view.workers(item, villager.id)) for item in action.outputs)
    return best * skill_score(view, villager, action)


def work(view: View, villager: Villager) -> Decision | None:
    wanted = [item for item in sorted(view.ctx.registry.items) if demand(view, item) > 0]
    scored = [(utility(view, villager, a), a) for a in jobs(view, villager, wanted)]
    ranked = [a for score, a in sorted(scored, key=lambda p: (-p[0], p[1].id)) if score > 0]
    return first_reachable(view, villager, ranked)


def deliver(view: View, villager: Villager) -> Decision | None:
    registry = view.ctx.registry
    for building in view.sites():
        remaining = remaining_cost(building, registry)
        for item in sorted(remaining):
            have = villager.inventory.count(item)
            if not have:
                continue
            step = view.go(villager, view.tiles(building))
            if step is not None:
                return Decision(step, target=building.id)
            qty = min(have, remaining[item])
            return Decision(Deliver(villager.id, building.id, item, qty), target=building.id)
    return None


def surplus(view: View, villager: Villager) -> list[tuple[str, int]]:
    """Stackable items to store: all but a little food, never tools or what sites need."""
    registry = view.ctx.registry
    needed = view.needed()
    extra = []
    for item, qty in sorted(villager.inventory.items.items()):
        if needed[item] > 0:
            continue
        nutrition = registry.items[item].nutrition
        keep = math.floor(view.config.food_carry / nutrition) if nutrition > 0 else 0
        if qty > keep:
            extra.append((item, qty - keep))
    return extra


def deposit(view: View, villager: Villager) -> Decision | None:
    load = villager.inventory.weight(view.ctx.registry)
    if load < view.config.deposit_load * view.ctx.config.carry_limit:
        return None
    for item, qty in surplus(view, villager):
        for building in view.stores(villager):
            room = view.room(building)
            if room <= 0:
                continue
            step = view.go(villager, view.tiles(building))
            if step is not None:
                return Decision(step, target=building.id)
            return Decision(Deposit(villager.id, building.id, item, min(qty, room)), target=building.id)
    return None
```

`Inventory.items` holds stackable items only, and tools live in `Inventory.tools`, so tools are never surplus. Check this against `src/pericles/core/inventory.py` before relying on it.

In `src/pericles/agents/scripted.py`, set:

```python
    rules: tuple[Rule, ...] = (
        rules.eat,
        rules.sleep,
        rules.shelter,
        rules.deliver,
        rules.deposit,
        rules.work,
    )
```

Run: `uv run pytest tests/pericles/test_scripted_work.py tests/pericles/test_scripted_survival.py -q`
Expected: PASS.

- [ ] **Step 3: Mutation-test, run the gates and commit**

```bash
git add src/pericles/agents tests/pericles/test_scripted_work.py tests/pericles/conftest.py
git commit -m "feat(agents): demand- and skill-driven work, deposits and site deliveries

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Building, homes and couples — the village builder

**Files:**
- Modify: `src/pericles/agents/rules.py`, `src/pericles/agents/scripted.py`
- Test: `tests/pericles/test_scripted_village.py`

**Interfaces:**
- Consumes: Tasks 2–5.
- Produces:
  - In `rules`:
    - `wanted_building(view, villager) -> str | None`.
    - `compatible(view, a, b) -> bool`.
    - The rules `build`, `home` and `couple`.
  - `ScriptedMind.rules = (eat, sleep, shelter, couple, home, deliver, deposit, build, work)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_scripted_village.py`:

```python
from collections.abc import Callable

import pytest

from pericles.agents import rules
from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller
from pericles.agents.scripted import ScriptedMind
from pericles.agents.view import CONSTRUCT, Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership, footprint
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import AcceptCouple, Construct, PlaceBuilding, ProposeCouple, SetHome
from pericles.core.nodes import Node
from pericles.core.state import Proposal, Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 16] * 16


def view_of(registry: Registry, state: WorldState, memory: dict[str, Memory] | None = None, **cfg: object) -> View:
    ctx = Context.build(registry, default_config())
    config = AgentConfig(**cfg)  # type: ignore[arg-type]
    return View(ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), memory or {})


def supplied_site(state: WorldState, registry: Registry, at: Coord = Coord(2, 2)) -> Building:
    building = Building("s1", "house", at, Ownership("communal"), delivered=dict(registry.buildings["house"].cost))
    state.buildings["s1"] = building
    return building


def house(state: WorldState, bid: str, at: Coord) -> Building:
    state.buildings[bid] = Building(bid, "house", at, Ownership("communal"), complete=True)
    return state.buildings[bid]


def test_build_a_supplied_site_within_the_builder_limit(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: once a site has its materials, villagers build it, up to max_builders at a time."""
    a = Villager("a", "A", Coord(3, 4), home="h0")
    state = make_world(ROWS, [a])
    house(state, "h0", Coord(10, 10))
    supplied_site(state, registry)
    decision = rules.build(view_of(registry, state, storage_per_capita=0.0), a)
    assert decision is not None
    assert (decision.intent, decision.target, decision.job) == (Construct("a", "s1"), "s1", CONSTRUCT)
    busy = {f"o{i}": Memory(job=CONSTRUCT, target="s1") for i in range(3)}
    for vid in busy:
        state.villagers[vid] = Villager(vid, "O", Coord(0, 0), home="h0")
    assert rules.build(view_of(registry, state, busy, storage_per_capita=0.0, max_builders=3), a) is None


def test_the_homeless_place_one_communal_house_at_a_time(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: with too few beds, one villager claims and places a communal house."""
    a, b = Villager("a", "A", Coord(8, 8)), Villager("b", "B", Coord(8, 8))
    state = make_world(ROWS, [a, b])
    view = view_of(registry, state, storage_per_capita=0.0)
    decision = rules.build(view, a)
    assert decision is not None and decision.target == "place:house"
    origin = view.free_origin("house")
    assert origin is not None
    walk = view.go(a, footprint(origin, registry.buildings["house"].footprint))
    assert decision.intent == (walk or PlaceBuilding("a", "house", origin, ownership="communal"))
    claimed = {"b": Memory(target="place:house")}
    assert rules.build(view_of(registry, state, claimed, storage_per_capita=0.0), a) is None
    avoided = {"a": Memory(avoid={"place:house": 99})}
    assert rules.build(view_of(registry, state, avoided, storage_per_capita=0.0), a) is None
    house(state, "h0", Coord(1, 1))
    assert rules.build(view_of(registry, state, storage_per_capita=0.0), a) is None


def test_a_storehouse_when_storage_runs_short(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: once housed, the village builds communal storage for its population."""
    villagers = [Villager(f"v{i}", "V", Coord(8, 8), home="h0") for i in range(4)]
    state = make_world(ROWS, villagers)
    house(state, "h0", Coord(1, 1))
    decision = rules.build(view_of(registry, state, storage_per_capita=15.0), villagers[0])
    assert decision is not None and decision.target == "place:storehouse"
    assert rules.build(view_of(registry, state, storage_per_capita=5.0), villagers[0]) is None


def test_homes_go_to_the_homeless_and_reunite_partners(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: homeless villagers move in; partners living apart move together."""
    a = Villager("a", "A", Coord(0, 0), sex="female", partner="b")
    b = Villager("b", "B", Coord(0, 0), sex="male", partner="a", home="h1")
    c = Villager("c", "C", Coord(0, 0), home="h0")
    state = make_world(ROWS, [a, b, c])
    house(state, "h0", Coord(1, 1))
    house(state, "h1", Coord(9, 9))
    assert rules.home(view_of(registry, state), a).intent == SetHome("a", "h1")  # type: ignore[union-attr]
    a.home = "h0"
    assert rules.home(view_of(registry, state), a).intent == SetHome("a", "h1")  # type: ignore[union-attr]
    assert rules.home(view_of(registry, state), c) is None
    a.home = "h1"
    assert rules.home(view_of(registry, state), a) is None


def test_couples_accept_then_propose_to_compatible_adults(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: unpartnered adults accept proposals made to them, or propose to the nearest match."""
    a = Villager("a", "A", Coord(0, 0), sex="female")
    m1 = Villager("m1", "M", Coord(5, 0), sex="male")
    m2 = Villager("m2", "M", Coord(2, 0), sex="male")
    f2 = Villager("f2", "F", Coord(1, 0), sex="female")
    kid = Villager("k", "K", Coord(1, 1), sex="male", adult=False)
    state = make_world(ROWS, [a, m1, m2, f2, kid])
    assert rules.couple(view_of(registry, state), a).intent == ProposeCouple("a", "m2")  # type: ignore[union-attr]
    state.proposals["m1"] = Proposal("a", 50)
    assert rules.couple(view_of(registry, state), a).intent == AcceptCouple("a", "m1")  # type: ignore[union-attr]
    state.tick = 50
    assert rules.couple(view_of(registry, state), a).intent == ProposeCouple("a", "m2")  # type: ignore[union-attr]
    state.proposals = {"a": Proposal("m2", 99)}
    assert rules.couple(view_of(registry, state), a) is None
    assert rules.couple(view_of(registry, state), f2).intent == ProposeCouple("f2", "m1")  # type: ignore[union-attr]
    state.proposals = {}
    assert rules.couple(view_of(registry, state, couples=False), a) is None
    assert rules.couple(view_of(registry, state), kid) is None
    assert not rules.compatible(view_of(registry, state), a, f2)


def test_scripted_villagers_house_themselves_and_pair_up(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: homeless scripted villagers build a house, move in and form couples, all unaided."""
    rows = ["......" + "T" * 10] * 8 + ["." * 16] * 4 + ["RRRRRR" + "." * 10] * 4
    trees = [Node(f"t{i}", "tree", Coord(7 + i, 3), 10) for i in range(5)]
    rocks = [Node("r0", "boulder", Coord(2, 13), 30), Node("r1", "boulder", Coord(4, 13), 30)]
    bushes = [Node(f"b{i}", "berry_bush", Coord(9 + i, 10), 20) for i in range(3)]
    people = [
        Villager(vid, vid.upper(), Coord(6, 9), sex=sex, skills={"woodcutting": 30.0, "masonry": 30.0})
        for vid, sex in [("a", "female"), ("b", "male"), ("c", "female"), ("d", "male")]
    ]
    state = make_world(rows, people, [*trees, *rocks, *bushes])
    engine = Engine(registry, default_config(debug_invariants=True))
    ctl = Controller(engine.context, AgentConfig(storage_per_capita=0.0), ScriptedMind(), ScriptedMind())
    for _ in range(6000):
        state, events = engine.step(state, ctl.intents(state))
        ctl.observe(state, events)
        if all(v.home is not None for v in state.villagers.values()) and all(v.partner for v in state.villagers.values()):
            break
    assert len(state.villagers) == 4
    assert any(b.complete and b.kind == "house" for b in state.buildings.values())
    assert all(v.home is not None for v in state.villagers.values())
    assert all(v.partner is not None for v in state.villagers.values())
```

Run: `uv run pytest tests/pericles/test_scripted_village.py -q`
Expected: FAIL with `AttributeError: module 'pericles.agents.rules' has no attribute 'build'`.

- [ ] **Step 2: Implement build, home and couple**

Append to `src/pericles/agents/rules.py`. Add these imports:
- `AcceptCouple`, `Construct`, `PlaceBuilding`, `ProposeCouple` and `SetHome` to the intents import;
- `footprint` from `pericles.core.buildings`;
- `CONSTRUCT` and `PLACE` from `pericles.agents.view`.

```python
COMMUNAL = "communal"


def wanted_building(view: View, villager: Villager) -> str | None:
    """The building kind the village lacks and nobody else is placing (ADR-0016 §4)."""
    config = view.config
    wants = (
        (config.house_building, view.housing_shortfall() > 0),
        (config.store_building, view.storage_shortfall() > 0),
    )
    for kind, short in wants:
        if short and not view.placing(kind, villager.id) and not view.avoided(villager, PLACE + kind):
            return kind
    return None


def build(view: View, villager: Villager) -> Decision | None:
    if not villager.adult:
        return None
    registry = view.ctx.registry
    for building in view.sites():
        if remaining_cost(building, registry):
            continue
        if view.builders(building.id, villager.id) >= view.config.max_builders:
            continue
        step = view.go(villager, view.tiles(building))
        intent = step if step is not None else Construct(villager.id, building.id)
        return Decision(intent, target=building.id, job=CONSTRUCT)
    kind = wanted_building(view, villager)
    origin = view.free_origin(kind) if kind is not None else None
    if kind is None or origin is None:
        return None
    step = view.go(villager, footprint(origin, registry.buildings[kind].footprint))
    intent = step if step is not None else PlaceBuilding(villager.id, kind, origin, ownership=COMMUNAL)
    return Decision(intent, target=PLACE + kind)


def home(view: View, villager: Villager) -> Decision | None:
    current = view.home(villager)
    partner = view.state.villagers.get(villager.partner) if villager.partner is not None else None
    apart = partner is not None and partner.home is not None and partner.home != villager.home
    if current is not None and not apart:
        return None
    house = view.house_for(villager)
    if house is None or house.id == villager.home:
        return None
    return Decision(SetHome(villager.id, house.id), target=house.id)


def compatible(view: View, a: Villager, b: Villager | None) -> bool:
    """Exactly one of the pair has the bearing sex (ADR-0015 §6)."""
    if b is None or a.sex is None or b.sex is None:
        return False
    bearing = view.ctx.config.bearing_sex
    return (a.sex == bearing) != (b.sex == bearing)


def couple(view: View, villager: Villager) -> Decision | None:
    if not view.config.couples or not villager.adult or villager.partner is not None:
        return None
    state = view.state
    for proposer in sorted(state.proposals):
        proposal = state.proposals[proposer]
        if (
            proposal.target == villager.id
            and proposal.expires_tick > state.tick
            and not view.avoided(villager, proposer)
            and compatible(view, villager, state.villagers.get(proposer))
        ):
            return Decision(AcceptCouple(villager.id, proposer), target=proposer)
    if villager.id in state.proposals:
        return None
    targeted = {p.target for p in state.proposals.values()}
    free = [
        other
        for other in state.villagers.values()
        if other.id != villager.id
        and other.adult
        and other.partner is None
        and other.id not in state.proposals
        and other.id not in targeted
        and compatible(view, villager, other)
        and not view.avoided(villager, other.id)
    ]
    if not free:
        return None
    other = min(free, key=lambda o: (villager.pos.manhattan(o.pos), o.id))
    return Decision(ProposeCouple(villager.id, other.id), target=other.id)
```

In `test_couples_accept_then_propose_to_compatible_adults`:
- At tick 50 the proposal `m1 → a` has expired (`expires_tick > tick` fails), so `a` proposes again. It proposes to `m2`, because `m1`, as a proposer, is excluded.
- `f2` cannot propose to `m2`, who is the target of `a`'s proposal, so it proposes to `m1`.

In `src/pericles/agents/scripted.py`, set:

```python
    rules: tuple[Rule, ...] = (
        rules.eat,
        rules.sleep,
        rules.shelter,
        rules.couple,
        rules.home,
        rules.deliver,
        rules.deposit,
        rules.build,
        rules.work,
    )
```

Run: `uv run pytest tests/pericles/test_scripted_village.py tests/pericles/test_scripted_work.py tests/pericles/test_scripted_survival.py -q`
Expected: PASS.

Inserting `couple` and `home` before `deliver` can change what earlier tests see. For example, a homeless villager next to a communal house now moves in first. If an earlier test breaks, fix its setup (give the villager a home, or `couples=False`), not the rule. Name each such change in the report.

- [ ] **Step 3: Mutation-test, run the gates and commit**

```bash
git add src/pericles/agents tests/pericles
git commit -m "feat(agents): scripted village builder — sites, construction, homes and couples

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The child mind and the scripted controller

**Files:**
- Modify: `src/pericles/agents/rules.py`, `src/pericles/agents/scripted.py`
- Test: `tests/pericles/test_scripted_children.py`

**Interfaces:**
- Consumes: Tasks 2–6.
- Produces:
  - In `rules`: the rules `child_eat`, `follow` and `forage`.
  - In `scripted`:
    - `ChildMind` with `rules = (child_eat, sleep, shelter, follow, deposit, forage)`.
    - `scripted_controller(ctx: Context, config: AgentConfig, minds: Mapping[str, Mind] | None = None) -> Controller`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_scripted_children.py`:

```python
from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.scripted import ChildMind, ScriptedMind, scripted_controller
from pericles.agents.view import Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import Eat, MoveTo, Sleep, StartAction, Take, Wait
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

MakeWorld = Callable[..., WorldState]
ROWS = ["......TTTT"] * 10
CONFIG = AgentConfig()
HUNGRY = {"hunger": CONFIG.act_at["eat"]}


def decide(registry: Registry, state: WorldState, vid: str = "k", memory: dict[str, Memory] | None = None):  # type: ignore[no-untyped-def]
    ctx = Context.build(registry, default_config())
    view = View(ctx, state, CONFIG, NodeIndex(state.nodes.values(), CONFIG.index_cell), memory or {})
    return ChildMind().decide(view, state.villagers[vid])


def family(child_at: Coord, **child: object) -> list[Villager]:
    return [
        Villager("m", "M", Coord(2, 2), sex="female"),
        Villager("k", "K", child_at, adult=False, parents=("m", "z"), **child),  # type: ignore[arg-type]
    ]


@pytest.mark.req("REQ-SIM-016")
def test_a_child_stays_near_a_parent(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: stay near a parent."""
    state = make_world(ROWS, family(Coord(9, 9)))
    decision = decide(registry, state)
    assert isinstance(decision.intent, MoveTo) and decision.target == "m"
    state.villagers["k"].pos = Coord(2, 2 + CONFIG.child_follow_radius)
    assert decide(registry, state).intent == Wait("k")


@pytest.mark.req("REQ-SIM-016")
def test_a_hungry_child_eats_from_hand_or_store(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: eat."""
    state = make_world(ROWS, family(Coord(3, 2), needs=dict(HUNGRY)))
    kid = state.villagers["k"]
    kid.inventory.add(registry, "berries", 5)
    assert isinstance(decide(registry, state).intent, Eat)
    kid.inventory.remove("berries", 5)
    store = Building("s0", "storehouse", Coord(3, 4), Ownership("communal"), complete=True)
    store.storage.add(registry, "fish", 3)
    state.buildings["s0"] = store
    kid.pos = Coord(3, 3)
    assert decide(registry, state).intent == Take("k", "s0", "fish", 3)


@pytest.mark.req("REQ-SIM-016")
def test_a_child_forages_only_light_work_near_the_parent(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: light gathering, close to a parent; heavy work is never chosen."""
    near_bush = Node("b0", "berry_bush", Coord(3, 3), 20)
    tree = Node("t0", "tree", Coord(6, 2), 10)
    state = make_world(ROWS, family(Coord(3, 2), needs=dict(HUNGRY)), [near_bush, tree])
    assert decide(registry, state).intent == StartAction("k", "gather_berries", "b0")
    far = make_world(ROWS, family(Coord(5, 2), needs=dict(HUNGRY)), [Node("b1", "berry_bush", Coord(2, 9), 20), tree])
    assert decide(registry, far).intent == Wait("k")


@pytest.mark.req("REQ-SIM-016")
def test_a_tired_child_sleeps(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: children sleep when tired, like adults."""
    state = make_world(ROWS, family(Coord(3, 2), needs={"fatigue": CONFIG.act_at["sleep"]}))
    assert decide(registry, state).intent == Sleep("k")


@pytest.mark.req("REQ-SIM-016", "REQ-AGT-008")
def test_a_family_runs_without_child_rejections(registry: Registry, make_world: MakeWorld) -> None:
    """SIM-016 AC1 / AGT-008 AC2: under the scripted controller a child only does what children may."""
    rows = ["." * 12] * 12
    people = [
        Villager("m", "M", Coord(5, 5), sex="female", partner="f"),
        Villager("f", "F", Coord(5, 6), sex="male", partner="m"),
        Villager("k", "K", Coord(6, 5), adult=False, parents=("f", "m"), needs=dict(HUNGRY)),
    ]
    bushes = [Node(f"b{i}", "berry_bush", Coord(4 + i, 3), 20) for i in range(4)]
    state = make_world(rows, people, bushes)
    engine = Engine(registry, default_config(debug_invariants=True))
    ctl = scripted_controller(engine.context, CONFIG)
    assert isinstance(ctl.adult, ScriptedMind) and isinstance(ctl.child, ChildMind)
    started: set[str] = set()
    for _ in range(1500):
        state, events = engine.step(state, ctl.intents(state))
        ctl.observe(state, events)
        for e in events:
            if e.kind == "intent_rejected" and e.data["actor"] == "k":
                assert e.data["reason"] != "too_young", e
            if e.kind == "work_started" and e.data["actor"] == "k":
                started.add(e.data["ident"])
    assert "k" in state.villagers
    assert started and all("light" in registry.actions[a].tags for a in started)
```

Run: `uv run pytest tests/pericles/test_scripted_children.py -q`
Expected: FAIL with `ImportError: cannot import name 'ChildMind'`.

- [ ] **Step 2: Implement the child rules and the factory**

Append to `src/pericles/agents/rules.py`:

```python
def child_eat(view: View, villager: Villager) -> Decision | None:
    """Children eat what they hold or what a store holds; they forage separately, near family."""
    if view.level(villager, EAT) < view.config.act_at[EAT]:
        return None
    return feed(view, villager)


def follow(view: View, villager: Villager) -> Decision | None:
    parent = view.guardian(villager)
    if parent is None or view.avoided(villager, parent.id):
        return None
    if villager.pos.manhattan(parent.pos) <= view.config.child_follow_radius:
        return None
    step = view.go(villager, [parent.pos])
    return None if step is None else Decision(step, target=parent.id)


def forage(view: View, villager: Villager) -> Decision | None:
    parent = view.guardian(villager)
    origin = villager.pos if parent is None else parent.pos
    return gather(view, villager, view.foods, origin=origin, radius=view.config.child_follow_radius)
```

The forage test expects a child with full hands to wait. `gather` already checks the carry limit through `fits_output`. `jobs` already keeps children to `child_action_tags`.

In `src/pericles/agents/scripted.py`, add:

```python
class ChildMind(ScriptedMind):
    """Children: stay near a parent, eat, light gathering (REQ-SIM-016 AC1)."""

    rules: tuple[Rule, ...] = (
        rules.child_eat,
        rules.sleep,
        rules.shelter,
        rules.follow,
        rules.deposit,
        rules.forage,
    )


def scripted_controller(
    ctx: Context, config: AgentConfig, minds: Mapping[str, Mind] | None = None
) -> Controller:
    """The controller every run uses: scripted adults and children, plus any model minds."""
    return Controller(ctx, config, ScriptedMind(), ChildMind(), minds)
```

Import `Mapping`, `AgentConfig`, `Context`, `Controller` and `Mind` accordingly.

Run: `uv run pytest tests/pericles/test_scripted_children.py -q`
Expected: PASS.

- [ ] **Step 3: Mutation-test, run the gates and commit**

```bash
git add src/pericles/agents tests/pericles/test_scripted_children.py
git commit -m "feat(agents): scripted child mind and the scripted controller factory

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Runs with agents — durable snapshots and a resume that matches no crash

**Files:**
- Modify: `src/pericles/experiment/rundir.py`, `src/pericles/experiment/runner.py`
- Test: `tests/pericles/test_rundir.py`, `tests/pericles/test_runner.py`

**Interfaces:**
- Consumes: `Controller.intents/observe/to_dict/load`, `scripted_controller` (Task 7).
- Produces:
  - In `rundir`:
    - `RunDirectory.SCHEMA_VERSION = 3`.
    - `Snapshot(tick: int, world: dict[str, Any], agents: dict[str, Any])`, frozen.
    - `RunDirectory.save_snapshot(state, agents: Mapping[str, Any] | None = None) -> Path`.
    - `RunDirectory.snapshots() -> Iterator[Snapshot]`, newest usable first.
    - `RunDirectory.latest_snapshot() -> Snapshot | None`.
    - `RunDirectory.skipped: list[Path]`.
  - In `runner`:
    - The `Agents` Protocol, with `intents(state)`, `observe(state, events)` and `to_dict()`.
    - `SourceAgents(source: IntentSource)`.
    - `run(run_dir, engine, state, agents: Agents, until_tick, snapshot_every, *, stop_when_extinct: bool = True) -> WorldState`.
    - `resume(run_dir) -> tuple[WorldState, dict[str, Any]]`.

- [ ] **Step 1: Update the existing tests to the new interfaces**

In `tests/pericles/test_runner.py`:
- wrap every `source_for(walkable)` passed to `run` as `SourceAgents(source_for(walkable))`;
- unpack `state, _ = resume(run_dir)` wherever `resume` is called.

In `tests/pericles/test_rundir.py`:
- change the pinned schema version to `3`;
- read `latest_snapshot()` through `.world` (a `Snapshot`) where the test used the returned dict.

Run: `uv run pytest tests/pericles/test_runner.py tests/pericles/test_rundir.py -q`
Expected: FAIL with `ImportError: cannot import name 'SourceAgents'`.

- [ ] **Step 2: Write the new failing tests**

Append to `tests/pericles/test_runner.py`:

```python
import os

from pericles.agents.config import AgentConfig
from pericles.agents.scripted import scripted_controller
from pericles.core.nodes import Node
from pericles.experiment.defaults import default_config
from pericles.experiment.runner import SourceAgents


def village(registry: Registry, small_map: TileMap) -> WorldState:
    start = small_map.start()
    people = [Villager(f"v{i}", f"V{i}", start, sex=("female", "male")[i % 2]) for i in range(4)]
    bushes = [Node(f"n{i}", "berry_bush", Coord(start.x + i - 2, start.y + 2), 20) for i in range(4)]
    return WorldState.new(4, small_map, people, bushes)


def test_resume_matches_a_run_that_never_stopped(tmp_path: Path, registry: Registry, small_map: TileMap) -> None:
    """AC3: crash and resume give the same event log as an uninterrupted run, agents included."""
    engine = Engine(registry, default_config())
    straight = RunDirectory.create(tmp_path / "a", {"seed": 4}, seed=4)
    run(straight, engine, village(registry, small_map), scripted_controller(engine.context, AgentConfig()), 600, 100)
    crashed = RunDirectory.create(tmp_path / "b", {"seed": 4}, seed=4)
    run(crashed, engine, village(registry, small_map), scripted_controller(engine.context, AgentConfig()), 350, 100)
    crashed.close()
    reopened = RunDirectory.open(tmp_path / "b")
    state, agents = resume(reopened)
    assert state.tick == 300
    controller = scripted_controller(Engine(registry, default_config()).context, AgentConfig())
    controller.load(agents)
    run(reopened, Engine(registry, default_config()), state, controller, 600, 100)
    assert reopened.event_log.digest() == straight.event_log.digest()


def test_resume_skips_corrupt_and_mismatched_snapshots(tmp_path: Path, registry: Registry, small_map: TileMap) -> None:
    """AC3: a damaged newest snapshot is skipped and reported, not fatal."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, SourceAgents(source_for(walkable)), 30, 10)
    snaps = run_dir.path / "snapshots"
    (snaps / "tick-0000000030.json").write_text('{"world": {"tick"', encoding="utf-8")
    os.replace(snaps / "tick-0000000010.json", snaps / "tick-0000000020.json")
    resumed, _ = resume(run_dir)
    assert resumed.tick == 0
    assert {p.name for p in run_dir.skipped} == {"tick-0000000030.json", "tick-0000000020.json"}
    assert run_dir.event_log.last_tick() is None


def test_resume_never_starts_ahead_of_the_log(tmp_path: Path, registry: Registry, small_map: TileMap) -> None:
    """AC2/AC3: a snapshot newer than the logged ticks is not used."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, SourceAgents(source_for(walkable)), 30, 10)
    run_dir.event_log.truncate_after(14)
    resumed, _ = resume(run_dir)
    assert resumed.tick == 10
    assert run_dir.event_log.last_tick() == 9


def test_no_usable_snapshot_is_a_run_directory_error(tmp_path: Path, registry: Registry, small_map: TileMap) -> None:
    """AC3: when nothing can be resumed, say so."""
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    with pytest.raises(RunDirectoryError, match="no usable snapshot"):
        resume(run_dir)
    (run_dir.path / "snapshots" / "tick-0000000000.json").write_text("[]", encoding="utf-8")
    with pytest.raises(RunDirectoryError, match="no usable snapshot"):
        resume(run_dir)


def test_snapshots_hold_agent_memory_and_are_fsynced(
    tmp_path: Path, registry: Registry, small_map: TileMap, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1/AC3: a snapshot carries the controller memory and reaches the disk."""
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    state, _ = initial(small_map, registry)
    calls: list[int] = []
    real = os.fsync
    monkeypatch.setattr(os, "fsync", lambda fd: (calls.append(fd), real(fd))[1])
    run_dir.save_snapshot(state, {"memory": {"v0": "x"}})
    assert len(calls) >= 2  # the file, then its directory
    snapshot = run_dir.latest_snapshot()
    assert snapshot is not None and snapshot.agents == {"memory": {"v0": "x"}}
    assert snapshot.world == state.to_dict()


def test_a_run_stops_when_the_village_dies_out(tmp_path: Path, life: Registry, small_map: TileMap) -> None:
    """AC1: an extinct village ends the run early, snapshotted at the end."""
    state = WorldState.new(4, small_map, [Villager("v0", "V", small_map.start())])
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    final = run(run_dir, Engine(life), state, SourceAgents(lambda s: []), 10_000, 1000)
    assert not final.villagers
    assert final.tick < 10_000
    assert run_dir.snapshot_ticks()[-1] == final.tick
```

The `life` registry starves a villager within a couple of hundred ticks: hunger rises 1 per tick and does 10 damage per tick at critical. Its terrain ids (grass, water, forest) are the ones `small_map` uses.

Run: `uv run pytest tests/pericles/test_runner.py -q`
Expected: FAIL (`SourceAgents` and the new behaviour are missing).

- [ ] **Step 3: Implement durable snapshots**

In `src/pericles/experiment/rundir.py`:
- add `from collections.abc import Iterator` and `from dataclasses import dataclass`;
- set `SCHEMA_VERSION = 3`;
- write `config.yaml` and `meta.json` through `_write_durably`;
- initialise `self.skipped: list[Path] = []` in `__init__`;
- replace the snapshot methods with:

```python
def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_durably(target: Path, text: str) -> None:
    """Write to a temporary file, fsync it, rename it into place and fsync the directory."""
    temporary = target.with_suffix(target.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    _fsync_dir(target.parent)


@dataclass(frozen=True)
class Snapshot:
    tick: int
    world: dict[str, Any]
    agents: dict[str, Any]
```

```python
    def _snapshot_path(self, tick: int) -> Path:
        return self.path / "snapshots" / f"tick-{tick:010d}.json"

    def save_snapshot(self, state: WorldState, agents: Mapping[str, Any] | None = None) -> Path:
        target = self._snapshot_path(state.tick)
        payload = {"world": state.to_dict(), "agents": dict(agents or {})}
        _write_durably(target, canonical_json(payload))
        return target

    def snapshot_ticks(self) -> list[int]:
        return sorted(
            int(p.stem.removeprefix("tick-")) for p in (self.path / "snapshots").glob("tick-*.json")
        )

    def snapshots(self) -> Iterator[Snapshot]:
        """Usable snapshots, newest first; unreadable or mislabelled ones go to `skipped`."""
        for tick in reversed(self.snapshot_ticks()):
            path = self._snapshot_path(tick)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                snapshot = Snapshot(tick, dict(payload["world"]), dict(payload["agents"]))
                usable = snapshot.world.get("tick") == tick
            except (OSError, ValueError, KeyError, TypeError):
                usable = False
            if not usable:
                self.skipped.append(path)
                continue
            yield snapshot

    def latest_snapshot(self) -> Snapshot | None:
        return next(self.snapshots(), None)
```

Use `canonical_json` for the payload. Don't use `json.dumps` there: snapshots must stay byte-stable for a given state.

- [ ] **Step 4: Implement agents in the runner and the safe resume**

Replace `src/pericles/experiment/runner.py` with:

```python
"""Drive the engine and agents, persist each tick, snapshot, and resume after crashes (REQ-EXP-003)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.intents import Intent
from pericles.core.state import WorldState
from pericles.experiment.rundir import RunDirectory, RunDirectoryError

IntentSource = Callable[[WorldState], Sequence[Intent]]


class Agents(Protocol):
    def intents(self, state: WorldState) -> Sequence[Intent]: ...

    def observe(self, state: WorldState, events: Sequence[Event]) -> None: ...

    def to_dict(self) -> dict[str, Any]: ...


class SourceAgents:
    """A plain intent function (tests, replays) as stateless agents."""

    def __init__(self, source: IntentSource) -> None:
        self.source = source

    def intents(self, state: WorldState) -> Sequence[Intent]:
        return self.source(state)

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {}


def run(
    run_dir: RunDirectory,
    engine: Engine,
    state: WorldState,
    agents: Agents,
    until_tick: int,
    snapshot_every: int,
    *,
    stop_when_extinct: bool = True,
) -> WorldState:
    if snapshot_every < 1:
        raise ValueError("snapshot_every must be at least 1")
    if until_tick < state.tick:
        raise ValueError(f"until_tick {until_tick} is before the current tick {state.tick}")
    log = run_dir.event_log
    if state.tick % snapshot_every == 0 and state.tick not in run_dir.snapshot_ticks():
        run_dir.save_snapshot(state, agents.to_dict())
    while state.tick < until_tick:
        if stop_when_extinct and not state.villagers:
            if state.tick not in run_dir.snapshot_ticks():
                run_dir.save_snapshot(state, agents.to_dict())
            break
        state, events = engine.step(state, agents.intents(state))
        agents.observe(state, events)
        log.append_tick(state.tick - 1, events)
        if state.tick % snapshot_every == 0:
            run_dir.save_snapshot(state, agents.to_dict())
    return state


def resume(run_dir: RunDirectory) -> tuple[WorldState, dict[str, Any]]:
    """Restore the newest usable snapshot the event log covers; truncate the log to it."""
    last = run_dir.event_log.last_tick()
    logged = 0 if last is None else last + 1
    for snapshot in run_dir.snapshots():
        if snapshot.tick > logged:
            run_dir.skipped.append(run_dir.path / "snapshots" / f"tick-{snapshot.tick:010d}.json")
            continue
        try:
            state = WorldState.from_dict(snapshot.world)
        except (KeyError, TypeError, ValueError):
            run_dir.skipped.append(run_dir.path / "snapshots" / f"tick-{snapshot.tick:010d}.json")
            continue
        run_dir.event_log.truncate_after(state.tick - 1)
        return state, snapshot.agents
    raise RunDirectoryError(f"{run_dir.path}: no usable snapshot to resume from")
```

The extinct check snapshots the final state, so a resume of an extinct run returns the empty world instead of replaying the last day.

In `test_resume_skips_corrupt_and_mismatched_snapshots`:
- `tick-30` is corrupt and is skipped.
- The tick-10 file renamed to `tick-20` is mislabelled, because its world says tick 10. It is skipped too.
- The tick-20 file it replaced is gone.
- Tick 10's own file is also gone, because it was moved. So the tick-0 snapshot is used. The test's expected `resumed.tick == 0` matches this.

If `os.replace` onto an existing name behaves differently on the platform, use `unlink` and then `rename`.

Run: `uv run pytest tests/pericles/test_runner.py tests/pericles/test_rundir.py -q`
Expected: PASS.

- [ ] **Step 5: Mutation-test, run the gates and commit**

`pericles.experiment` has no mutation threshold. Still, run `uv run mutmut run --paths-to-mutate src/pericles/experiment/runner.py,src/pericles/experiment/rundir.py` if it finishes in reasonable time, and list notable survivors in the report.

```bash
git add src/pericles/experiment tests/pericles
git commit -m "feat(experiment): agent memory in fsynced snapshots; resume skips corrupt or unlogged ones

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The experiment file and the starting world

**Files:**
- Modify: `src/pericles/core/mapgen.py`: rename `_validate` to `validate` and update its call in `generate_map`.
- Modify: `src/pericles/experiment/settings.py`: rename `_mapping` to `as_mapping` and `_values` to `values_for`, updating every use. They become public helpers.
- Create: `src/pericles/experiment/config.py`, `experiments/baseline.yaml`
- Test: `tests/pericles/test_experiment_config.py`

**Interfaces:**
- Consumes: `engine_config_from_mapping`, `agent_config_from_mapping`, `default_settings_mapping` (Task 1); core `generate_map`, `validate`, `start_area`, `place_nodes`, `load_registry`, `base_pack_path`, `bundle_weight`.
- Produces (in `pericles.experiment.config`):
  - `ExperimentError(ValueError)`.
  - `VillagerSpec` and `RunSpec` (pydantic, frozen).
  - `Experiment(seed, packs, map, population, run, engine, agents, registry, resolved)`, a frozen dataclass.
  - `experiment_from_mapping(raw: object, base_dir: Path) -> Experiment`.
  - `load_experiment(path: Path) -> Experiment`.
  - `build_world(experiment: Experiment) -> WorldState`.

- [ ] **Step 1: Write the baseline experiment**

Create `experiments/baseline.yaml`:

```yaml
# The all-scripted baseline village (ADR-0016). Copy it to start a new experiment.
# engine: and agents: override the packaged default_settings.yaml key by key.
seed: 1
packs: [base]
map:
  width: 64
  height: 64
  bands:
    - {terrain: water, share: 0.12}
    - {terrain: fertile_soil, share: 0.18}
    - {terrain: grass, share: 0.35}
    - {terrain: forest, share: 0.25}
    - {terrain: rock, share: 0.10}
  veins:
    - {terrain: iron_vein, share: 0.02, host: rock}
    - {terrain: gold_vein, share: 0.005, host: rock}
  start_terrain: grass
  start_radius: 6
population:
  - {id: ada, name: Ada, sex: female, age_days: 210, traits: [industrious], skills: {foraging: 20.0}, inventory: {berries: 4}}
  - {id: bram, name: Bram, sex: male, age_days: 260, skills: {woodcutting: 25.0}, inventory: {berries: 4}}
  - {id: cora, name: Cora, sex: female, age_days: 180, traits: [altruistic], skills: {masonry: 20.0}, inventory: {berries: 4}}
  - {id: dov, name: Dov, sex: male, age_days: 300, traits: [dutiful], skills: {woodcutting: 15.0, masonry: 10.0}, inventory: {berries: 4}}
  - {id: elin, name: Elin, sex: female, age_days: 150, skills: {fishing: 20.0}, inventory: {berries: 4}}
  - {id: fenn, name: Fenn, sex: male, age_days: 140, traits: [greedy], skills: {hunting: 20.0}, inventory: {berries: 4}}
  - {id: greta, name: Greta, sex: female, age_days: 380, traits: [fearful], skills: {foraging: 30.0}, inventory: {berries: 4}}
  - {id: hugo, name: Hugo, sex: male, age_days: 220, skills: {masonry: 25.0}, inventory: {berries: 4}}
  - {id: ines, name: Ines, sex: female, age_days: 240, traits: [rebellious], skills: {woodcutting: 20.0}, inventory: {berries: 4}}
  - {id: jory, name: Jory, sex: male, age_days: 170, skills: {foraging: 15.0, fishing: 10.0}, inventory: {berries: 4}}
  - {id: kaia, name: Kaia, sex: female, age_days: 135, traits: [industrious], skills: {hunting: 10.0}, inventory: {berries: 4}}
  - {id: lars, name: Lars, sex: male, age_days: 330, skills: {woodcutting: 10.0, masonry: 20.0}, inventory: {berries: 4}}
run:
  days: 60
  snapshot_every_days: 1
```

- [ ] **Step 2: Write the failing tests**

Create `tests/pericles/test_experiment_config.py`:

```python
import copy
from pathlib import Path
from typing import Any

import pytest

from pericles.core.content.registry import base_pack_path
from pericles.core.geometry import Coord
from pericles.experiment.config import ExperimentError, build_world, experiment_from_mapping, load_experiment
from pericles.experiment.defaults import default_agent_config, default_config

pytestmark = pytest.mark.req("REQ-EXP-001")
BASELINE = Path(__file__).parents[2] / "experiments" / "baseline.yaml"
MINIMAL: dict[str, Any] = {
    "seed": 3,
    "map": {
        "width": 24,
        "height": 24,
        "bands": [{"terrain": "grass", "share": 0.7}, {"terrain": "forest", "share": 0.3}],
        "start_terrain": "grass",
        "start_radius": 4,
        "feature_size": 8,
    },
    "population": [
        {"id": "a", "name": "A", "sex": "female", "age_days": 200, "skills": {"foraging": 5}},
        {"id": "b", "name": "B", "sex": "male", "age_days": 10, "inventory": {"berries": 3}, "model": "m"},
    ],
    "run": {"days": 2, "snapshot_every_days": 1},
}


def changed(path: str, value: object) -> dict[str, Any]:
    """MINIMAL with the dotted `path` (list indices as numbers) set to `value`; None deletes."""
    data = copy.deepcopy(MINIMAL)
    *parents, last = [int(p) if p.isdigit() else p for p in path.split(".")]
    node: Any = data
    for part in parents:
        node = node[part]
    if value is None:
        del node[last]
    else:
        node[last] = value
    return data


def test_the_baseline_experiment_loads(tmp_path: Path) -> None:
    """AC1: seed, map, packs, population, engine and agent parameters come from the file."""
    experiment = load_experiment(BASELINE)
    assert experiment.seed == 1
    assert experiment.packs == (base_pack_path(),)
    assert len(experiment.population) == 12
    assert experiment.engine == default_config()
    assert experiment.agents == default_agent_config()
    assert experiment.run.days == 60


def test_sections_override_the_packaged_defaults(tmp_path: Path) -> None:
    """AC1: engine and agents sections override the defaults key by key."""
    data = {**copy.deepcopy(MINIMAL), "engine": {"debug_invariants": True}, "agents": {"idle_ticks": 4}}
    experiment = experiment_from_mapping(data, tmp_path)
    assert experiment.engine.debug_invariants
    assert experiment.engine.calendar == default_config().calendar
    assert experiment.agents.idle_ticks == 4


def test_the_resolved_config_rebuilds_the_same_experiment(tmp_path: Path) -> None:
    """AC1: the run directory's config snapshot alone reproduces the experiment."""
    first = experiment_from_mapping(copy.deepcopy(MINIMAL), tmp_path)
    again = experiment_from_mapping(copy.deepcopy(first.resolved), tmp_path / "elsewhere")
    assert (again.seed, again.map, again.population, again.run) == (first.seed, first.map, first.population, first.run)
    assert (again.engine, again.agents, again.packs) == (first.engine, first.agents, first.packs)
    assert again.resolved == first.resolved


@pytest.mark.parametrize(
    ("data", "prefix"),
    [
        ({**MINIMAL, "sede": 1}, "sede: unknown section"),
        (changed("run", None), "run: missing"),
        (changed("seed", "x"), "seed: expected an integer"),
        (changed("seed", True), "seed: expected an integer"),
        ({**MINIMAL, "packs": ["no/such/pack"]}, "packs:"),
        ({**MINIMAL, "packs": "base"}, "packs: expected a non-empty list"),
        (changed("map.width", "64"), "map.width:"),
        (changed("map.bands", None), "map.bands: missing"),
        (changed("map.bands.0.colour", "red"), "map.bands[0].colour: unknown setting"),
        (changed("map.bands.0.terrain", "lava"), "map:"),
        (changed("population", {"a": 1}), "population: expected a list"),
        (changed("population.1.id", "a"), "population[1].id: duplicate id 'a'"),
        (changed("population.1.id", "Bad Id"), "population[1].id:"),
        (changed("population.0.age_days", "old"), "population[0].age_days:"),
        (changed("population.0.age", 3), "population[0].age:"),
        (changed("population.0.sex", "other"), "population[0].sex: must be one of"),
        (changed("population.0.traits", ["lazy"]), "population[0].traits[0]: unknown trait 'lazy'"),
        (changed("population.0.skills", {"juggling": 3}), "population[0].skills.juggling: unknown skill"),
        (changed("population.0.skills", {"foraging": 1000.0}), "population[0].skills.foraging: at most"),
        (changed("population.0.knowledge", ["warp"]), "population[0].knowledge[0]: unknown id 'warp'"),
        (changed("population.0.inventory", {"unobtainium": 1}), "population[0].inventory.unobtainium: unknown item"),
        (changed("population.0.inventory", {"stone": 11}), "population[0].inventory: weighs more than carry_limit"),
        (changed("run.days", 0), "run.days:"),
        ({**MINIMAL, "engine": {"carry_limit": "x"}}, "engine.carry_limit:"),
        ({**MINIMAL, "engine": {"sexes": ["x"]}}, "engine:"),
        ({**MINIMAL, "agents": {"house_building": "hut"}}, "agents.house_building: unknown building 'hut'"),
        ({**MINIMAL, "agents": {"store_building": "farm"}}, "agents.store_building: 'farm' has no storage"),
        ({**MINIMAL, "agents": {"house_building": "storehouse"}}, "agents.house_building: 'storehouse' has no housing"),
        ([1, 2], "experiment: expected a mapping"),
    ],
)
def test_errors_name_the_field(tmp_path: Path, data: object, prefix: str) -> None:
    """AC2: the config is validated at load; errors name the field and the problem."""
    with pytest.raises(ExperimentError) as caught:
        experiment_from_mapping(data, tmp_path)
    assert str(caught.value).startswith(prefix), str(caught.value)


def test_load_reports_bad_yaml(tmp_path: Path) -> None:
    """AC2: unreadable files are experiment errors too."""
    path = tmp_path / "e.yaml"
    path.write_text("seed: [1\n", encoding="utf-8")
    with pytest.raises(ExperimentError, match="invalid YAML"):
        load_experiment(path)


def test_build_world_places_the_population(tmp_path: Path) -> None:
    """AC1: villagers start near the centre, with their age, adulthood, model and belongings."""
    experiment = experiment_from_mapping(copy.deepcopy(MINIMAL), tmp_path)
    world = build_world(experiment)
    a, b = world.villagers["a"], world.villagers["b"]
    tpd = experiment.engine.calendar.ticks_per_day
    assert (a.born_tick, b.born_tick) == (-200 * tpd, -10 * tpd)
    assert a.adult and not b.adult
    assert b.model is None  # children get a model when they come of age
    assert b.inventory.count("berries") == 3
    assert a.skills == {"foraging": 5.0}
    centre = world.tilemap.start()
    assert a.pos != b.pos
    assert max(centre.manhattan(v.pos) for v in (a, b)) <= 1
    assert world.nodes and world.digest() == build_world(experiment).digest()
    assert isinstance(a.pos, Coord)
```

Run: `uv run pytest tests/pericles/test_experiment_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.experiment.config'`.

- [ ] **Step 3: Implement the loader and the world builder**

Create `src/pericles/experiment/config.py`:

```python
"""experiment.yaml → a validated Experiment, and its starting world (REQ-EXP-001; ADR-0016 §5)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from pericles.agents.config import AgentConfig
from pericles.core.config import EngineConfig
from pericles.core.content.loader import ContentError, read_yaml
from pericles.core.content.registry import Registry, base_pack_path, load_registry
from pericles.core.inventory import bundle_weight
from pericles.core.mapgen import Band, MapParams, Vein, generate_map, start_area, validate
from pericles.core.nodes import place_nodes
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_settings_mapping
from pericles.experiment.settings import (
    SettingsError,
    agent_config_from_mapping,
    as_mapping,
    engine_config_from_mapping,
    values_for,
)

SECTIONS = ("seed", "packs", "map", "population", "run", "engine", "agents")
REQUIRED = ("seed", "map", "population", "run")
BASE = "base"
ID = r"^[a-z][a-z0-9_]*$"


class ExperimentError(ValueError):
    """An experiment file is invalid; the message starts with the dotted field path."""


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VillagerSpec(_Spec):
    id: Annotated[StrictStr, Field(pattern=ID)]
    name: Annotated[StrictStr, Field(min_length=1)]
    sex: StrictStr | None = None
    age_days: Annotated[StrictInt, Field(ge=0)]
    traits: tuple[StrictStr, ...] = ()
    skills: dict[StrictStr, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)
    knowledge: tuple[StrictStr, ...] = ()
    model: StrictStr | None = None
    inventory: dict[StrictStr, Annotated[StrictInt, Field(gt=0)]] = Field(default_factory=dict)


class RunSpec(_Spec):
    days: Annotated[StrictInt, Field(gt=0)]
    snapshot_every_days: Annotated[StrictInt, Field(gt=0)]


@dataclass(frozen=True)
class Experiment:
    seed: int
    packs: tuple[Path, ...]
    map: MapParams
    population: tuple[VillagerSpec, ...]
    run: RunSpec
    engine: EngineConfig
    agents: AgentConfig
    registry: Registry
    resolved: dict[str, Any]


def _path(loc: Sequence[int | str]) -> str:
    return "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in loc)


def _pydantic(model: type[_Spec], data: object, where: str) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        raise ExperimentError(f"{where}{_path(first['loc'])}: {first['msg']}") from None


def _list(data: object, where: str) -> list[Any]:
    if not isinstance(data, list):
        raise ExperimentError(f"{where}: expected a list")
    return data


def _packs(data: object, base_dir: Path) -> tuple[Path, ...]:
    raw = [BASE] if data is None else data
    if not isinstance(raw, list) or not raw or not all(isinstance(p, str) for p in raw):
        raise ExperimentError("packs: expected a non-empty list of pack paths")
    return tuple(base_pack_path() if p == BASE else (base_dir / p).resolve() for p in raw)


def _registry(packs: tuple[Path, ...]) -> Registry:
    try:
        return load_registry(list(packs))
    except (ContentError, OSError) as error:
        raise ExperimentError(f"packs: {error}") from None


def _merged(section: str, data: object) -> dict[str, Any]:
    defaults = dict(default_settings_mapping()[section])
    overrides = {} if data is None else dict(as_mapping(data, section))
    return {**defaults, **overrides}


def _map(data: object, registry: Registry) -> MapParams:
    raw = as_mapping(data, "map")
    values = values_for(MapParams, raw, "map", nested={"bands", "veins"})

    def parts(key: str, cls: type[Any]) -> tuple[Any, ...]:
        items = _list(raw.get(key, []), f"map.{key}")
        return tuple(
            cls(**values_for(cls, as_mapping(item, f"map.{key}[{i}]"), f"map.{key}[{i}]", set()))
            for i, item in enumerate(items)
        )

    params = MapParams(**values, bands=parts("bands", Band), veins=parts("veins", Vein))
    try:
        validate(params, registry)
    except ValueError as error:
        raise ExperimentError(f"map: {error}") from None
    return params


def _check_agents(agents: AgentConfig, registry: Registry) -> None:
    for name, attribute in (("house_building", "housing"), ("store_building", "storage")):
        kind = getattr(agents, name)
        if kind not in registry.buildings:
            raise ExperimentError(f"agents.{name}: unknown building {kind!r}")
        if not getattr(registry.buildings[kind], attribute):
            raise ExperimentError(f"agents.{name}: {kind!r} has no {attribute}")


def _population(data: object, registry: Registry, engine: EngineConfig) -> tuple[VillagerSpec, ...]:
    skills = {a.skill for a in registry.actions.values() if a.skill} | {
        r.skill for r in registry.recipes.values() if r.skill
    }
    known = registry.all_ids()
    specs: list[VillagerSpec] = []
    for i, entry in enumerate(_list(data, "population")):
        where = f"population[{i}]"
        spec: VillagerSpec = _pydantic(VillagerSpec, entry, where)
        if any(s.id == spec.id for s in specs):
            raise ExperimentError(f"{where}.id: duplicate id {spec.id!r}")
        if spec.sex is not None and spec.sex not in engine.sexes:
            raise ExperimentError(f"{where}.sex: must be one of {engine.sexes}")
        for j, trait in enumerate(spec.traits):
            if trait not in registry.traits:
                raise ExperimentError(f"{where}.traits[{j}]: unknown trait {trait!r}")
        for skill in sorted(spec.skills):
            if skill not in skills:
                raise ExperimentError(f"{where}.skills.{skill}: unknown skill")
            if spec.skills[skill] > engine.max_skill:
                raise ExperimentError(f"{where}.skills.{skill}: at most max_skill {engine.max_skill}")
        for j, ident in enumerate(spec.knowledge):
            if ident not in known:
                raise ExperimentError(f"{where}.knowledge[{j}]: unknown id {ident!r}")
        for item in sorted(spec.inventory):
            if item not in registry.items:
                raise ExperimentError(f"{where}.inventory.{item}: unknown item")
        if bundle_weight(registry, spec.inventory) > engine.carry_limit:
            raise ExperimentError(f"{where}.inventory: weighs more than carry_limit {engine.carry_limit}")
        specs.append(spec)
    return tuple(specs)


def experiment_from_mapping(raw: object, base_dir: Path) -> Experiment:
    if not isinstance(raw, Mapping):
        raise ExperimentError("experiment: expected a mapping")
    for key in sorted(raw):
        if key not in SECTIONS:
            raise ExperimentError(f"{key}: unknown section")
    for key in REQUIRED:
        if key not in raw:
            raise ExperimentError(f"{key}: missing")
    seed = raw["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ExperimentError("seed: expected an integer")
    try:
        packs = _packs(raw.get("packs"), base_dir)
        registry = _registry(packs)
        engine_data = _merged("engine", raw.get("engine"))
        agents_data = _merged("agents", raw.get("agents"))
        engine = engine_config_from_mapping(engine_data, "engine")
        agents = agent_config_from_mapping(agents_data, "agents")
        _check_agents(agents, registry)
        params = _map(raw["map"], registry)
        population = _population(raw["population"], registry, engine)
        run: RunSpec = _pydantic(RunSpec, raw["run"], "run")
    except SettingsError as error:
        raise ExperimentError(str(error)) from None
    resolved = {
        "seed": seed,
        "packs": [str(p) for p in packs],
        "map": dict(as_mapping(raw["map"], "map")),
        "population": [spec.model_dump(mode="json", exclude_defaults=True) for spec in population],
        "run": run.model_dump(mode="json"),
        "engine": engine_data,
        "agents": agents_data,
    }
    return Experiment(seed, packs, params, population, run, engine, agents, registry, resolved)


def load_experiment(path: Path) -> Experiment:
    try:
        raw = read_yaml(path)
    except ContentError as error:
        raise ExperimentError(str(error)) from None
    return experiment_from_mapping(raw, path.parent)


def build_world(experiment: Experiment) -> WorldState:
    """Generate the map and nodes, and place the population near the centre (ADR-0016 §5)."""
    registry, engine = experiment.registry, experiment.engine
    tilemap = generate_map(experiment.seed, experiment.map, registry)
    centre = tilemap.start()
    spots = sorted(
        (
            c
            for c in start_area(tilemap.width, tilemap.height, experiment.map.start_radius)
            if registry.terrains[tilemap.terrain_at(c)].walkable
        ),
        key=lambda c: (centre.manhattan(c), c.y, c.x),
    )
    ticks = engine.calendar.ticks_per_day
    villagers = []
    for i, spec in enumerate(experiment.population):
        adult = spec.age_days >= engine.adult_age_days
        villager = Villager(
            spec.id,
            spec.name,
            spots[i % len(spots)],
            skills=dict(spec.skills),
            knowledge=set(spec.knowledge),
            traits=spec.traits,
            sex=spec.sex,
            born_tick=-spec.age_days * ticks,
            adult=adult,
            model=spec.model if adult else None,
        )
        for item, qty in sorted(spec.inventory.items()):
            villager.inventory.add(registry, item, qty)
        villagers.append(villager)
    nodes = place_nodes(experiment.seed, tilemap, registry)
    return WorldState.new(experiment.seed, tilemap, villagers, nodes)
```

Notes for the implementer:
- `"base"` is a pack alias, not a content id.
- `resolved["map"]` keeps the user's raw map mapping. Rebuilding from `resolved` must give the same `MapParams`, and the round-trip test checks this.
- `exclude_defaults=True` keeps the population entries short. It must not drop a field that matters, so the round-trip test compares `population`.
- If pydantic's `float` with `Field(ge=0)` accepts a numeric string such as `"5"` for a skill, that is acceptable, because the value is still a valid number. Do not loosen `age_days` or `inventory`, which are strict.
- A start area that has fewer walkable tiles than villagers stacks villagers on tiles. This is allowed: villagers may share tiles.
- If `validate` reports an unknown terrain with a different message than `map: …`, keep the `map:` prefix. It comes from this wrapper.

Run: `uv run pytest tests/pericles/test_experiment_config.py tests/pericles/test_mapgen.py tests/pericles/test_settings.py -q`
Expected: PASS.

- [ ] **Step 4: Run the gates and commit**

```bash
git add src/pericles experiments tests/pericles
git commit -m "feat(experiment): experiment.yaml with field-named errors, baseline village, world builder

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Metrics, the command line, and the baseline village

**Files:**
- Modify: `pyproject.toml`:
  - add `"pyarrow>=17"` to `dependencies`;
  - add `[project.scripts] pericles = "pericles.experiment.cli:main"`;
  - add the markers `perf` and `long`, and set `addopts = "--strict-markers -m 'not slow and not perf and not long'"`;
  - add a mypy override: `[[tool.mypy.overrides]] module = ["pyarrow", "pyarrow.*"] ignore_missing_imports = true`.
- Modify: `.github/workflows/ci.yml`. In the job that runs `uv run pytest`, add a step after it: `uv run pytest -m long`. Check the workflow file name with `ls .github/workflows`.
- Create: `src/pericles/analysis/metrics.py`, `src/pericles/experiment/launch.py`, `src/pericles/experiment/cli.py`
- Modify: `src/pericles/experiment/rundir.py`: `write_metrics`, `read_metrics`
- Test: `tests/pericles/test_metrics.py`, `tests/pericles/test_cli.py`, `tests/pericles/test_baseline.py`, `tests/pericles/test_core_boundaries.py`

**Interfaces:**
- Consumes: Tasks 7–9.
- Produces:
  - In `pericles.analysis.metrics`:
    - `Row(day: int, metric: str, value: float)`, frozen.
    - `ticks_per_day(config: Mapping[str, Any]) -> int`.
    - `daily_survival(config: Mapping[str, Any], events: Iterable[Event], last_tick: int | None) -> list[Row]`.
  - `RunDirectory.write_metrics(rows: Sequence[Row]) -> Path` and `RunDirectory.read_metrics() -> list[Row]`.
  - In `pericles.experiment.launch`:
    - `Session(run_dir, experiment, engine, state, controller)`.
    - `start(experiment, out: Path) -> Session`.
    - `reopen(out: Path) -> Session`.
    - `advance(session, days: int | None = None) -> WorldState`.
  - `pericles.experiment.cli.main(argv: Sequence[str] | None = None) -> int`.

- [ ] **Step 1: Add the dependency**

Run: `uv add "pyarrow>=17"`, then make the other `pyproject.toml` edits listed above, then run `uv sync`.
Expected: `uv run python -c "import pyarrow.parquet"` exits 0.

- [ ] **Step 2: Write the failing metrics tests**

Create `tests/pericles/test_metrics.py`:

```python
from pathlib import Path

import pytest

from pericles.analysis.metrics import Row, daily_survival
from pericles.core.events import Event
from pericles.experiment.rundir import RunDirectory

pytestmark = pytest.mark.req("REQ-EXP-003")
CONFIG = {
    "engine": {"calendar": {"day_minutes": 100, "tick_minutes": 10}, "adult_age_days": 50},
    "population": [{"id": "a", "age_days": 60}, {"id": "b", "age_days": 70}, {"id": "k", "age_days": 49}],
}


def by_day(rows: list[Row]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for row in rows:
        out.setdefault(row.day, {})[row.metric] = row.value
    return out


def test_daily_survival_counts_population_births_deaths_and_food() -> None:
    """AC1: daily metrics derive from the config and the event log alone."""
    events = [
        Event(3, 0, "ate", {"actor": "a", "nutrition": 30.0}),
        Event(5, 0, "born", {"child": "v9", "mother": "a"}),
        Event(12, 0, "came_of_age", {"villager": "k"}),
        Event(14, 0, "died", {"villager": "b", "cause": "cold"}),
        Event(14, 1, "died", {"villager": "v9", "cause": "starvation"}),
        Event(14, 2, "ate", {"actor": "a", "nutrition": 15.0}),
    ]
    days = by_day(daily_survival(CONFIG, events, last_tick=35))
    assert sorted(days) == [0, 1, 2, 3]
    assert days[0] == {"population": 4, "adults": 2, "children": 2, "births": 1, "deaths": 0, "food_eaten": 30.0}
    assert days[1]["population"] == 2 and days[1]["adults"] == 2 and days[1]["children"] == 0
    assert days[1]["deaths"] == 2 and days[1]["deaths.cold"] == 1 and days[1]["deaths.starvation"] == 1
    assert days[1]["food_eaten"] == 15.0
    assert days[3] == {"population": 2, "adults": 2, "children": 0, "births": 0, "deaths": 0, "food_eaten": 0.0}


def test_an_empty_log_reports_the_starting_village() -> None:
    """AC1: day 0 exists even before anything happens; no log, no rows."""
    assert by_day(daily_survival(CONFIG, [], last_tick=0))[0]["population"] == 3
    assert daily_survival(CONFIG, [], last_tick=None) == []


def test_metrics_round_trip_through_parquet(tmp_path: Path) -> None:
    """AC1: the run directory holds metrics.parquet."""
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 1}, seed=1)
    rows = [Row(0, "population", 3.0), Row(0, "deaths.cold", 1.0)]
    path = run_dir.write_metrics(rows)
    assert path.name == "metrics.parquet"
    assert run_dir.read_metrics() == rows
```

Add to `tests/pericles/test_core_boundaries.py`:

```python
@pytest.mark.req("REQ-EXP-003")
def test_analysis_reads_only_the_event_schema() -> None:
    """AC1: metrics derive from the event log and config, independent of the engine and agents."""
    import pericles.analysis

    root = Path(pericles.analysis.__file__).parent
    offenders = [
        f"{path.name}: {name}"
        for path in sorted(root.rglob("*.py"))
        for name in imported_modules(path, "pericles.analysis")
        if name.startswith("pericles") and not name.startswith(("pericles.core.events", "pericles.analysis"))
    ]
    assert offenders == []
```

Run: `uv run pytest tests/pericles/test_metrics.py tests/pericles/test_core_boundaries.py -q`
Expected: FAIL. `ModuleNotFoundError: No module named 'pericles.analysis.metrics'`.

- [ ] **Step 3: Implement the metrics**

Create `src/pericles/analysis/metrics.py`:

```python
"""Daily survival metrics from the resolved config and the event log (REQ-EXP-003; ADR-0016 §6)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pericles.core.events import Event

DEATHS = "deaths"


@dataclass(frozen=True)
class Row:
    day: int
    metric: str
    value: float


def ticks_per_day(config: Mapping[str, Any]) -> int:
    calendar = config["engine"]["calendar"]
    return int(calendar["day_minutes"]) // int(calendar["tick_minutes"])


def daily_survival(
    config: Mapping[str, Any], events: Iterable[Event], last_tick: int | None
) -> list[Row]:
    """Rows per day up to `last_tick`'s day: population, adults, children, births, deaths
    (and `deaths.<cause>`), food eaten. Events must come in tick order."""
    per_day = ticks_per_day(config)
    adult_age = int(config["engine"]["adult_age_days"])
    population = [(str(v["id"]), int(v["age_days"])) for v in config["population"]]
    adults = {vid for vid, age in population if age >= adult_age}
    children = {vid for vid, _ in population} - adults
    counts: Counter[str] = Counter()
    food = 0.0
    rows: list[Row] = []
    day = 0

    def close() -> None:
        nonlocal food
        rows.extend(
            [
                Row(day, "population", float(len(adults) + len(children))),
                Row(day, "adults", float(len(adults))),
                Row(day, "children", float(len(children))),
                Row(day, "births", float(counts["births"])),
                Row(day, DEATHS, float(counts[DEATHS])),
                Row(day, "food_eaten", food),
            ]
        )
        rows.extend(
            Row(day, key, float(n)) for key, n in sorted(counts.items()) if key.startswith(DEATHS + ".")
        )
        counts.clear()
        food = 0.0

    for event in events:
        while event.tick // per_day > day:
            close()
            day += 1
        data = event.data
        if event.kind == "born":
            children.add(str(data["child"]))
            counts["births"] += 1
        elif event.kind == "died":
            vid = str(data["villager"])
            adults.discard(vid)
            children.discard(vid)
            counts[DEATHS] += 1
            counts[f"{DEATHS}.{data['cause']}"] += 1
        elif event.kind == "came_of_age":
            vid = str(data["villager"])
            children.discard(vid)
            adults.add(vid)
        elif event.kind == "ate":
            food += float(data["nutrition"])
    if last_tick is None:
        return []
    while day <= last_tick // per_day:
        close()
        day += 1
    return rows
```

The test expects the `days[0]` dict to have exactly six keys, with no `deaths.*` keys on a day without deaths. `close` only adds cause rows that are present, so this holds.

In `src/pericles/experiment/rundir.py`, add `METRICS = "metrics.parquet"`, import `pyarrow as pa`, `pyarrow.parquet as pq` and `Row`, and add:

```python
    def write_metrics(self, rows: Sequence[Row]) -> Path:
        table = pa.table(
            {
                "day": pa.array([r.day for r in rows], pa.int64()),
                "metric": pa.array([r.metric for r in rows], pa.string()),
                "value": pa.array([r.value for r in rows], pa.float64()),
            }
        )
        target = self.path / METRICS
        temporary = target.with_suffix(target.suffix + ".tmp")
        pq.write_table(table, temporary)
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_dir(self.path)
        return target

    def read_metrics(self) -> list[Row]:
        table = pq.read_table(self.path / METRICS)
        return [Row(int(r["day"]), str(r["metric"]), float(r["value"])) for r in table.to_pylist()]
```

Run: `uv run pytest tests/pericles/test_metrics.py tests/pericles/test_core_boundaries.py -q`
Expected: PASS.

- [ ] **Step 4: Write the failing CLI tests**

Create `tests/pericles/test_cli.py`:

```python
import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from pericles.experiment.cli import main
from pericles.experiment.rundir import RunDirectory

pytestmark = pytest.mark.req("REQ-EXP-003")
TINY: dict[str, Any] = {
    "seed": 5,
    "map": {
        "width": 24,
        "height": 24,
        "bands": [{"terrain": "grass", "share": 0.6}, {"terrain": "forest", "share": 0.3}, {"terrain": "rock", "share": 0.1}],
        "start_terrain": "grass",
        "start_radius": 4,
        "feature_size": 8,
    },
    "population": [
        {"id": "a", "name": "A", "sex": "female", "age_days": 200},
        {"id": "b", "name": "B", "sex": "male", "age_days": 200},
    ],
    "run": {"days": 2, "snapshot_every_days": 1},
    "engine": {
        "calendar": {
            "tick_minutes": 10,
            "day_minutes": 1440,
            "sunrise_minute": 360,
            "sunset_minute": 1200,
            "seasons": [{"name": "year", "days": 40}],
        }
    },
}


def write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "exp.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_run_writes_a_complete_run_directory(tmp_path: Path) -> None:
    """AC1: config snapshot, events, snapshots, llm_cache, metrics and meta."""
    out = tmp_path / "run"
    assert main(["run", str(write(tmp_path, TINY)), "--out", str(out), "--days", "1"]) == 0
    for name in ("config.yaml", "events.sqlite", "snapshots", "llm_cache", "metrics.parquet", "meta.json"):
        assert (out / name).exists(), name
    run_dir = RunDirectory.open(out)
    assert run_dir.config["engine"]["calendar"]["tick_minutes"] == 10
    assert {r.day for r in run_dir.read_metrics()} == {0, 1}
    run_dir.close()


def test_resume_continues_to_the_requested_day(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """AC3: a run directory can be continued from its last snapshot."""
    out = tmp_path / "run"
    main(["run", str(write(tmp_path, TINY)), "--out", str(out), "--days", "1"])
    assert main(["resume", str(out)]) == 0
    run_dir = RunDirectory.open(out)
    assert run_dir.event_log.last_tick() == 2 * 144 - 1
    assert max(r.day for r in run_dir.read_metrics()) == 2
    assert "Day 2" in capsys.readouterr().out
    run_dir.close()


def test_errors_exit_2_with_the_field_named(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """AC1: bad experiments and missing run directories are reported, not raised."""
    bad = copy.deepcopy(TINY)
    bad["population"][0]["traits"] = ["lazy"]
    assert main(["run", str(write(tmp_path, bad)), "--out", str(tmp_path / "x")]) == 2
    assert "population[0].traits[0]: unknown trait 'lazy'" in capsys.readouterr().err
    assert main(["resume", str(tmp_path / "nowhere")]) == 2
    assert "not a run directory" in capsys.readouterr().err


def test_an_extinct_village_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """AC1: a run whose population dies out stops and says when."""
    doomed = copy.deepcopy(TINY)
    doomed["engine"]["max_health"] = 0.001
    doomed["population"] = [{"id": "a", "name": "A", "age_days": 200}]
    doomed["agents"] = {"act_at": {"eat": 100.0, "sleep": 100.0, "shelter": 100.0}, "urgent_at": {"eat": 100.0, "sleep": 100.0, "shelter": 100.0}, "warm_until": 10.0}
    doomed["run"]["days"] = 30
    assert main(["run", str(write(tmp_path, doomed)), "--out", str(tmp_path / "run")]) == 0
    assert "died out on day" in capsys.readouterr().out
```

The extinct test gives the villager almost no health and never lets it act on hunger. It starves once hunger reaches critical: about 25 in-game hours at 4 per hour. If `EngineConfig` rejects `max_health: 0.001`, use the smallest value it accepts.

Run: `uv run pytest tests/pericles/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.experiment.cli'`.

- [ ] **Step 5: Implement launch and the CLI**

Create `src/pericles/experiment/launch.py`:

```python
"""Start, continue and advance a run directory from an experiment (ADR-0016 §5-§7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pericles.agents.controller import Controller
from pericles.agents.scripted import scripted_controller
from pericles.analysis.metrics import daily_survival
from pericles.core.engine import Engine
from pericles.core.state import WorldState
from pericles.experiment.config import Experiment, build_world, experiment_from_mapping
from pericles.experiment.rundir import RunDirectory
from pericles.experiment.runner import resume, run


@dataclass
class Session:
    run_dir: RunDirectory
    experiment: Experiment
    engine: Engine
    state: WorldState
    controller: Controller


def start(experiment: Experiment, out: Path) -> Session:
    run_dir = RunDirectory.create(out, experiment.resolved, seed=experiment.seed)
    engine = Engine(experiment.registry, experiment.engine)
    controller = scripted_controller(engine.context, experiment.agents)
    return Session(run_dir, experiment, engine, build_world(experiment), controller)


def reopen(out: Path) -> Session:
    run_dir = RunDirectory.open(out)
    experiment = experiment_from_mapping(run_dir.config, run_dir.path)
    engine = Engine(experiment.registry, experiment.engine)
    state, agents = resume(run_dir)
    controller = scripted_controller(engine.context, experiment.agents)
    controller.load(agents)
    return Session(run_dir, experiment, engine, state, controller)


def advance(session: Session, days: int | None = None) -> WorldState:
    """Run until `days` in-game days in total (default: run.days); then rewrite the metrics."""
    per_day = session.experiment.engine.calendar.ticks_per_day
    total = session.experiment.run.days if days is None else days
    session.state = run(
        session.run_dir,
        session.engine,
        session.state,
        session.controller,
        max(session.state.tick, total * per_day),
        session.experiment.run.snapshot_every_days * per_day,
    )
    log = session.run_dir.event_log
    rows = daily_survival(session.run_dir.config, log.events(), log.last_tick())
    session.run_dir.write_metrics(rows)
    return session.state
```

Create `src/pericles/experiment/cli.py`:

```python
"""`pericles run` and `pericles resume` (REQ-EXP-003; ADR-0016)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pericles.experiment.config import ExperimentError, load_experiment
from pericles.experiment.launch import advance, reopen, start
from pericles.experiment.rundir import RunDirectoryError

EXIT_ERROR = 2


def _days(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pericles", description="Run Pericles villages.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start a run from an experiment file")
    run.add_argument("experiment", type=Path)
    run.add_argument("--out", type=Path, required=True, help="a new, empty run directory")
    run.add_argument("--days", type=_days, help="total in-game days (default: run.days)")
    again = sub.add_parser("resume", help="continue a run from its last usable snapshot")
    again.add_argument("run_dir", type=Path)
    again.add_argument("--days", type=_days, help="total in-game days (default: run.days)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            session = start(load_experiment(args.experiment), args.out)
        else:
            session = reopen(args.run_dir)
    except (ExperimentError, RunDirectoryError) as error:
        print(f"pericles: {error}", file=sys.stderr)
        return EXIT_ERROR
    try:
        for path in session.run_dir.skipped:
            print(f"pericles: skipped unusable snapshot {path}", file=sys.stderr)
        state = advance(session, args.days)
    finally:
        session.run_dir.close()
    day = state.tick // session.experiment.engine.calendar.ticks_per_day
    if state.villagers:
        print(f"Day {day}: {len(state.villagers)} villagers.")
    else:
        print(f"The village died out on day {day}.")
    return 0
```

Run: `uv run pytest tests/pericles/test_cli.py -q`
Expected: PASS.

Then check the console entry point:
- Run: `uv run pericles run experiments/baseline.yaml --out /tmp/pericles-smoke --days 1`
- Expected: `Day 1: 12 villagers.` Delete the directory afterwards.

- [ ] **Step 6: Write the baseline-village tests**

Create `tests/pericles/test_baseline.py`:

```python
from pathlib import Path

import pytest

from pericles.experiment.config import load_experiment
from pericles.experiment.launch import advance, start

BASELINE = Path(__file__).parents[2] / "experiments" / "baseline.yaml"
WINTER_OVER = 41  # the default calendar: spring, summer, autumn, winter of 10 days each


def kinds(session_dir: Path) -> dict[str, list[dict[str, object]]]:
    from pericles.experiment.rundir import RunDirectory

    run_dir = RunDirectory.open(session_dir)
    found: dict[str, list[dict[str, object]]] = {}
    for event in run_dir.event_log.events():
        found.setdefault(event.kind, []).append(dict(event.data))
    run_dir.close()
    return found


@pytest.mark.long
@pytest.mark.req("REQ-AGT-008")
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_baseline_village_survives_its_first_winter(tmp_path: Path, seed: int) -> None:
    """AC1/AC2: the all-scripted baseline keeps everyone alive through winter."""
    experiment = load_experiment(BASELINE)
    experiment = type(experiment)(**{**experiment.__dict__, "seed": seed})
    session = start(experiment, tmp_path / "run")
    state = advance(session, WINTER_OVER)
    session.run_dir.close()
    events = kinds(tmp_path / "run")
    causes = [d["cause"] for d in events.get("died", [])]
    assert "starvation" not in causes and "cold" not in causes, causes
    assert any(b.complete for b in state.buildings.values())
    assert events.get("couple_formed")
    assert len(state.villagers) >= len(experiment.population)


@pytest.mark.long
@pytest.mark.req("REQ-AGT-008")
def test_the_baseline_village_grows(tmp_path: Path) -> None:
    """AC2: the baseline reproduces: children are born within the configured run."""
    experiment = load_experiment(BASELINE)
    session = start(experiment, tmp_path / "run")
    advance(session)
    session.run_dir.close()
    assert kinds(tmp_path / "run").get("born")
```

`WINTER_OVER` is a test constant. Derive it from `default_config().calendar` (`days_per_year + 1`) instead of hard-coding it.

Replacing the seed through `type(experiment)(**…)` keeps `resolved["seed"]` at 1. Use `dataclasses.replace(experiment, seed=seed, resolved={**experiment.resolved, "seed": seed})` instead.

- [ ] **Step 7: Run the baseline and tune the agent defaults**

Run: `uv run pytest -m long tests/pericles/test_baseline.py -q`
Expected: PASS.

If it fails, find out why from the event log, for example:
- villagers stuck on rejections,
- no house by winter,
- food demand never met,
- couples living apart.

Then fix it in this order:
1. **A rule is wrong** (it does something a reasonable villager would not). Fix the rule and add a unit test for the case in the matching `test_scripted_*.py`.
2. **Agent defaults.** Tune `AgentConfig` defaults *and* `default_settings.yaml`, keeping them in step. Record each change as a ruling in the report, with the before and after values.
3. **Engine or content values.** Do not change these. Report `DONE_WITH_CONCERNS` with the numbers. The user approves balance changes to the world.

- [ ] **Step 8: Run the gates and commit**

```bash
git add pyproject.toml uv.lock .github src/pericles tests/pericles
git commit -m "feat(experiment): daily metrics in metrics.parquet, pericles run/resume, baseline village tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Performance — 1000 ticks/s with 150 scripted villagers

**Files:**
- Create: `tools/pericles_tools/bench.py`, `tests/pericles/test_perf.py`, `tests/pericles/test_determinism_pin.py`
- Modify: `src/pericles/core/calendar.py`, `src/pericles/core/context.py`, `src/pericles/core/life.py`, plus whatever the profile shows next (core and agents only, with no change in behaviour)

**Interfaces:**
- Consumes: `experiment_from_mapping`, `build_world`, `scripted_controller`.
- Produces:
  - `pericles_tools.bench.perf_experiment(villagers: int = 150, size: int = 128) -> Experiment`.
  - `pericles_tools.bench.measure(villagers, size, warmup, ticks) -> float` (ticks per second).
  - `python -m pericles_tools.bench [--villagers N] [--size N] [--warmup N] [--ticks N] [--profile]`.
  - `Context.traits: Mapping[str, tuple[Modifier, ...]]`.

- [ ] **Step 1: Pin the event digest before optimising**

Create `tests/pericles/test_determinism_pin.py`:

```python
from pathlib import Path

import pytest
import yaml

from pericles.experiment.config import experiment_from_mapping
from pericles.experiment.launch import advance, start

TINY_PIN = """
seed: 7
map:
  width: 24
  height: 24
  bands:
    - {terrain: grass, share: 0.6}
    - {terrain: forest, share: 0.3}
    - {terrain: rock, share: 0.1}
  start_terrain: grass
  start_radius: 4
  feature_size: 8
population:
  - {id: a, name: A, sex: female, age_days: 200, inventory: {berries: 4}}
  - {id: b, name: B, sex: male, age_days: 200, inventory: {berries: 4}}
  - {id: c, name: C, sex: female, age_days: 200, inventory: {berries: 4}}
  - {id: d, name: D, sex: male, age_days: 200, inventory: {berries: 4}}
run: {days: 2, snapshot_every_days: 1}
"""
PINNED = "0" * 64  # replaced in Step 1 by the digest of the unoptimised code


@pytest.mark.req("REQ-NFR-003")
def test_optimisations_do_not_change_a_scripted_run(tmp_path: Path) -> None:
    """AC1: speed work must leave a pinned scripted run's event log byte-for-byte equal."""
    session = start(experiment_from_mapping(yaml.safe_load(TINY_PIN), tmp_path), tmp_path / "run")
    advance(session, 2)
    assert session.run_dir.event_log.digest() == PINNED
    session.run_dir.close()
```

Run: `uv run pytest tests/pericles/test_determinism_pin.py -q`
Expected: FAIL. The assertion shows the real digest on the right-hand side.

Copy that digest into `PINNED`. This is the pre-optimisation baseline: do it before touching any engine code. Then re-run.
Expected: PASS.

- [ ] **Step 2: Write the benchmark and the perf test**

Create `tools/pericles_tools/bench.py`:

```python
"""Engine + scripted-agent throughput (REQ-NFR-003; ADR-0016 §8)."""

from __future__ import annotations

import argparse
import cProfile
import pstats
import tempfile
import time
from pathlib import Path

from pericles.agents.scripted import scripted_controller
from pericles.core.engine import Engine
from pericles.experiment.config import Experiment, build_world, experiment_from_mapping

BASELINE = Path(__file__).resolve().parents[2] / "experiments" / "baseline.yaml"
SKILLS = ("foraging", "woodcutting", "masonry", "fishing", "hunting")
SEXES = ("female", "male")
AGES = (140, 200, 260, 320, 380)
SKILL_LEVEL = 20.0
PROFILE_ROWS = 20


def perf_experiment(villagers: int = 150, size: int = 128) -> Experiment:
    """The baseline village's map and settings at NFR-003 scale."""
    import yaml

    raw = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    raw["map"] = {**raw["map"], "width": size, "height": size}
    raw["population"] = [
        {
            "id": f"p{i:03d}",
            "name": f"P{i}",
            "sex": SEXES[i % len(SEXES)],
            "age_days": AGES[i % len(AGES)],
            "skills": {SKILLS[i % len(SKILLS)]: SKILL_LEVEL},
        }
        for i in range(villagers)
    ]
    with tempfile.TemporaryDirectory() as base:
        return experiment_from_mapping(raw, Path(base))


def measure(villagers: int = 150, size: int = 128, warmup: int = 2000, ticks: int = 3000) -> float:
    experiment = perf_experiment(villagers, size)
    engine = Engine(experiment.registry, experiment.engine)
    controller = scripted_controller(engine.context, experiment.agents)
    state = build_world(experiment)
    for _ in range(warmup):
        state, events = engine.step(state, controller.intents(state))
        controller.observe(state, events)
    started = time.perf_counter()
    for _ in range(ticks):
        state, events = engine.step(state, controller.intents(state))
        controller.observe(state, events)
    return ticks / (time.perf_counter() - started)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pericles_tools.bench")
    parser.add_argument("--villagers", type=int, default=150)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--warmup", type=int, default=2000)
    parser.add_argument("--ticks", type=int, default=3000)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    if args.profile:
        profile = cProfile.Profile()
        profile.enable()
    rate = measure(args.villagers, args.size, args.warmup, args.ticks)
    if args.profile:
        profile.disable()
        pstats.Stats(profile).sort_stats("cumulative").print_stats(PROFILE_ROWS)
    print(f"{rate:.0f} ticks/s ({args.villagers} villagers, {args.size}x{args.size})")


if __name__ == "__main__":
    main()
```

Create `tests/pericles/test_perf.py`:

```python
import pytest

from pericles_tools.bench import measure

REQUIRED_TICKS_PER_SECOND = 1000  # REQ-NFR-003 AC1


@pytest.mark.perf
@pytest.mark.req("REQ-NFR-003")
def test_the_engine_sustains_1000_ticks_per_second() -> None:
    """AC1: 150 scripted villagers on a 128x128 map, no LLM calls, on the target machine."""
    assert measure(villagers=150, size=128) >= REQUIRED_TICKS_PER_SECOND
```

Run: `PYTHONPATH=tools uv run python -m pericles_tools.bench`
Expected: it prints a rate. Write it down in the report as the "before" number.

- [ ] **Step 3: Cache the season and the trait modifiers**

In `src/pericles/core/calendar.py`, give `Calendar` a per-day season table built once:

```python
    _by_day: tuple[Season, ...] = field(init=False, repr=False, compare=False, default=())

    def __post_init__(self) -> None:
        # existing validation stays first
        ...
        table = tuple(season for season in self.seasons for _ in range(season.days))
        object.__setattr__(self, "_by_day", table)

    def season_at(self, tick: int) -> Season:
        if tick < 0:
            raise ValueError("tick must be non-negative")
        day = tick * self.tick_minutes // self.day_minutes
        return self._by_day[day % len(self._by_day)]
```

Keep `_locate` for `time_of`. The existing calendar tests must still pass.

In `src/pericles/core/context.py`, add `traits: Mapping[str, tuple[Modifier, ...]]` to `Context`. Fill it in `Context.build` from `registry.traits`, using `Modifier.from_def(m, f"trait:{trait}")`, the same source string `life.need_rate` uses today.

In `src/pericles/core/life.py`, compute rates through a per-tick cache:

```python
def rate_table(ctx: Context, state: WorldState) -> Callable[[Villager, NeedDef], float]:
    """Need rates for this tick; cached by (need, traits) when no modifier names a villager."""
    season = ctx.config.calendar.season_at(state.tick)
    shared = (*state.modifiers, *season.modifiers)
    personal = any(m.scope.villager is not None for m in shared)
    cache: dict[tuple[str, tuple[str, ...]], float] = {}

    def rate(villager: Villager, need: NeedDef) -> float:
        key = (need.id, villager.traits)
        if not personal and key in cache:
            return cache[key]
        modifiers = list(shared)
        for trait in villager.traits:
            modifiers.extend(ctx.traits[trait])
        value = resolve(
            modifiers,
            kind="need",
            ident=need.id,
            attribute="rate",
            base=need.rate_per_hour,
            tick=state.tick,
            villager=villager.id,
        ).value
        if not personal:
            cache[key] = value
        return value

    return rate


def need_rate(ctx: Context, state: WorldState, villager: Villager, need: NeedDef) -> float:
    """The need's per-hour rate after world, season and trait modifiers."""
    return rate_table(ctx, state)(villager, need)
```

In `update_needs`, build `rate = rate_table(ctx, state)` once and pass it to `_hourly_change` in place of the `need_rate` call. Keep the modifier order the same as today (world modifiers, then season, then traits): `resolve` may depend on order.

Run: `uv run pytest -q` and `uv run pytest tests/pericles/test_determinism_pin.py -q`
Expected: PASS, with the digest unchanged.

- [ ] **Step 4: Profile and iterate until the target is met**

Run: `PYTHONPATH=tools uv run python -m pericles_tools.bench --profile`

While the rate is below 1000, take the top cumulative hot spot in `pericles.core` or `pericles.agents` and remove the repeated work. Typical candidates:
- `View` queries recomputed per villager when they could be per tick, such as `housing_shortfall`, `storage_shortfall` and `stores`: cache them on the `View`.
- `Controller._due` calling `view.level` for each relief: read `villager.needs` through the precomputed relief map once.
- `construction.blocked_tiles` rebuilt every tick in `Engine._cost_field`: cache it on the building set's identity and size.
- `free_origin` sorting the whole search square: generate candidates in Manhattan rings instead.

After each change:
1. Run the full suite and the pinned-digest test. Both must pass, digest unchanged.
2. Re-run the bench.
3. Record the change and the new rate in the report as a ruling: `Ruling: optimised <what> — <rate before → after> — cost if wrong: <risk>`.

Do not change rules, parameters or content to gain speed. If the target cannot be reached without changing behaviour, stop and report `DONE_WITH_CONCERNS` with the profile.

- [ ] **Step 5: Run the perf test on this machine**

Run: `uv run pytest -m perf -q`
Expected: PASS. Put the measured ticks/s in the report.

- [ ] **Step 6: Run the gates, mutation-test core and agents, and commit**

```bash
git add src/pericles tools tests/pericles
git commit -m "perf: per-tick need-rate and season caches; 150 scripted villagers at >= 1000 ticks/s

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Whole-system property test, documentation and statuses

**Files:**
- Create: `tests/pericles/test_agent_fuzz.py`
- Modify:
  - `docs/requirements/agt.md`, `sim.md`, `exp.md`, `nfr.md` (statuses)
  - `docs/requirements/milestones.md` (M1 done)
  - `docs/requirements/traceability.md` (regenerated)
  - `README.md` (status and how to run a village)

- [ ] **Step 1: Write the property test**

Create `tests/pericles/test_agent_fuzz.py`:

```python
from collections.abc import Callable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pericles.agents.config import AgentConfig
from pericles.agents.scripted import scripted_controller
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

MakeWorld = Callable[..., WorldState]
ROWS = ["....TTTT....", "....TTTT.~~.", "...........~", "RR..........", "RR....~~....", "......~~...."] * 2
TICKS, SPLIT = 600, 300

person = st.tuples(
    st.sampled_from(["female", "male"]),
    st.sampled_from([30, 200, 400]),
    st.integers(0, 6),
    st.integers(0, 11),
    st.integers(0, 11),
)
spot = st.tuples(st.sampled_from(["berry_bush", "tree", "boulder"]), st.integers(0, 11), st.integers(0, 11))


@pytest.mark.req("REQ-AGT-008", "REQ-EXP-003")
@settings(max_examples=25, deadline=None)
@given(st.lists(person, min_size=1, max_size=6), st.lists(spot, max_size=12))
def test_scripted_villages_keep_invariants_and_resume_exactly(
    registry: Registry, make_world: MakeWorld, people: list[tuple[str, int, int, int, int]], spots: list[tuple[str, int, int]]
) -> None:
    """AGT-008 AC1 / EXP-003 AC3: any small scripted village keeps the engine invariants, and
    restoring world + agent memory mid-run reproduces the rest of the run exactly."""
    config = default_config(debug_invariants=True, adult_age_days=100)
    villagers = []
    for i, (sex, age, berries, x, y) in enumerate(people):
        v = Villager(f"v{i}", f"V{i}", Coord(x, y), sex=sex, born_tick=0, adult=age >= 100)
        v.inventory.add(registry, "berries", berries)
        villagers.append(v)
    parents = [v.id for v in villagers if v.adult][:2]
    for v in villagers:
        if not v.adult and parents:
            v.parents = tuple(sorted(parents))
    nodes = [Node(f"n{i}", kind, Coord(x, y), 10) for i, (kind, x, y) in enumerate(spots)]
    state = make_world(ROWS, villagers, nodes)
    engine = Engine(registry, config)
    controller = scripted_controller(engine.context, AgentConfig())
    saved = None
    tail: list[object] = []
    for tick in range(TICKS):
        if tick == SPLIT:
            saved = (state.to_dict(), controller.to_dict())
        state, events = engine.step(state, controller.intents(state))
        controller.observe(state, events)
        if tick >= SPLIT:
            tail.extend(e.to_dict() for e in events)
    assert saved is not None
    again = WorldState.from_dict(saved[0])
    other = scripted_controller(Engine(registry, config).context, AgentConfig())
    other.load(saved[1])
    engine2 = Engine(registry, config)
    replay: list[object] = []
    for _ in range(SPLIT, TICKS):
        again, events = engine2.step(again, other.intents(again))
        other.observe(again, events)
        replay.extend(e.to_dict() for e in events)
    assert replay == tail
```

The `make_world` fixture's `TERRAIN` mapping needs `R` (added in Task 5). Nodes may land on water tiles. That is allowed: villagers reach them from beside the water, and unreachable ones exercise the avoid path.

Run: `uv run pytest tests/pericles/test_agent_fuzz.py -q`
Expected: PASS. If Hypothesis finds a failing example, it is a real bug. Fix the cause in the agents or the controller, add the shrunk example as a unit test in the relevant `test_scripted_*.py`, and record it in the report.

- [ ] **Step 2: Update statuses and documents**

- Set REQ-AGT-008, REQ-SIM-016 and REQ-EXP-003 to `Implemented`.
- Set REQ-NFR-003 to `Implemented` only if Task 11's perf test passed on this machine. Otherwise leave it `Accepted` and say so in the report.
- Leave REQ-EXP-001 `Accepted`. It is an M4 requirement, and laws and interventions are still missing.
- In `docs/requirements/milestones.md`, set M1 `Done` to `yes`, but only if every M1 requirement is Implemented.
- Regenerate the matrix: `PYTHONPATH=tools uv run python -m pericles_tools.traceability matrix`.
- Update `README.md`. The status paragraph says M1 Headless sim is done. Add a short "Run a village" section:

  ```bash
  uv run pericles run experiments/baseline.yaml --out runs/baseline
  uv run pericles resume runs/baseline --days 90
  PYTHONPATH=tools uv run python -m pericles_tools.bench     # REQ-NFR-003 check
  uv run pytest -m long                                      # baseline village tests
  uv run pytest -m perf                                      # perf test (target machine)
  ```

- Add `runs/` to `.gitignore`.

Run: `PYTHONPATH=tools uv run python -m pericles_tools.traceability check` and `PYTHONPATH=tools uv run python -m pericles_tools.adr check`
Expected: both exit 0.

- [ ] **Step 3: Run every gate, including the long tests, and commit**

Run the six gates, then `uv run pytest -m long -q`, then `PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run --changed-since main`.
Expected: all pass; `pericles.core` ≥ 80% and `pericles.agents` ≥ 70%.

```bash
git add tests/pericles docs README.md .gitignore
git commit -m "test: scripted-village property test; docs: M1 done, statuses, how to run a village

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
