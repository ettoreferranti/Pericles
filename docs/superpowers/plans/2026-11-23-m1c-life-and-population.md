# M1c Life and Population Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give villagers a life cycle: needs, eating, sleeping, shelter, health and death; couples, pregnancy and births; children and coming of age; inheritance. Every parameter is settable from a settings file. The base pack adds a mill and a bakery.

**Architecture:**
- Two new core modules hold the life rules:
  - `pericles.core.life`: needs, eating, sleeping, shelter, health.
  - `pericles.core.lifecycle`: age, homes, couples, births, coming of age, death and inheritance.
- The engine calls them in a fixed order every tick and once per in-game day.
- Every number they use comes from `EngineConfig` (core defaults) or from content packs. `pericles.experiment.settings` loads the `engine:` section of a YAML settings file into an `EngineConfig`.
- The playable defaults move from Python into a packaged `default_settings.yaml`.
- A test rejects numeric literals in core outside the config classes and an allowlist of definitional constants.

**Tech Stack:** Python 3.12+, uv, pydantic v2 (settings validation), PyYAML, pytest, Hypothesis, mypy strict, ruff, mutmut.

**Spec:** `docs/superpowers/specs/2026-11-22-pericles-design.md` (§4.1, §4.3, §4.4, §4.2 base pack). Requirements: `docs/requirements/sim.md`, `docs/requirements/exp.md`. Decisions: `docs/adr/0013-engine-kernel-conventions.md`, `docs/adr/0014-gameplay-state-model.md`, and the new ADR-0015 written in Task 1.

**Requirements in scope:**

| Requirement | In this plan |
|---|---|
| REQ-SIM-003 AC2 | Winter need-rate modifiers (seasons now carry modifiers) |
| REQ-SIM-009 AC4 | Changed to include mill and bakery (approved 2026-11-23) |
| REQ-SIM-012 | All |
| REQ-SIM-015 | All |
| REQ-SIM-016 | AC2 and AC3. AC1 only partly: the engine limits children to allowed intents and light actions. The scripted child behaviour comes with REQ-AGT-008. |
| REQ-SIM-017 | All. Raid and epidemic deaths are recorded through the same `die` call that M4's god powers will use. |
| REQ-SIM-018 AC1 | Consumption (`ate`) and estate losses carry `destroyed` bundles, and the checker covers the new state |
| REQ-EXP-001 AC2 | Partly: the `engine:` section of a settings file is validated, and errors name the field |

**Follow-up plan M1d, "Running villages":**
- REQ-AGT-008 scripted utility AI, and with it REQ-SIM-016 AC1
- the full `experiment.yaml` (seed, map, packs, initial population) feeding the runner
- REQ-EXP-003 metrics
- REQ-NFR-003 engine performance
- the M1a snapshot-durability items: fsync, falling back past a corrupt snapshot, and the log-behind check

---

## Global Constraints

- Work on branch `m1c-life-population`, which the plan commit creates from `main`. Land it through a PR to `main`.
- `pericles.core` imports nothing from `pericles.agents`, `pericles.llm`, `pericles.experiment`, `pericles.server` or `pericles.analysis`. It never imports `time`, `datetime`, `uuid` or `secrets`. It contains no string literal equal to a base-pack content ID. Existing tests enforce all three.
- **No magic values** (the user's rule, 2026-11-23). Every simulation parameter is settable from a file:
  - Engine parameters are `EngineConfig` fields, loadable from a settings file's `engine:` section.
  - Game values are content-pack YAML.
  - Core code holds no other numeric literals except `0`, `1` and the allowlist in `tests/pericles/test_core_boundaries.py`; Task 2 adds the test that enforces this.
  - Any new parameter is added to `EngineConfig` **and** to `src/pericles/experiment/default_settings.yaml`. A test checks that the file lists every field.
- Determinism (ADR-0013):
  - All randomness comes from `WorldState.rng`.
  - Iterate dicts and sets in sorted order wherever the order can affect state or events.
  - Draws happen in a fixed order: intents shuffle, births, then the daily phase.
- Tick order (ADR-0015 §12):
  1. intents (sorted, then shuffled)
  2. work progress (sleep excluded)
  3. movement
  4. needs and health (deaths from needs)
  5. births that are due
  6. proposal expiry
  7. at a day boundary: regrowth, then old-age deaths, then coming of age, then conception
  8. witnessing
  9. modifier expiry
  10. `tick += 1`
  11. invariant check in debug mode
- Item conservation (ADR-0014 §4) still holds. Every event that creates or destroys items carries `created` and/or `destroyed` bundles, including `ate` and `estate_lost`. Moving items between containers (inheritance, estate storage) carries neither.
- Content models keep `extra="forbid"`, `frozen=True` and strict numerics. Content IDs match `^[a-z][a-z0-9_]*$`.
- Every test for a requirement carries `@pytest.mark.req("REQ-…")` (literal IDs) and names the AC in its docstring. Product tests live in `tests/pericles/`.
- Mutation score for `pericles.core` must be ≥ 80%. Each task mutates its own modules and adds tests for survivors. `# pragma: no mutate` is allowed only on a line where every possible mutant is equivalent, with the per-mutant reason given in the report.
- Gates before every commit, in order (never hide a gate's exit code behind a pipe):
  1. `uv run ruff format .`
  2. `uv run pytest -q`
  3. `uv run mypy`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Death in the middle of things.**
   - Cases: a villager dies while working (reserved inputs), while sleeping, while pregnant, while holding tools, while owning a shared building, or on the same tick that their partner dies or their child is born.
   - Expected: inputs return to the estate before inheritance. No item is lost without `estate_lost`. The partner is unlinked and the pregnancy ends with an event. Ownership never names a dead villager.
   - Tests: Task 5, and the Task 8 property test.
2. **Inheritance against the carry limit and store capacity.**
   - Cases: an estate larger than the heirs can carry and the communal stores can hold.
   - Expected: heirs never exceed the carry limit and stores never exceed capacity. The remainder is destroyed with `estate_lost`.
   - Tests: Task 5.
3. **Housing capacity under births.**
   - Cases: two couples in one house both conceiving on the same day; a birth into a full house.
   - Expected: pregnancies due in a home count against its capacity, so residents never exceed housing.
   - Tests: Task 6.
4. **Couple consent.**
   - Cases: accepting without a proposal, after the proposal expired, or a proposal to a child, a partnered villager, oneself or an unknown id.
   - Expected: each is rejected with a specific reason, and a couple forms only from a proposal plus a matching acceptance.
   - Tests: Task 6.
5. **Settings-file errors.**
   - Cases: an unknown key, a wrong type (a string or bool where a number belongs), a missing season field, a bad modifier, or a rule broken in `__post_init__`.
   - Expected: `SettingsError` naming the dotted field path, never a raw `TypeError` or `KeyError`.
   - Tests: Task 2.

---

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `docs/adr/0015-life-and-population.md` | Life, lifecycle and settings decisions | 1 |
| `src/pericles/core/config.py` | `EngineConfig` gains the life parameters | 1 |
| `src/pericles/core/calendar.py` | `Season.modifiers` | 1 |
| `src/pericles/core/content/schema.py`, `registry.py` | `NeedDef` gains `damage_per_hour`, `death_cause`, `relief`; registry rule | 1 |
| `src/pericles/core/content/loader.py` | `read_yaml` made public | 2 |
| `src/pericles/experiment/settings.py` | Settings file → `EngineConfig` | 2 |
| `src/pericles/experiment/default_settings.yaml` | The playable defaults, every engine parameter listed | 2 |
| `src/pericles/experiment/defaults.py` | Loads the default settings file | 2 |
| `src/pericles/core/mapgen.py` | Noise persistence, lacunarity and vein feature divisor become `MapParams` fields | 2 |
| `tests/pericles/test_core_boundaries.py` | No-magic-numbers test | 2 |
| `src/pericles/core/state.py` | Life fields on `Villager`; `Pregnancy`, `Proposal`, `Deceased`; new `WorldState` fields | 3 |
| `src/pericles/core/life.py` | Needs, eating, sleeping, shelter, health | 4 |
| `src/pericles/core/intents.py` | `Eat`, `Sleep`, `SetHome`, `ProposeCouple`, `AcceptCouple` | 4, 6 |
| `src/pericles/core/lifecycle.py` | Ages, homes, death, inheritance, couples, births, coming of age, witnessing | 5, 6, 7 |
| `src/pericles/core/engine.py` | Calls the life phases in the ADR-0015 order; child intent filter | 4–7 |
| `src/pericles/core/work.py` | Children limited to light actions | 7 |
| `src/pericles/core/invariants.py` | Checks for needs, health, couples, homes and the dead | 8 |
| `src/pericles/content/base/*.yaml` | Needs, mill, bakery, flour, bread, grain at nutrition 3, the `light` tag | 8 |
| `tests/pericles/conftest.py` | `LIFE_PACK` and the `life` fixture | 3 |

---
### Task 1: ADR-0015, life parameters, season modifiers, need definitions

**Files:**
- Create: `docs/adr/0015-life-and-population.md`
- Modify: `docs/adr/README.md` (index row)
- Modify: `src/pericles/core/config.py`
- Modify: `src/pericles/core/calendar.py` (`Season`)
- Modify: `src/pericles/core/content/schema.py` (`NeedDef`)
- Modify: `src/pericles/core/content/registry.py` (`check_references`)
- Test: `tests/pericles/test_config.py`, `tests/pericles/test_calendar.py`, `tests/pericles/test_registry.py`

**Interfaces:**
- Consumes: `Modifier` (M1a, `pericles.core.modifiers`), `Calendar` and `Season` (M1a/M1b), `EngineConfig` (M1b).
- Produces:
  - `config.MODEL_RULES = ("inherit", "fixed")`.
  - `EngineConfig` gains these fields, with the defaults shown in Step 3:
    - health and needs: `max_health`, `health_regen_per_hour`, `sleep_relief_per_hour`, `home_sleep_multiplier`, `shelter_relief_per_hour`
    - sex and age: `sexes`, `bearing_sex`, `adult_age_days`, `old_age_days`, `old_age_death_chance`, `old_age_death_growth`
    - births: `gestation_days`, `birth_interval_days`, `conception_chance_per_day`, `birth_food_per_capita`
    - couples and coming of age: `couple_proposal_ttl_ticks`, `model_rule`, `adult_model`, `child_names`
    - children and memory: `child_intents`, `child_action_tags`, `family_events`, `village_events`, `childhood_memory_limit`
  - Invalid values raise `ValueError` with one message per broken rule, joined by `"; "`. Non-finite floats are rejected.
  - `calendar.Season(name, days, blocked_tags=(), modifiers: tuple[Modifier, ...] = ())`.
  - `schema.NeedDef` gains `damage_per_hour: NonNegative = 0.0`, `death_cause: Id | None = None` and `relief: Literal["eat", "sleep", "shelter"] | None = None`.
  - Registry rule: a need with `damage_per_hour > 0` must name a `death_cause`.

- [ ] **Step 1: Write the ADR**

Create `docs/adr/0015-life-and-population.md`:

```markdown
# ADR-0015: Life and population

- **Status:** Accepted
- **Date:** 2026-11-23
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

M1c gives villagers a life cycle (REQ-SIM-003 AC2, REQ-SIM-012, -015, -016, -017, REQ-SIM-018 AC1): needs, health, death, couples, births, children, coming of age and inheritance. The spec (§4.3, §4.4) names these mechanics without fixing their rules. The user requires every parameter to be tweakable from a settings file (2026-11-23).

## Decision

1. **Needs are content.**
   - A need's level runs from 0 (satisfied) to its `critical` value.
   - Each tick, a need rises by its `rate` × hours per tick, then is clamped to 0…critical. The `rate` is resolved through the modifier system: target kind `need`, the need's id, attribute `rate`, base `rate_per_hour`. The current season's modifiers and the villager's trait modifiers take part.
   - A need's `relief` says what lowers it:
     - `eat`: eating an item lowers the need by the item's `nutrition` × quantity.
     - `sleep`: while sleeping, the need falls by `sleep_relief_per_hour` (× `home_sleep_multiplier` at home) instead of rising.
     - `shelter`: at home, the need falls by `shelter_relief_per_hour` instead of rising.
2. **Health** is `max_health − damage`.
   - Each need at its critical value adds `damage_per_hour` × hours per tick to the damage. With no need at critical, damage heals at `health_regen_per_hour`.
   - When the damage reaches `max_health` the villager dies. The cause is the `death_cause` of the first damaging critical need in id order.
   - A need that does damage must name a death cause (registry rule).
3. **Eating and sleeping.**
   - Eating is an instant intent (`Eat`). It destroys the food, and its `ate` event carries a `destroyed` bundle.
   - Sleeping is an activity of kind `sleep`. It ends by itself when every `sleep` need reaches 0 (event `woke`), or through the usual interruption.
4. **Homes.**
   - A villager's `home` is a completed building with `housing > 0`. It must be owned by the villager or their partner (communal counts), and have fewer residents than its housing.
   - "At home" means within reach of the home (ADR-0014 §6).
5. **Age.**
   - Age is counted in days from `born_tick`.
   - Adulthood is a flag: false at birth, and set by coming of age. Villagers created by an experiment are adults unless the experiment says otherwise.
   - Past `old_age_days`, the daily death probability is `min(1, old_age_death_chance × old_age_death_growth^(days past old_age_days))`.
6. **Couples need mutual consent.**
   - `ProposeCouple` records a proposal that lapses after `couple_proposal_ttl_ticks`. A matching `AcceptCouple` from the proposed villager forms the couple. M3 dialogue will issue these intents.
   - Couples last until a death.
   - Any two unpartnered adults may couple. Conception needs one partner of `bearing_sex` and one of another sex.
7. **Conception and birth.**
   - Once per day, each bearing adult with a living partner may conceive if all of these hold:
     - they share a completed home with free capacity, counting pregnancies due in that home;
     - the village food stock (the total nutrition held in inventories and stores) is at least `birth_food_per_capita` × population;
     - at least `birth_interval_days` have passed since their last birth;
     - a draw against `conception_chance_per_day` succeeds.

     Otherwise pregnancy does not start.
   - The child is born `gestation_days` later at the mother's position. Its home is the mother's, and its sex is drawn from `sexes`.
8. **Children** may only use the intents in `child_intents`. They may only start actions that carry a tag from `child_action_tags`. Anything else is rejected with `too_young`. Scripted child behaviour comes with the scripted AI (REQ-AGT-008, plan M1d).
9. **Coming of age** happens at the first day boundary after `adult_age_days`.
   - The model follows `model_rule`:
     - `inherit`: a parent's model, living or dead, chosen with the state RNG, falling back to `adult_model`;
     - `fixed`: `adult_model`.
   - The new adult's memories are the notable events they witnessed as a child, up to `childhood_memory_limit`, most recent kept. These are:
     - events of a `family_events` kind that name the child, a parent or a sibling;
     - every event of a `village_events` kind.
10. **Death and inheritance** go through one function, `lifecycle.die`, which god powers (raid, epidemic) will also call. It does these things in order:
    1. It interrupts work, so reserved inputs return to the estate.
    2. It ends a pregnancy and unlinks the partner.
    3. It drops the dead villager's proposals and moves them to `WorldState.dead`.
    4. It distributes the estate. Each item goes to the heirs in order (partner, then children, oldest first) as far as their carry limit allows. What is left goes to completed communal stores in id order, as far as their capacity allows. Any remainder is destroyed, recorded by `estate_lost` with a `destroyed` bundle.
    5. It reassigns buildings:
       - a personal building goes to the first heir, or becomes communal if there are no heirs;
       - a shared building drops the dead owner and adds the first heir if absent, then collapses to personal or communal as the owner count requires.
11. **No magic values.**
    - Engine parameters are `EngineConfig` fields, and the `engine:` section of a YAML settings file sets them (`pericles.experiment.settings`). The playable defaults live in the packaged `default_settings.yaml`, which lists every field.
    - Game values are content.
    - Core code contains no other numeric literals except 0, 1 and an allowlist of definitional constants, enforced by a test.
12. **Tick order:**
    1. intents
    2. work (sleep excluded)
    3. movement
    4. needs and health
    5. due births
    6. proposal expiry
    7. at a day boundary: regrowth, old-age deaths, coming of age, conception
    8. witnessing
    9. modifier expiry
    10. tick + 1

## Consequences

+ Every life rule is parameterised and testable through intents and the clock.
+ Death, births and inheritance keep the item ledger exact.
− Estates can lose items when heirs and stores are full. This is recorded, not hidden.
− Children's behaviour is inert until the scripted AI exists (M1d).
```

Add the index row after ADR-0014's row in `docs/adr/README.md`:

```markdown
| [0015](0015-life-and-population.md) | Life and population | Accepted |
```

Run: `PYTHONPATH=tools uv run python -m pericles_tools.adr check`
Expected: exit 0.

- [ ] **Step 2: Write the failing tests**

Append to `tests/pericles/test_config.py`:

```python
import math

from pericles.core.config import MODEL_RULES


def test_life_defaults_are_valid() -> None:
    """The core defaults describe a working life cycle."""
    config = EngineConfig()
    assert config.max_health == 100.0
    assert config.sexes == ("female", "male")
    assert config.bearing_sex == "female"
    assert config.model_rule == "inherit"
    assert config.adult_model is None
    assert config.child_intents == (
        "move_to",
        "wait",
        "start_action",
        "eat",
        "sleep",
        "take",
        "deposit",
    )
    assert config.child_action_tags == ("light",)
    assert MODEL_RULES == ("inherit", "fixed")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_health": 0.0}, "max_health must be positive"),
        ({"health_regen_per_hour": -1.0}, "relief and regeneration rates must be non-negative"),
        ({"sleep_relief_per_hour": -1.0}, "relief and regeneration rates must be non-negative"),
        ({"shelter_relief_per_hour": -1.0}, "relief and regeneration rates must be non-negative"),
        ({"home_sleep_multiplier": 0.5}, "home_sleep_multiplier must be at least 1"),
        ({"sexes": ()}, "sexes must be non-empty and unique"),
        ({"sexes": ("f", "f"), "bearing_sex": "f"}, "sexes must be non-empty and unique"),
        ({"bearing_sex": "other"}, "bearing_sex must be one of sexes"),
        ({"adult_age_days": 0}, "adult_age_days must be positive"),
        ({"old_age_days": 10, "adult_age_days": 20}, "old_age_days must be at least adult_age_days"),
        ({"old_age_death_chance": 1.5}, r"old_age_death_chance must be in \[0, 1\]"),
        ({"old_age_death_chance": -0.1}, r"old_age_death_chance must be in \[0, 1\]"),
        ({"old_age_death_growth": 0.9}, "old_age_death_growth must be at least 1"),
        ({"gestation_days": 0}, "gestation_days must be positive"),
        ({"birth_interval_days": -1}, "birth_interval_days must be non-negative"),
        ({"conception_chance_per_day": 2.0}, r"conception_chance_per_day must be in \[0, 1\]"),
        ({"birth_food_per_capita": -1.0}, "birth_food_per_capita must be non-negative"),
        ({"couple_proposal_ttl_ticks": 0}, "couple_proposal_ttl_ticks must be positive"),
        ({"model_rule": "random"}, r"model_rule must be one of \('inherit', 'fixed'\)"),
        ({"model_rule": "fixed"}, "model_rule 'fixed' needs adult_model"),
        ({"childhood_memory_limit": -1}, "childhood_memory_limit must be non-negative"),
        ({"carry_limit": math.inf}, "numeric parameters must be finite"),
        ({"max_health": math.nan}, "numeric parameters must be finite"),
    ],
)
def test_invalid_life_parameters_are_rejected(kwargs: dict[str, object], message: str) -> None:
    """Every life parameter is validated, with a message naming the rule."""
    with pytest.raises(ValueError, match=message):
        EngineConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"home_sleep_multiplier": 1.0},
        {"old_age_days": 120, "adult_age_days": 120},
        {"old_age_death_chance": 0.0},
        {"old_age_death_chance": 1.0},
        {"old_age_death_growth": 1.0},
        {"birth_interval_days": 0},
        {"conception_chance_per_day": 0.0},
        {"conception_chance_per_day": 1.0},
        {"birth_food_per_capita": 0.0},
        {"model_rule": "fixed", "adult_model": "m"},
        {"childhood_memory_limit": 0},
        {"health_regen_per_hour": 0.0, "sleep_relief_per_hour": 0.0, "shelter_relief_per_hour": 0.0},
    ],
)
def test_life_parameter_boundaries_are_accepted(kwargs: dict[str, object]) -> None:
    """The inclusive ends of each range are valid."""
    EngineConfig(**kwargs)  # type: ignore[arg-type]


def test_several_broken_rules_are_all_reported() -> None:
    """One message per broken rule, joined in rule order."""
    with pytest.raises(ValueError) as error:
        EngineConfig(max_health=0.0, gestation_days=0)
    assert str(error.value) == "max_health must be positive; gestation_days must be positive"
```

Append to `tests/pericles/test_calendar.py`:

```python
from pericles.core.modifiers import Modifier, Op, Target


def test_seasons_carry_modifiers() -> None:
    """Seasons hold the modifiers they apply (ADR-0015 §1); none by default."""
    assert Season("spring", 10).modifiers == ()
    cold = Modifier(Target("need", "cold"), "rate", Op.MUL, 4.0, "season:winter")
    winter = Season("winter", 10, blocked_tags=("sowing",), modifiers=(cold,))
    assert Calendar(seasons=(winter,)).season_at(0).modifiers == (cold,)
```

Append to `tests/pericles/test_registry.py` (it already builds packs from YAML text in its own helpers; reuse the helper the file uses for single-file packs, here called `pack_from`):

```python
def test_need_fields_parse(tmp_path: Path) -> None:
    """Needs carry damage, a death cause and a relief kind (ADR-0015 §1–§2)."""
    root = tmp_path / "p"
    root.mkdir()
    (root / "content.yaml").write_text(
        "needs:\n"
        "  - {id: hunger, rate_per_hour: 4, damage_per_hour: 5, death_cause: starvation, relief: eat}\n"
        "  - {id: fatigue, rate_per_hour: 6, relief: sleep}\n",
        encoding="utf-8",
    )
    registry = load_registry([root])
    hunger = registry.needs["hunger"]
    assert (hunger.damage_per_hour, hunger.death_cause, hunger.relief) == (5.0, "starvation", "eat")
    fatigue = registry.needs["fatigue"]
    assert (fatigue.damage_per_hour, fatigue.death_cause, fatigue.relief) == (0.0, None, "sleep")


def test_a_damaging_need_must_name_a_death_cause(tmp_path: Path) -> None:
    """A need that can kill must say what the death is called (ADR-0015 §2)."""
    root = tmp_path / "p"
    root.mkdir()
    (root / "content.yaml").write_text(
        "needs:\n  - {id: hunger, rate_per_hour: 4, damage_per_hour: 5}\n", encoding="utf-8"
    )
    with pytest.raises(ContentError, match=r"p: needs\[hunger\]\.death_cause: a need that does damage needs a death_cause"):
        load_registry([root])


def test_an_unknown_relief_kind_is_rejected(tmp_path: Path) -> None:
    """Relief is one of eat, sleep or shelter."""
    root = tmp_path / "p"
    root.mkdir()
    (root / "content.yaml").write_text(
        "needs:\n  - {id: hunger, rate_per_hour: 4, relief: pray}\n", encoding="utf-8"
    )
    with pytest.raises(ContentError, match="relief"):
        load_registry([root])
```

If `test_registry.py` lacks the imports, add `from pathlib import Path`, `from pericles.core.content.loader import ContentError` and `from pericles.core.content.registry import load_registry`. Wrap the long YAML literal lines in parentheses so ruff's E501 (100 columns) passes.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_config.py tests/pericles/test_calendar.py tests/pericles/test_registry.py -q`
Expected: FAIL. `MODEL_RULES` cannot be imported, `Season` takes no `modifiers`, and `NeedDef` rejects `damage_per_hour`.

- [ ] **Step 4: Implement**

Replace `src/pericles/core/config.py`:

```python
"""Engine parameters (ADR-0014, ADR-0015). Every field is settable from a settings file."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

from pericles.core.calendar import Calendar, Season

MODEL_RULES = ("inherit", "fixed")


def _neutral_calendar() -> Calendar:
    return Calendar(seasons=(Season("year", 40),))


@dataclass(frozen=True)
class EngineConfig:
    calendar: Calendar = field(default_factory=_neutral_calendar)
    carry_limit: float = 30.0
    max_skill: float = 100.0
    skill_practice: float = 1.0
    skill_speed_per_level: float = 0.005
    debug_invariants: bool = False
    # Health and needs (ADR-0015 §1-§3)
    max_health: float = 100.0
    health_regen_per_hour: float = 1.0
    sleep_relief_per_hour: float = 12.0
    home_sleep_multiplier: float = 2.0
    shelter_relief_per_hour: float = 20.0
    # Age, couples and births (ADR-0015 §5-§7)
    sexes: tuple[str, ...] = ("female", "male")
    bearing_sex: str = "female"
    adult_age_days: int = 120
    old_age_days: int = 600
    old_age_death_chance: float = 0.002
    old_age_death_growth: float = 1.02
    gestation_days: int = 10
    birth_interval_days: int = 10
    conception_chance_per_day: float = 0.2
    birth_food_per_capita: float = 50.0
    couple_proposal_ttl_ticks: int = 60
    # Children and coming of age (ADR-0015 §8-§9)
    model_rule: str = "inherit"
    adult_model: str | None = None
    child_names: tuple[str, ...] = ()
    child_intents: tuple[str, ...] = (
        "move_to",
        "wait",
        "start_action",
        "eat",
        "sleep",
        "take",
        "deposit",
    )
    child_action_tags: tuple[str, ...] = ("light",)
    family_events: tuple[str, ...] = ("born", "died", "couple_formed", "came_of_age")
    village_events: tuple[str, ...] = ("building_completed", "technology_learned")
    childhood_memory_limit: int = 20

    def __post_init__(self) -> None:
        problems = _problems(self)
        if problems:
            raise ValueError("; ".join(problems))


def _problems(c: EngineConfig) -> list[str]:
    floats = [getattr(c, f.name) for f in fields(c) if isinstance(getattr(c, f.name), float)]
    rates = (c.health_regen_per_hour, c.sleep_relief_per_hour, c.shelter_relief_per_hour)
    checks = [
        (all(math.isfinite(v) for v in floats), "numeric parameters must be finite"),
        (c.carry_limit > 0, "carry_limit must be positive"),
        (c.max_skill > 0, "max_skill must be positive"),
        (
            c.skill_practice >= 0 and c.skill_speed_per_level >= 0,
            "skill rates must be non-negative",
        ),
        (c.max_health > 0, "max_health must be positive"),
        (min(rates) >= 0, "relief and regeneration rates must be non-negative"),
        (c.home_sleep_multiplier >= 1, "home_sleep_multiplier must be at least 1"),
        (
            len(c.sexes) > 0 and len(set(c.sexes)) == len(c.sexes),
            "sexes must be non-empty and unique",
        ),
        (c.bearing_sex in c.sexes, "bearing_sex must be one of sexes"),
        (c.adult_age_days > 0, "adult_age_days must be positive"),
        (c.old_age_days >= c.adult_age_days, "old_age_days must be at least adult_age_days"),
        (0 <= c.old_age_death_chance <= 1, "old_age_death_chance must be in [0, 1]"),
        (c.old_age_death_growth >= 1, "old_age_death_growth must be at least 1"),
        (c.gestation_days > 0, "gestation_days must be positive"),
        (c.birth_interval_days >= 0, "birth_interval_days must be non-negative"),
        (0 <= c.conception_chance_per_day <= 1, "conception_chance_per_day must be in [0, 1]"),
        (c.birth_food_per_capita >= 0, "birth_food_per_capita must be non-negative"),
        (c.couple_proposal_ttl_ticks > 0, "couple_proposal_ttl_ticks must be positive"),
        (c.model_rule in MODEL_RULES, f"model_rule must be one of {MODEL_RULES}"),
        (
            c.model_rule != "fixed" or c.adult_model is not None,
            "model_rule 'fixed' needs adult_model",
        ),
        (c.childhood_memory_limit >= 0, "childhood_memory_limit must be non-negative"),
    ]
    return [message for ok, message in checks if not ok]
```

The finiteness check comes first, so a NaN never reaches a comparison that silently passes. The existing tests match single messages with `^…$`, and a single broken rule still produces exactly its own message.

In `src/pericles/core/calendar.py`, import `Modifier` and extend `Season`:

```python
from pericles.core.modifiers import Modifier


@dataclass(frozen=True)
class Season:
    name: str
    days: int
    blocked_tags: tuple[str, ...] = ()
    modifiers: tuple[Modifier, ...] = ()
```

In `src/pericles/core/content/schema.py`, replace `NeedDef`:

```python
class NeedDef(Model):
    id: Id
    rate_per_hour: NonNegative
    critical: Float = Field(default=100.0, gt=0, le=100)
    damage_per_hour: NonNegative = 0.0
    death_cause: Id | None = None
    relief: Literal["eat", "sleep", "shelter"] | None = None
```

In `check_references` (`src/pericles/core/content/registry.py`), add after the node checks:

```python
    for ident, need in registry.needs.items():
        if need.damage_per_hour > 0 and need.death_cause is None:
            problems.append(
                f"{where('needs', ident, 'death_cause')}: a need that does damage needs a "
                "death_cause"
            )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles/test_config.py tests/pericles/test_calendar.py tests/pericles/test_registry.py -q`
Expected: PASS.

- [ ] **Step 6: Mutation testing**

Run: `uv run mutmut run "pericles.core.config.*"` and `uv run mutmut run "pericles.core.content.registry.*"`, then `uv run mutmut results`.
Expected: no survivors in the new code. Kill any survivor with a test, and report the counts.

- [ ] **Step 7: Gates and commit**

Run the five gates, plus `PYTHONPATH=tools uv run python -m pericles_tools.traceability check` and `PYTHONPATH=tools uv run python -m pericles_tools.adr check`.

```bash
git add docs/adr src/pericles/core tests/pericles
git commit -m "feat(core): ADR-0015 and life parameters, season modifiers, need definitions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Settings files and the no-magic-values guard

**Files:**
- Modify: `src/pericles/core/content/loader.py` (rename `_read_yaml` → `read_yaml`)
- Create: `src/pericles/experiment/settings.py`
- Create: `src/pericles/experiment/default_settings.yaml`
- Modify: `src/pericles/experiment/defaults.py`
- Modify: `src/pericles/core/mapgen.py` (`MapParams.persistence`, `lacunarity`, `vein_feature_divisor`; `value_noise` keyword arguments)
- Modify: `tests/pericles/test_mapgen.py` (`value_noise` calls)
- Test: `tests/pericles/test_settings.py` (new), `tests/pericles/test_core_boundaries.py`

**Interfaces:**
- Consumes: `EngineConfig`, `Calendar`, `Season` (Task 1); `ModifierDef` (schema); `Modifier.from_def` (M1a); `ContentError`.
- Produces:
  - `loader.read_yaml(file: Path) -> dict[str, Any]`, public. It rejects duplicate keys and requires a top-level mapping, raising `ContentError`.
  - In `pericles.experiment.settings`:
    - `class SettingsError(ValueError)`
    - `engine_config_from_mapping(data: object, where: str = "engine") -> EngineConfig`
    - `load_settings(path: Path) -> EngineConfig`, which reads the `engine:` section; other top-level keys are errors.
  - `pericles.experiment.defaults`:
    - `DEFAULT_SETTINGS: Path`
    - `default_config(**overrides) -> EngineConfig`, loaded from `default_settings.yaml` then `dataclasses.replace`d
    - `DEFAULT_CALENDAR = default_config().calendar`
  - `MapParams` gains `persistence: float = 0.5`, `lacunarity: int = 2` and `vein_feature_divisor: int = 2`. The defaults equal the old constants, so every map digest is unchanged.
  - `value_noise(rng, width, height, feature_size, octaves, *, persistence, lacunarity)`.

- [ ] **Step 1: Write the failing settings tests**

Create `tests/pericles/test_settings.py`:

```python
import dataclasses
from pathlib import Path

import pytest
import yaml

from pericles.core.config import EngineConfig
from pericles.core.modifiers import Modifier, Op, Target
from pericles.experiment.defaults import DEFAULT_CALENDAR, DEFAULT_SETTINGS, default_config
from pericles.experiment.settings import SettingsError, engine_config_from_mapping, load_settings


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.req("REQ-EXP-001")
def test_settings_set_engine_parameters(tmp_path: Path) -> None:
    """AC2: a settings file sets engine parameters; omitted ones keep the core default."""
    path = write(
        tmp_path,
        "engine:\n"
        "  carry_limit: 12\n"
        "  sexes: [a, b]\n"
        "  bearing_sex: b\n"
        "  adult_model: llama\n"
        "  debug_invariants: true\n",
    )
    config = load_settings(path)
    assert config.carry_limit == 12.0
    assert isinstance(config.carry_limit, float)
    assert config.sexes == ("a", "b")
    assert config.bearing_sex == "b"
    assert config.adult_model == "llama"
    assert config.debug_invariants is True
    assert config.max_health == EngineConfig().max_health


@pytest.mark.req("REQ-EXP-001")
def test_settings_build_a_calendar_with_season_modifiers(tmp_path: Path) -> None:
    """AC2: seasons, blocked tags and season modifiers come from the file."""
    path = write(
        tmp_path,
        "engine:\n"
        "  calendar:\n"
        "    day_minutes: 60\n"
        "    sunrise_minute: 10\n"
        "    sunset_minute: 50\n"
        "    seasons:\n"
        "      - {name: warm, days: 2}\n"
        "      - name: cold\n"
        "        days: 3\n"
        "        blocked_tags: [sowing]\n"
        "        modifiers:\n"
        "          - {target: {kind: need, id: cold}, attribute: rate, op: mul, value: 4}\n",
    )
    calendar = load_settings(path).calendar
    assert calendar.day_minutes == 60
    assert [s.name for s in calendar.seasons] == ["warm", "cold"]
    cold = calendar.seasons[1]
    assert cold.blocked_tags == ("sowing",)
    assert cold.modifiers == (
        Modifier(Target("need", "cold"), "rate", Op.MUL, 4.0, "season:cold"),
    )


@pytest.mark.req("REQ-EXP-001")
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("engine:\n  carry_limt: 3\n", r"^engine\.carry_limt: unknown setting$"),
        ("engine:\n  carry_limit: heavy\n", r"^engine\.carry_limit: "),
        ("engine:\n  carry_limit: true\n", r"^engine\.carry_limit: "),
        ("engine:\n  gestation_days: 2.5\n", r"^engine\.gestation_days: "),
        ("engine:\n  sexes: a\n", r"^engine\.sexes: "),
        ("engine:\n  carry_limit: 0\n", r"^engine: carry_limit must be positive$"),
        ("engine:\n  calendar: {seasons: [{days: 3}]}\n", r"^engine\.calendar\.seasons\[0\]\.name: missing$"),
        ("engine:\n  calendar: {}\n", r"^engine\.calendar\.seasons: missing$"),
        ("engine:\n  calendar: {seasons: [{name: a, days: 0}]}\n", r"^engine\.calendar: every season must last at least one day$"),
        ("engine:\n  calendar: {seasons: [x]}\n", r"^engine\.calendar\.seasons\[0\]: expected a mapping$"),
        ("engine:\n  calendar: {seasons: [{name: a, days: 3, modifiers: [{attribute: rate}]}]}\n", r"^engine\.calendar\.seasons\[0\]\.modifiers\.0\.target: "),
        ("engine:\n  calendar: {seasons: [{name: a, days: 3, colour: red}]}\n", r"^engine\.calendar\.seasons\[0\]\.colour: unknown setting$"),
        ("engine: 3\n", r"^engine: expected a mapping$"),
        ("map: {}\n", r"^map: unknown section$"),
        ("engine: {carry_limit: 1}\nengine: {carry_limit: 2}\n", r"duplicate key 'engine'"),
    ],
)
def test_settings_errors_name_the_field(tmp_path: Path, text: str, message: str) -> None:
    """AC2: errors name the field and the problem; no raw TypeError or KeyError escapes."""
    with pytest.raises(SettingsError, match=message):
        load_settings(write(tmp_path, text))


def test_an_empty_settings_file_gives_core_defaults(tmp_path: Path) -> None:
    """No engine section means every parameter keeps its core default."""
    assert load_settings(write(tmp_path, "")) == EngineConfig()


def test_engine_config_from_mapping_takes_a_where_prefix() -> None:
    """Callers embedding the engine section elsewhere get their own path in errors."""
    with pytest.raises(SettingsError, match=r"^experiment\.engine\.x: unknown setting$"):
        engine_config_from_mapping({"x": 1}, where="experiment.engine")


def test_default_settings_list_every_engine_parameter() -> None:
    """No magic values: every EngineConfig field is spelled out in the default settings file."""
    raw = yaml.safe_load(DEFAULT_SETTINGS.read_text(encoding="utf-8"))
    assert sorted(raw["engine"]) == sorted(f.name for f in dataclasses.fields(EngineConfig))
    calendar_fields = {"seasons", "tick_minutes", "day_minutes", "sunrise_minute", "sunset_minute"}
    assert set(raw["engine"]["calendar"]) == calendar_fields


def test_default_config_is_the_four_season_year() -> None:
    """The playable default is four 10-day seasons; winter blocks sowing."""
    assert [(s.name, s.days) for s in DEFAULT_CALENDAR.seasons] == [
        ("spring", 10),
        ("summer", 10),
        ("autumn", 10),
        ("winter", 10),
    ]
    assert DEFAULT_CALENDAR.seasons[3].blocked_tags == ("sowing",)
    assert default_config(carry_limit=5.0).carry_limit == 5.0
    assert default_config().calendar == DEFAULT_CALENDAR
```

The parametrised cases with long literals must be wrapped to 100 columns. Put each long `text` on its own line inside parentheses.

- [ ] **Step 2: Write the failing guard test**

Append to `tests/pericles/test_core_boundaries.py`:

```python
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
                if child.value not in (0, 1):
                    found.append((".".join(scope) or "<module>", child.value, child.lineno))
            else:
                visit(child, scope)

    visit(ast.parse(path.read_text(encoding="utf-8")), [])
    return found


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
```

`life.py` does not exist until Task 4. An allowlist entry for a missing file is harmless.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_settings.py tests/pericles/test_core_boundaries.py -q`
Expected:
- FAIL with `ModuleNotFoundError: pericles.experiment.settings`.
- The guard test fails, listing `mapgen.py` literals in `value_noise` (`0.5`, and the `2` of `cell //= 2`) and in `generate_map` (`feature_size // 2`).

If the guard lists literals the allowlist does not explain, read each one. Either move it to a parameter (the preferred fix), or, if it is truly definitional, add it to the allowlist with a reason and say so in the report.

- [ ] **Step 4: Make mapgen's tuning constants parameters**

In `src/pericles/core/mapgen.py`, extend `MapParams`:

```python
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
    persistence: float = 0.5
    lacunarity: int = 2
    vein_feature_divisor: int = 2
```

Add these checks to `_validate`, next to the existing `octaves` check:

```python
    if not 0 < params.persistence <= 1:
        raise ValueError("persistence must be in (0, 1]")
    if params.lacunarity < 1:
        raise ValueError("lacunarity must be at least 1")
    if params.vein_feature_divisor < 1:
        raise ValueError("vein_feature_divisor must be at least 1")
```

Change `value_noise` to take the two as keyword arguments and use them:

```python
def value_noise(
    rng: random.Random,
    width: int,
    height: int,
    feature_size: int,
    octaves: int,
    *,
    persistence: float,
    lacunarity: int,
) -> list[float]:
```

Inside the loop, replace `amplitude *= 0.5` with `amplitude *= persistence` and `cell //= 2` with `cell //= lacunarity`. In `generate_map`, pass `persistence=params.persistence, lacunarity=params.lacunarity` to both calls. Replace the vein call's `params.feature_size // 2` with `params.feature_size // params.vein_feature_divisor`.

In `tests/pericles/test_mapgen.py`, add `persistence=0.5, lacunarity=2` to the two `value_noise(...)` calls in `test_value_noise_golden_values`. Also add:

```python
@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"persistence": 0.0}, r"persistence must be in \(0, 1\]"),
        ({"persistence": 1.5}, r"persistence must be in \(0, 1\]"),
        ({"lacunarity": 0}, "lacunarity must be at least 1"),
        ({"vein_feature_divisor": 0}, "vein_feature_divisor must be at least 1"),
    ],
)
def test_noise_parameters_are_validated(
    map_params: MapParams, registry: Registry, change: dict[str, float], message: str
) -> None:
    """The noise tuning values are parameters, validated like the others."""
    with pytest.raises(ValueError, match=message):
        generate_map(7, dataclasses.replace(map_params, **change), registry)


def test_noise_parameters_change_the_map(map_params: MapParams, registry: Registry) -> None:
    """Persistence really feeds the noise (it is not a dead parameter)."""
    base = generate_map(7, map_params, registry).digest()
    rougher = generate_map(7, dataclasses.replace(map_params, persistence=0.9), registry).digest()
    assert rougher != base
```

(Add `import dataclasses` and the `Registry` import if they are missing.) The existing golden digests must not change, because the defaults equal the old constants.

- [ ] **Step 5: Implement the settings loader**

In `src/pericles/core/content/loader.py`, rename `_read_yaml` to `read_yaml` (keep its body and docstring) and update its one caller in `load_pack`.

Create `src/pericles/experiment/settings.py`:

```python
"""Settings files: every engine parameter, tweakable without code changes (ADR-0015 §11)."""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.loader import ContentError, read_yaml
from pericles.core.content.schema import ModifierDef
from pericles.core.modifiers import Modifier

SECTIONS = ("engine",)


class SettingsError(ValueError):
    """A settings file is invalid; the message starts with the dotted field path."""


def _mapping(data: object, where: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise SettingsError(f"{where}: expected a mapping")
    return data


def _values(cls: type[Any], data: Mapping[str, Any], where: str, nested: set[str]) -> dict[str, Any]:
    """Validate the scalar fields of a dataclass; `nested` fields are left to the caller."""
    hints = typing.get_type_hints(cls)
    fields = {f.name: f for f in dataclasses.fields(cls)}
    for key in sorted(data):
        if key not in fields:
            raise SettingsError(f"{where}.{key}: unknown setting")
    for name, f in fields.items():
        required = f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        if required and name not in data:
            raise SettingsError(f"{where}.{name}: missing")
    values: dict[str, Any] = {}
    for key in sorted(data):
        if key in nested:
            continue
        raw = data[key]
        value = tuple(raw) if isinstance(raw, list) else raw
        try:
            values[key] = TypeAdapter(hints[key]).validate_python(value, strict=True)
        except ValidationError as error:
            raise SettingsError(f"{where}.{key}: {error.errors()[0]['msg']}") from None
    return values


def _season(data: object, where: str) -> Season:
    season = _mapping(data, where)
    values = _values(Season, season, where, nested={"modifiers"})
    try:
        defs = TypeAdapter(tuple[ModifierDef, ...]).validate_python(
            tuple(season.get("modifiers", ()))
        )
    except ValidationError as error:
        first = error.errors()[0]
        loc = ".".join(str(part) for part in first["loc"])
        raise SettingsError(f"{where}.modifiers.{loc}: {first['msg']}") from None
    source = f"season:{values['name']}"
    return Season(**values, modifiers=tuple(Modifier.from_def(d, source) for d in defs))


def _calendar(data: object, where: str) -> Calendar:
    calendar = _mapping(data, where)
    values = _values(Calendar, calendar, where, nested={"seasons"})
    raw = calendar["seasons"]
    if not isinstance(raw, list):
        raise SettingsError(f"{where}.seasons: expected a list")
    seasons = tuple(_season(s, f"{where}.seasons[{i}]") for i, s in enumerate(raw))
    try:
        return Calendar(**values, seasons=seasons)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def engine_config_from_mapping(data: object, where: str = "engine") -> EngineConfig:
    engine = _mapping(data, where)
    values = _values(EngineConfig, engine, where, nested={"calendar"})
    if "calendar" in engine:
        values["calendar"] = _calendar(engine["calendar"], f"{where}.calendar")
    try:
        return EngineConfig(**values)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def load_settings(path: Path) -> EngineConfig:
    try:
        raw = read_yaml(path)
    except ContentError as error:
        raise SettingsError(str(error)) from None
    for key in sorted(raw):
        if key not in SECTIONS:
            raise SettingsError(f"{key}: unknown section")
    return engine_config_from_mapping(raw.get("engine", {}))
```

How it behaves:
- `strict=True` keeps the content packs' numeric rule: an int is a valid float, but bools and strings are never numbers.
- YAML lists are turned into tuples before the strict check, because strict tuple validation refuses lists.
- The duplicate-key case surfaces through `read_yaml`'s `ContentError`, whose message contains `duplicate key 'engine'`.
- `read_yaml` raises `ContentError` when the top level is not a mapping. For an empty file it returns `{}`.

`engine: 3` reaches `engine_config_from_mapping`, which takes `object` for that reason, and fails in `_mapping` with `engine: expected a mapping`.

- [ ] **Step 6: Move the playable defaults into a settings file**

Create `src/pericles/experiment/default_settings.yaml`. It lists every `EngineConfig` field with the core default, except the calendar, which is the four-season year:

```yaml
# Playable defaults for every engine parameter (ADR-0015 §11). Copy this file to tweak a run.
engine:
  calendar:
    tick_minutes: 1
    day_minutes: 1440
    sunrise_minute: 360
    sunset_minute: 1200
    seasons:
      - {name: spring, days: 10}
      - {name: summer, days: 10}
      - {name: autumn, days: 10}
      - {name: winter, days: 10, blocked_tags: [sowing]}
  carry_limit: 30.0
  max_skill: 100.0
  skill_practice: 1.0
  skill_speed_per_level: 0.005
  debug_invariants: false
  max_health: 100.0
  health_regen_per_hour: 1.0
  sleep_relief_per_hour: 12.0
  home_sleep_multiplier: 2.0
  shelter_relief_per_hour: 20.0
  sexes: [female, male]
  bearing_sex: female
  adult_age_days: 120
  old_age_days: 600
  old_age_death_chance: 0.002
  old_age_death_growth: 1.02
  gestation_days: 10
  birth_interval_days: 10
  conception_chance_per_day: 0.2
  birth_food_per_capita: 50.0
  couple_proposal_ttl_ticks: 60
  model_rule: inherit
  adult_model: null
  child_names: []
  child_intents: [move_to, wait, start_action, eat, sleep, take, deposit]
  child_action_tags: [light]
  family_events: [born, died, couple_formed, came_of_age]
  village_events: [building_completed, technology_learned]
  childhood_memory_limit: 20
```

Replace `src/pericles/experiment/defaults.py`:

```python
"""The playable defaults, read from the packaged settings file (ADR-0014 §10, ADR-0015 §11)."""

from __future__ import annotations

import dataclasses
from importlib.resources import files
from pathlib import Path
from typing import Any

from pericles.core.config import EngineConfig
from pericles.experiment.settings import load_settings

DEFAULT_SETTINGS = Path(str(files("pericles.experiment").joinpath("default_settings.yaml")))


def default_config(**overrides: Any) -> EngineConfig:
    return dataclasses.replace(load_settings(DEFAULT_SETTINGS), **overrides)


DEFAULT_CALENDAR = default_config().calendar
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles/test_settings.py tests/pericles/test_core_boundaries.py tests/pericles/test_mapgen.py tests/pericles/test_base_pack.py -q`
Expected: PASS. The mapgen golden digests and the existing base-pack season tests are unchanged.

- [ ] **Step 8: Mutation testing**

Run: `uv run mutmut run "pericles.core.mapgen.*"` and `uv run mutmut run "pericles.core.content.loader.*"`, then `uv run mutmut results`.
Expected: no new survivors. `pericles.experiment` is outside the mutation gate's packages, but its tests above still pin every branch.

- [ ] **Step 9: Gates and commit**

Run the five gates and the traceability check.

```bash
git add src/pericles tests/pericles
git commit -m "feat(experiment): settings files for every engine parameter; no-magic-numbers guard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 3: Life state on villagers and the world

**Files:**
- Modify: `src/pericles/core/state.py`
- Modify: `tests/pericles/conftest.py` (`LIFE_PACK`, `life` fixture)
- Test: `tests/pericles/test_state.py`

**Interfaces:**
- Consumes: `Villager`, `WorldState`, `Activity` (M1b); `Inventory`.
- Produces:
  - `state.Pregnancy(father: str, due_tick: int)`, a mutable dataclass with `to_dict`/`from_dict`.
  - `state.Proposal(target: str, expires_tick: int)`, frozen, with `to_dict`/`from_dict`.
  - `state.Deceased(id, name, sex: str | None, born_tick: int, died_tick: int, cause: str, parents: tuple[str, ...], model: str | None)`, frozen, with `to_dict`/`from_dict`.
  - `Villager` gains these fields, all defaulted:
    - `sex: str | None = None`
    - `born_tick: int = 0`
    - `adult: bool = True`
    - `needs: dict[str, float] = {}`
    - `damage: float = 0.0`
    - `home: str | None = None`
    - `partner: str | None = None`
    - `parents: tuple[str, ...] = ()`
    - `pregnancy: Pregnancy | None = None`
    - `last_birth_tick: int | None = None`
    - `model: str | None = None`
    - `witnessed: list[dict[str, Any]] = []`
    - `memories: list[dict[str, Any]] = []`
  - `WorldState` gains `dead: dict[str, Deceased] = {}`, `proposals: dict[str, Proposal] = {}` (keyed by proposer) and `next_villager: int = 0`.
  - `tests/pericles/conftest.py` gains:
    - `LIFE_PACK`, which is `ECON_PACK` plus:
      - needs: hunger, fatigue, cold
      - trait `hardy`
      - building `lodge` (housing 8, storage 50)
      - building `cabin` (housing 5)
      - action `glean` (tag `light`)
    - the session fixture `life`, a registry built from `LIFE_PACK`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/pericles/test_state.py`:

```python
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.state import Deceased, Pregnancy, Proposal, Villager, WorldState
from pericles.core.mapgen import TileMap


def full_villager() -> Villager:
    return Villager(
        "v1",
        "Ana",
        Coord(1, 2),
        inventory=Inventory({"berries": 2}),
        sex="female",
        born_tick=-500,
        adult=False,
        needs={"hunger": 12.5, "cold": 3.0},
        damage=4.0,
        home="b0",
        partner="v2",
        parents=("v7", "v8"),
        pregnancy=Pregnancy("v2", 900),
        last_birth_tick=100,
        model="llama",
        witnessed=[{"tick": 3, "kind": "born", "data": {"villager": "v1"}}],
        memories=[{"tick": 1, "kind": "died", "data": {"villager": "v9"}}],
    )


def test_life_fields_have_neutral_defaults() -> None:
    """A villager built without life fields is a healthy adult of unknown sex with no family."""
    villager = Villager("v1", "Ana", Coord(0, 0))
    assert villager.sex is None
    assert (villager.born_tick, villager.adult, villager.damage) == (0, True, 0.0)
    assert villager.needs == {} and villager.parents == () and villager.witnessed == []
    assert villager.home is None and villager.partner is None and villager.pregnancy is None
    assert villager.last_birth_tick is None and villager.model is None and villager.memories == []


def test_a_villager_with_life_fields_round_trips() -> None:
    """Snapshots keep every life field (REQ-EXP-003 AC3 resume needs the full state)."""
    villager = full_villager()
    data = villager.to_dict()
    assert list(data["needs"]) == ["cold", "hunger"]
    assert Villager.from_dict(data) == villager


def test_world_life_fields_round_trip() -> None:
    """The dead, open proposals and the id counter survive a snapshot."""
    tilemap = TileMap(2, 2, ["grass"] * 4, [0.0] * 4)
    state = WorldState.new(1, tilemap, [full_villager()])
    state.dead["v9"] = Deceased("v9", "Old", "male", -9000, 40, "old_age", ("v5",), "qwen")
    state.dead["v3"] = Deceased("v3", "Kid", None, 10, 20, "cold", (), None)
    state.proposals["v1"] = Proposal("v2", 70)
    state.next_villager = 12
    data = state.to_dict()
    assert [d["id"] for d in data["dead"]] == ["v3", "v9"]
    assert list(data["proposals"]) == ["v1"]
    restored = WorldState.from_dict(data)
    assert restored.dead == state.dead
    assert restored.proposals == state.proposals
    assert restored.next_villager == 12
    assert restored.digest() == state.digest()


@pytest.mark.parametrize(
    "change",
    [
        lambda v: setattr(v, "damage", 5.0),
        lambda v: v.needs.update(hunger=13.0),
        lambda v: setattr(v, "partner", None),
        lambda v: setattr(v, "adult", True),
        lambda v: setattr(v, "pregnancy", None),
        lambda v: setattr(v, "model", "qwen"),
        lambda v: v.witnessed.append({"tick": 4, "kind": "died", "data": {}}),
    ],
)
def test_life_fields_feed_the_digest(change: Callable[[Villager], object]) -> None:
    """Every life field is part of the canonical state."""
    tilemap = TileMap(2, 2, ["grass"] * 4, [0.0] * 4)
    before = WorldState.new(1, tilemap, [full_villager()])
    after = WorldState.new(1, tilemap, [full_villager()])
    change(after.villagers["v1"])
    assert after.digest() != before.digest()


def test_life_pack_loads(life: Registry) -> None:
    """The life test pack adds needs, a hardy trait, a lodge, a cabin and a light action."""
    assert sorted(life.needs) == ["cold", "fatigue", "hunger"]
    assert life.needs["hunger"].relief == "eat"
    assert life.buildings["lodge"].housing == 8
    assert "light" in life.actions["glean"].tags
```

Add `from collections.abc import Callable`, `import pytest` and `from pericles.core.content.registry import Registry` if `test_state.py` lacks them.

In `tests/pericles/conftest.py`, after `ECON_PACK`:

```python
LIFE_PACK = (
    ECON_PACK
    + """
needs:
  - {id: hunger, rate_per_hour: 60, damage_per_hour: 600, death_cause: starvation, relief: eat}
  - {id: fatigue, rate_per_hour: 60, relief: sleep}
  - {id: cold, rate_per_hour: 60, damage_per_hour: 300, death_cause: cold, relief: shelter}
"""
)
"""ECON_PACK plus needs. With 1-minute ticks every need rises by exactly 1 per tick, hunger does
10 damage per tick at critical and cold does 5, so tests can count ticks."""

LIFE_EXTRA = """
traits:
  - id: hardy
    description: Feels the cold less.
    modifiers:
      - {target: {kind: need, id: cold}, attribute: rate, op: mul, value: 0.5}
buildings:
  - {id: lodge, cost: {wood: 2}, build_work: 5, footprint: [2, 2], housing: 8, storage: 50}
  - {id: cabin, cost: {wood: 1}, build_work: 2, footprint: [1, 1], housing: 5}
actions:
  - {id: glean, duration_ticks: 2, outputs: {berries: 1}, location: {node: bush}, tags: [light]}
"""


@pytest.fixture(scope="session")
def life(tmp_path_factory: pytest.TempPathFactory) -> Registry:
    root = tmp_path_factory.mktemp("packs")
    base, extra = root / "life", root / "life_extra"
    base.mkdir()
    extra.mkdir()
    (base / "content.yaml").write_text(LIFE_PACK, encoding="utf-8")
    (extra / "content.yaml").write_text(LIFE_EXTRA, encoding="utf-8")
    return load_registry([base, extra])
```

`ECON_PACK` already has `traits`, `buildings` and `actions` sections. A YAML file cannot repeat a top-level key, so the extra definitions live in a second pack that layers on top; overriding nothing is fine.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_state.py -q`
Expected: FAIL with `ImportError: cannot import name 'Deceased'`.

- [ ] **Step 3: Implement**

In `src/pericles/core/state.py`, add after `Activity`:

```python
@dataclass
class Pregnancy:
    father: str
    due_tick: int

    def to_dict(self) -> dict[str, Any]:
        return {"father": self.father, "due_tick": self.due_tick}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Pregnancy:
        return cls(str(data["father"]), int(data["due_tick"]))


@dataclass(frozen=True)
class Proposal:
    """An open couple proposal to `target`, lapsing after `expires_tick` (ADR-0015 §6)."""

    target: str
    expires_tick: int

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "expires_tick": self.expires_tick}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Proposal:
        return cls(str(data["target"]), int(data["expires_tick"]))


@dataclass(frozen=True)
class Deceased:
    """What the world remembers of a dead villager: lineage and the model they ran on."""

    id: str
    name: str
    sex: str | None
    born_tick: int
    died_tick: int
    cause: str
    parents: tuple[str, ...]
    model: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "sex": self.sex,
            "born_tick": self.born_tick,
            "died_tick": self.died_tick,
            "cause": self.cause,
            "parents": list(self.parents),
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Deceased:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            sex=None if data["sex"] is None else str(data["sex"]),
            born_tick=int(data["born_tick"]),
            died_tick=int(data["died_tick"]),
            cause=str(data["cause"]),
            parents=tuple(str(p) for p in data["parents"]),
            model=None if data["model"] is None else str(data["model"]),
        )


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)
```

Extend `Villager`. Add the fields after `activity`, then extend `to_dict` and `from_dict`:

```python
    sex: str | None = None
    born_tick: int = 0
    adult: bool = True
    needs: dict[str, float] = field(default_factory=dict)
    damage: float = 0.0
    home: str | None = None
    partner: str | None = None
    parents: tuple[str, ...] = ()
    pregnancy: Pregnancy | None = None
    last_birth_tick: int | None = None
    model: str | None = None
    witnessed: list[dict[str, Any]] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)
```

Add these entries to the `to_dict` return value:

```python
            "sex": self.sex,
            "born_tick": self.born_tick,
            "adult": self.adult,
            "needs": dict(sorted(self.needs.items())),
            "damage": self.damage,
            "home": self.home,
            "partner": self.partner,
            "parents": list(self.parents),
            "pregnancy": None if self.pregnancy is None else self.pregnancy.to_dict(),
            "last_birth_tick": self.last_birth_tick,
            "model": self.model,
            "witnessed": [dict(record) for record in self.witnessed],
            "memories": [dict(record) for record in self.memories],
```

and these to `from_dict`'s constructor call (read `pregnancy` and `last_birth_tick` first, as `activity` is):

```python
            sex=_optional_str(data["sex"]),
            born_tick=int(data["born_tick"]),
            adult=bool(data["adult"]),
            needs={str(k): float(v) for k, v in data["needs"].items()},
            damage=float(data["damage"]),
            home=_optional_str(data["home"]),
            partner=_optional_str(data["partner"]),
            parents=tuple(str(p) for p in data["parents"]),
            pregnancy=None if pregnancy is None else Pregnancy.from_dict(pregnancy),
            last_birth_tick=None if last_birth is None else int(last_birth),
            model=_optional_str(data["model"]),
            witnessed=[dict(record) for record in data["witnessed"]],
            memories=[dict(record) for record in data["memories"]],
```

`_optional_str` must be defined above `Villager`. Move it next to the imports.

Extend `WorldState`:

```python
    dead: dict[str, Deceased] = field(default_factory=dict)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    next_villager: int = 0
```

In `to_dict` add:

```python
            "dead": [self.dead[k].to_dict() for k in sorted(self.dead)],
            "proposals": {k: self.proposals[k].to_dict() for k in sorted(self.proposals)},
            "next_villager": self.next_villager,
```

and in `from_dict`:

```python
            dead={d.id: d for d in (Deceased.from_dict(x) for x in data["dead"])},
            proposals={str(k): Proposal.from_dict(v) for k, v in data["proposals"].items()},
            next_villager=int(data["next_villager"]),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles -q`
Expected: PASS, the whole suite. Existing snapshot and digest tests compare states built the same way, so the extra keys do not break them.

- [ ] **Step 5: Mutation testing**

Run: `uv run mutmut run "pericles.core.state.*"`, then `uv run mutmut results`.
Expected: no survivors. A survivor in `to_dict` usually means a field missing from the round-trip test; add it to `full_villager`.

- [ ] **Step 6: Gates and commit**

```bash
git add src/pericles/core/state.py tests/pericles
git commit -m "feat(core): life state for villagers and the world

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Needs, eating, sleeping, shelter and health

**Files:**
- Create: `src/pericles/core/life.py`
- Modify: `src/pericles/core/intents.py` (`Eat`, `Sleep`)
- Modify: `src/pericles/core/engine.py` (handlers; skip sleep in `_advance_work`; call `life.update_needs`)
- Test: `tests/pericles/test_life.py` (new)

**Interfaces:**
- Consumes: `Context`, `reject` (M1b); `building_tiles`, `near`; `Modifier`, `resolve`; `NeedDef` (Task 1); `Activity`, `Villager`, `WorldState` with life fields (Task 3); the `life` fixture and `make_world` (Task 3, M1b).
- Produces:
  - Intents: `Eat(actor, item: str, qty: int = 1)`, kind `"eat"`, and `Sleep(actor)`, kind `"sleep"`.
  - In `pericles.core.life`:
    - `MINUTES_PER_HOUR = 60` and `SLEEP = "sleep"`
    - `per_tick(ctx, per_hour) -> float`, computed as `per_hour × tick_minutes / 60`, multiplying first so the test numbers stay exact
    - `need_rate(ctx, state, villager, need) -> float`, per hour
    - `at_home(ctx, state, villager) -> bool`
    - `sleeping(villager) -> bool`
    - `eat(ctx, state, intent, sink)` and `sleep(ctx, state, intent, sink)`, the handlers
    - `update_needs(ctx, state, sink) -> list[tuple[str, str]]`, which returns `(villager_id, cause)` for each villager whose damage reached `max_health`, in id order. Task 5 makes the engine kill them.
  - **Events:**
    - `ate {actor, item, qty, nutrition, destroyed}`
    - `fell_asleep {actor, at_home}`
    - `woke {actor}`
    - `need_critical {actor, need}`, emitted when a need reaches its critical value
  - **Rejection reasons for `eat`:** `unknown_item`, `not_food`, `bad_quantity`, `missing_items`.
  - The engine skips activities of kind `sleep` in `_advance_work` and calls `life.update_needs` after movement.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_life.py`:

```python
from collections.abc import Callable

import pytest

from pericles.core import life as life_rules
from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import Eat, Sleep, Wait
from pericles.core.inventory import Inventory
from pericles.core.modifiers import Modifier, Op, Target
from pericles.core.state import Villager, WorldState

ROWS = ["......", "......", "......"]
MakeWorld = Callable[..., WorldState]


def ana(**fields: object) -> Villager:
    return Villager("a", "Ana", Coord(0, 0), **fields)  # type: ignore[arg-type]


def lodge(state: WorldState, owner: str = "a") -> Building:
    building = Building("b0", "lodge", Coord(2, 0), Ownership("personal", (owner,)), complete=True)
    state.buildings["b0"] = building
    return building


def kinds(events: list) -> list[str]:  # type: ignore[type-arg]
    return [e.kind for e in events]


@pytest.mark.req("REQ-SIM-012")
def test_needs_rise_by_their_rate_every_tick(life: Registry, make_world: MakeWorld) -> None:
    """AC1: hunger, fatigue and cold rise per tick at their rates (1 per tick in the life pack)."""
    state = make_world(ROWS, [ana()])
    engine = Engine(life)
    for _ in range(3):
        engine.step(state, [])
    assert state.villagers["a"].needs == {"cold": 3.0, "fatigue": 3.0, "hunger": 3.0}


@pytest.mark.req("REQ-SIM-012")
def test_need_rates_are_modified_by_traits_and_world_modifiers(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: rates are the modified rates: a hardy trait halves cold; a world modifier adds."""
    state = make_world(ROWS, [ana(traits=("hardy",))])
    state.modifiers = (Modifier(Target("need", "hunger"), "rate", Op.ADD, 60.0, "test"),)
    Engine(life).step(state, [])
    assert state.villagers["a"].needs["cold"] == 0.5
    assert state.villagers["a"].needs["hunger"] == 2.0


@pytest.mark.req("REQ-SIM-003")
def test_winter_multiplies_need_rates(life: Registry, make_world: MakeWorld) -> None:
    """AC2: in winter the food and warmth need rates are multiplied by the winter modifiers."""
    winter_mods = (
        Modifier(Target("need", "hunger"), "rate", Op.MUL, 1.5, "season:winter"),
        Modifier(Target("need", "cold"), "rate", Op.MUL, 4.0, "season:winter"),
    )
    calendar = Calendar(
        seasons=(Season("summer", 1), Season("winter", 1, modifiers=winter_mods)),
        day_minutes=2,
        sunrise_minute=0,
        sunset_minute=1,
    )
    state = make_world(ROWS, [ana()])
    engine = Engine(life, EngineConfig(calendar=calendar))
    engine.step(state, [])
    engine.step(state, [])  # day 0 (summer): +1, +1
    assert state.villagers["a"].needs["cold"] == 2.0
    engine.step(state, [])  # day 1 (winter): cold +4, hunger +1.5
    assert state.villagers["a"].needs["cold"] == 6.0
    assert state.villagers["a"].needs["hunger"] == 3.5
    assert state.villagers["a"].needs["fatigue"] == 3.0


@pytest.mark.req("REQ-SIM-012")
def test_needs_stop_at_critical_and_report_it_once(life: Registry, make_world: MakeWorld) -> None:
    """AC1: a need never passes its critical value; reaching it is an event, once."""
    state = make_world(ROWS, [ana(needs={"fatigue": 99.5})])
    engine = Engine(life)
    _, events = engine.step(state, [])
    assert state.villagers["a"].needs["fatigue"] == 100.0
    assert [e.data for e in events if e.kind == "need_critical"] == [
        {"actor": "a", "need": "fatigue"}
    ]
    _, events = engine.step(state, [])
    assert "need_critical" not in kinds(events)
    assert state.villagers["a"].needs["fatigue"] == 100.0


@pytest.mark.req("REQ-SIM-012")
def test_a_critical_damaging_need_costs_health(life: Registry, make_world: MakeWorld) -> None:
    """AC2: hunger at 100 loses health at the starvation rate (10 per tick in the life pack)."""
    state = make_world(ROWS, [ana(needs={"hunger": 100.0})])
    ctx = Engine(life).context
    assert life_rules.update_needs(ctx, state, _sink()) == []
    assert state.villagers["a"].damage == 10.0
    for _ in range(8):
        life_rules.update_needs(ctx, state, _sink())
    assert state.villagers["a"].damage == 90.0
    assert life_rules.update_needs(ctx, state, _sink()) == [("a", "starvation")]


@pytest.mark.req("REQ-SIM-012")
def test_cold_kills_with_cause_cold(life: Registry, make_world: MakeWorld) -> None:
    """AC2: cold works the same way, with cause `cold` (5 damage per tick)."""
    state = make_world(ROWS, [ana(needs={"cold": 100.0}, damage=95.0)])
    ctx = Engine(life).context
    assert life_rules.update_needs(ctx, state, _sink()) == [("a", "cold")]


@pytest.mark.req("REQ-SIM-012")
def test_with_two_lethal_needs_the_first_in_id_order_is_the_cause(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: damage adds up; the cause is the first damaging critical need by id (cold < hunger)."""
    state = make_world(ROWS, [ana(needs={"cold": 100.0, "hunger": 100.0}, damage=86.0)])
    ctx = Engine(life).context
    assert life_rules.update_needs(ctx, state, _sink()) == [("a", "cold")]
    assert state.villagers["a"].damage == 101.0


@pytest.mark.req("REQ-SIM-012")
def test_health_recovers_when_no_need_is_critical(life: Registry, make_world: MakeWorld) -> None:
    """AC2: without a critical need, damage heals at the regeneration rate, never below 0."""
    state = make_world(ROWS, [ana(damage=0.5, needs={"fatigue": 100.0})])
    ctx = Engine(life, EngineConfig(health_regen_per_hour=60.0)).context
    life_rules.update_needs(ctx, state, _sink())
    assert state.villagers["a"].damage == 0.0  # fatigue does no damage, so it heals


@pytest.mark.req("REQ-SIM-012")
def test_eating_reduces_hunger_by_nutrition(life: Registry, make_world: MakeWorld) -> None:
    """AC3: eating consumes food and lowers hunger by nutrition × quantity, never below 0."""
    state = make_world(ROWS, [ana(needs={"hunger": 25.0}, inventory=Inventory({"berries": 3}))])
    _, events = Engine(life).step(state, [Eat("a", "berries", 2)])
    villager = state.villagers["a"]
    assert villager.inventory.count("berries") == 1
    assert villager.needs["hunger"] == 6.0  # 25 - 20, then +1 for the tick
    ate = next(e for e in events if e.kind == "ate")
    assert ate.data == {
        "actor": "a",
        "item": "berries",
        "qty": 2,
        "nutrition": 20.0,
        "destroyed": {"berries": 2},
    }
    Engine(life).step(state, [Eat("a", "berries")])
    assert villager.needs["hunger"] == 1.0  # floored at 0, then +1


@pytest.mark.req("REQ-SIM-012")
@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        (Eat("a", "stone"), "unknown_item"),
        (Eat("a", "wood"), "not_food"),
        (Eat("a", "berries", 0), "bad_quantity"),
        (Eat("a", "berries", 5), "missing_items"),
    ],
)
def test_bad_eat_intents_are_rejected(
    life: Registry, make_world: MakeWorld, intent: Eat, reason: str
) -> None:
    """AC3: only food the villager holds can be eaten; nothing is consumed otherwise."""
    state = make_world(ROWS, [ana(inventory=Inventory({"berries": 1, "wood": 1}))])
    _, events = Engine(life).step(state, [intent])
    assert [e.data["reason"] for e in events if e.kind == "intent_rejected"] == [reason]
    assert state.villagers["a"].inventory == Inventory({"berries": 1, "wood": 1})


@pytest.mark.req("REQ-SIM-012")
def test_sleeping_outdoors_restores_energy(life: Registry, make_world: MakeWorld) -> None:
    """AC3: while asleep fatigue falls by the sleep relief rate (1 per tick here) instead of rising."""
    state = make_world(ROWS, [ana(needs={"fatigue": 10.0})])
    engine = Engine(life, EngineConfig(sleep_relief_per_hour=60.0))
    _, events = engine.step(state, [Sleep("a")])
    assert [e.data for e in events if e.kind == "fell_asleep"] == [{"actor": "a", "at_home": False}]
    assert state.villagers["a"].needs["fatigue"] == 9.0
    assert state.villagers["a"].activity is not None
    assert state.villagers["a"].activity.kind == "sleep"


@pytest.mark.req("REQ-SIM-012")
def test_sleeping_at_home_is_faster(life: Registry, make_world: MakeWorld) -> None:
    """AC3: sleeping in a house restores energy faster than sleeping outdoors."""
    state = make_world(ROWS, [ana(needs={"fatigue": 10.0}, home="b0", pos=Coord(1, 0))])
    lodge(state)
    engine = Engine(life, EngineConfig(sleep_relief_per_hour=60.0, home_sleep_multiplier=3.0))
    _, events = engine.step(state, [Sleep("a")])
    assert [e.data for e in events if e.kind == "fell_asleep"] == [{"actor": "a", "at_home": True}]
    assert state.villagers["a"].needs["fatigue"] == 7.0


@pytest.mark.req("REQ-SIM-012")
def test_sleep_ends_when_rested(life: Registry, make_world: MakeWorld) -> None:
    """AC3: a sleeper wakes by themselves once every sleep need is at 0."""
    state = make_world(ROWS, [ana(needs={"fatigue": 1.5})])
    engine = Engine(life, EngineConfig(sleep_relief_per_hour=60.0))
    engine.step(state, [Sleep("a")])
    _, events = engine.step(state, [])
    assert state.villagers["a"].needs["fatigue"] == 0.0
    assert "woke" in kinds(events)
    assert state.villagers["a"].activity is None
    engine.step(state, [])
    assert state.villagers["a"].needs["fatigue"] == 1.0  # awake again, so it rises


@pytest.mark.req("REQ-SIM-012")
def test_any_intent_wakes_a_sleeper(life: Registry, make_world: MakeWorld) -> None:
    """AC3: sleep is an activity, so the usual interruption rule ends it (ADR-0014 §3)."""
    state = make_world(ROWS, [ana(needs={"fatigue": 50.0})])
    engine = Engine(life)
    engine.step(state, [Sleep("a")])
    _, events = engine.step(state, [Wait("a")])
    interrupted = next(e for e in events if e.kind == "work_interrupted")
    assert interrupted.data["work"] == "sleep"
    assert state.villagers["a"].activity is None


@pytest.mark.req("REQ-SIM-012")
def test_sleeping_stops_movement(life: Registry, make_world: MakeWorld) -> None:
    """AC3: a villager who lies down stops walking."""
    state = make_world(ROWS, [ana(path=[Coord(1, 0), Coord(2, 0)])])
    _, events = Engine(life).step(state, [Sleep("a")])
    assert "stopped" in kinds(events)
    assert state.villagers["a"].path == []
    assert state.villagers["a"].pos == Coord(0, 0)


@pytest.mark.req("REQ-SIM-012")
def test_shelter_at_home_lowers_cold(life: Registry, make_world: MakeWorld) -> None:
    """AC1: at home, cold falls by the shelter rate instead of rising; away, it rises."""
    state = make_world(ROWS, [ana(needs={"cold": 10.0}, home="b0", pos=Coord(1, 0))])
    lodge(state)
    engine = Engine(life, EngineConfig(shelter_relief_per_hour=120.0))
    engine.step(state, [])
    assert state.villagers["a"].needs["cold"] == 8.0
    state.villagers["a"].pos = Coord(5, 2)
    engine.step(state, [])
    assert state.villagers["a"].needs["cold"] == 9.0


@pytest.mark.req("REQ-SIM-012")
def test_an_unfinished_or_missing_home_gives_no_shelter(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: only a completed home shelters."""
    state = make_world(ROWS, [ana(needs={"cold": 10.0}, home="b0", pos=Coord(1, 0))])
    lodge(state).complete = False
    ctx = Engine(life).context
    assert not life_rules.at_home(ctx, state, state.villagers["a"])
    state.villagers["a"].home = "b9"
    assert not life_rules.at_home(ctx, state, state.villagers["a"])


def test_per_tick_scales_by_tick_minutes(life: Registry) -> None:
    """Rates are per hour; a 5-minute tick takes a twelfth of the hourly rate."""
    calendar = Calendar(seasons=(Season("year", 1),), tick_minutes=5)
    ctx = Engine(life, EngineConfig(calendar=calendar)).context
    assert life_rules.per_tick(ctx, 60.0) == 5.0


def _sink():  # type: ignore[no-untyped-def]
    from pericles.core.events import EventSink

    return EventSink(0)
```

Move the `EventSink` import to the top of the file, and type `_sink` as `-> EventSink`. The inline form above only keeps the listing short.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_life.py -q`
Expected: FAIL with `ImportError` (`pericles.core.life` and `Eat` are missing).

- [ ] **Step 3: Add the intents**

Append to `src/pericles/core/intents.py`:

```python
@dataclass(frozen=True)
class Eat(Intent):
    item: str
    qty: int = 1
    kind: ClassVar[str] = "eat"


@dataclass(frozen=True)
class Sleep(Intent):
    kind: ClassVar[str] = "sleep"
```

- [ ] **Step 4: Implement `pericles.core.life`**

Create `src/pericles/core/life.py`:

```python
"""Needs, eating, sleeping, shelter and health (REQ-SIM-012, REQ-SIM-003 AC2; ADR-0015 §1-§4)."""

from __future__ import annotations

from pericles.core.buildings import building_tiles, near
from pericles.core.content.schema import NeedDef
from pericles.core.context import Context, reject
from pericles.core.events import EventSink
from pericles.core.intents import Eat, Intent, Sleep
from pericles.core.modifiers import Modifier, resolve
from pericles.core.state import Activity, Villager, WorldState

MINUTES_PER_HOUR = 60
SLEEP = "sleep"


def per_tick(ctx: Context, per_hour: float) -> float:
    return per_hour * ctx.config.calendar.tick_minutes / MINUTES_PER_HOUR


def need_rate(ctx: Context, state: WorldState, villager: Villager, need: NeedDef) -> float:
    """The need's per-hour rate after world, season and trait modifiers."""
    registry = ctx.registry
    modifiers = list(state.modifiers)
    modifiers.extend(ctx.config.calendar.season_at(state.tick).modifiers)
    for trait in villager.traits:
        modifiers.extend(
            Modifier.from_def(m, f"trait:{trait}") for m in registry.traits[trait].modifiers
        )
    return resolve(
        modifiers,
        kind="need",
        ident=need.id,
        attribute="rate",
        base=need.rate_per_hour,
        tick=state.tick,
        villager=villager.id,
    ).value


def at_home(ctx: Context, state: WorldState, villager: Villager) -> bool:
    home = state.buildings.get(villager.home) if villager.home is not None else None
    return (
        home is not None
        and home.complete
        and near(villager.pos, building_tiles(home, ctx.registry))
    )


def sleeping(villager: Villager) -> bool:
    return villager.activity is not None and villager.activity.kind == SLEEP


def _hourly_change(
    ctx: Context, state: WorldState, villager: Villager, need: NeedDef, home: bool
) -> float:
    config = ctx.config
    if need.relief == "sleep" and sleeping(villager):
        boost = config.home_sleep_multiplier if home else 1.0
        return -config.sleep_relief_per_hour * boost
    if need.relief == "shelter" and home:
        return -config.shelter_relief_per_hour
    return need_rate(ctx, state, villager, need)


def update_needs(ctx: Context, state: WorldState, sink: EventSink) -> list[tuple[str, str]]:
    """Advance every villager's needs and health; return (villager, cause) for the dying."""
    config = ctx.config
    needs = [ctx.registry.needs[k] for k in sorted(ctx.registry.needs)]
    dying: list[tuple[str, str]] = []
    for vid in sorted(state.villagers):
        villager = state.villagers[vid]
        home = at_home(ctx, state, villager)
        damage = 0.0
        causes: list[str] = []
        for need in needs:
            before = villager.needs.get(need.id, 0.0)
            change = per_tick(ctx, _hourly_change(ctx, state, villager, need, home))
            level = min(need.critical, max(0.0, before + change))
            villager.needs[need.id] = level
            if level < need.critical:
                continue
            if before < need.critical:
                sink.emit("need_critical", actor=vid, need=need.id)
            if need.damage_per_hour > 0:
                assert need.death_cause is not None  # registry rule (ADR-0015 §2)
                damage += per_tick(ctx, need.damage_per_hour)
                causes.append(need.death_cause)
        if causes:
            villager.damage += damage
        else:
            regen = per_tick(ctx, config.health_regen_per_hour)
            villager.damage = max(0.0, villager.damage - regen)
        if causes and villager.damage >= config.max_health:
            dying.append((vid, causes[0]))
        elif sleeping(villager) and all(
            villager.needs.get(n.id, 0.0) <= 0 for n in needs if n.relief == SLEEP
        ):
            villager.activity = None
            sink.emit("woke", actor=vid)
    return dying


def eat(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Eat)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    item = registry.items.get(intent.item)
    if item is None:
        return reject(sink, intent, "unknown_item")
    if item.nutrition <= 0:
        return reject(sink, intent, "not_food")
    if intent.qty <= 0:
        return reject(sink, intent, "bad_quantity")
    if villager.inventory.count(item.id) < intent.qty:
        return reject(sink, intent, "missing_items")
    villager.inventory.remove(item.id, intent.qty)
    relief = item.nutrition * intent.qty
    for need_id in sorted(registry.needs):
        if registry.needs[need_id].relief == "eat":
            villager.needs[need_id] = max(0.0, villager.needs.get(need_id, 0.0) - relief)
    sink.emit(
        "ate",
        actor=villager.id,
        item=item.id,
        qty=intent.qty,
        nutrition=relief,
        destroyed={item.id: intent.qty},
    )
    return None


def sleep(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Sleep)
    villager = state.villagers[intent.actor]
    if villager.path:
        villager.path = []
        villager.move_progress = 0.0
        sink.emit("stopped", actor=villager.id, at=list(villager.pos))
    home = villager.home if at_home(ctx, state, villager) else None
    villager.activity = Activity(SLEEP, SLEEP, home, 0.0, 0.0, 0.0)
    sink.emit("fell_asleep", actor=villager.id, at_home=home is not None)
```

Notes:
- A villager dies only in a tick where a damaging need is critical, so `causes[0]` always exists. A villager loaded with `damage ≥ max_health` and no critical need heals instead. Pin this with `test_a_villager_loaded_at_max_damage_without_a_critical_need_heals`: damage 100, no needs, regeneration 60/hour. After one `update_needs` the damage is 99 and the returned list is empty.
- With the sleep relief at 60/hour and fatigue at 1.5, the first sleeping tick takes fatigue to 0.5 and the next to 0.0, where the villager wakes. That is the `test_sleep_ends_when_rested` timeline.

- [ ] **Step 5: Wire the engine**

In `src/pericles/core/engine.py`:
- import `life` (`from pericles.core import construction, life, work`), `Eat` and `Sleep`;
- register `Eat: partial(life.eat, self.context)` and `Sleep: partial(life.sleep, self.context)`;
- in `_advance_work`, skip sleep before the construction branch:

```python
            if activity.kind == life.SLEEP:
                continue
```

- in `step`, after `self._advance_movement(state, sink)`, add:

```python
        life.update_needs(self.context, state, sink)
```

(Task 5 turns this line into the death loop.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles -q`
Expected: PASS. The existing econ-pack tests define no needs, so `update_needs` changes nothing for them.

Base-pack engine tests also gain needs. The base pack keeps its current needs until Task 8, and those have no damage, so no base-pack test can die.

- [ ] **Step 7: Mutation testing**

Run: `uv run mutmut run "pericles.core.life.*"` and `uv run mutmut run "pericles.core.engine.*"`, then `uv run mutmut results`.
Expected: no survivors in `life`. A typical survivor is `before < need.critical` → `<=`; the "report it once" test kills it. Report the counts.

- [ ] **Step 8: Gates and commit**

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): needs, eating, sleeping, shelter and health

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 5: Death and inheritance

**Files:**
- Create: `src/pericles/core/lifecycle.py`
- Modify: `src/pericles/core/engine.py` (death loop after needs; daily old-age deaths; `Engine.kill`)
- Test: `tests/pericles/test_death.py` (new)

**Interfaces:**
- Consumes:
  - `work.interrupt(ctx, villager, sink, cause, reason=None)` (M1b)
  - `inventory.transfer(registry, src, dst, item, qty)`, `inventory.EPSILON`, `Inventory.weight(registry)`, `Inventory.totals()` (M1b)
  - `buildings.Ownership`, `storage_capacity` (M1b)
  - `Deceased`, `WorldState.dead`, `WorldState.proposals` (Task 3)
  - `life.update_needs` returns `(villager_id, cause)` pairs (Task 4)
- Produces:
  - In `pericles.core.lifecycle`:
    - `OLD_AGE = "old_age"`
    - `age_days(ctx, state, villager) -> int`, computed as `(state.tick - villager.born_tick) // ticks_per_day`
    - `heirs(state, vid) -> list[str]`: the living partner first, then living children ordered by `(born_tick, id)`
    - `die(ctx, state, vid, cause, sink) -> None`, the single death path (ADR-0015 §10)
    - `old_age_deaths(ctx, state, sink) -> None`, the daily phase
  - `Engine.kill(state, villager_id, cause, sink) -> None`, a public entry for god powers (M4) and tests.
  - **Events**, in the order `die` emits them:
    - `work_interrupted` (cause `engine`, reason `death`)
    - `pregnancy_lost {mother, father}`
    - `died {villager, cause, age_days}`
    - `inherited {from, to, item, qty}`, one per heir and item
    - `estate_stored {from, building, item, qty}`
    - `estate_lost {from, destroyed}`
    - `ownership_changed {building, from_kind, from_owners, to_kind, to_owners}`

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_death.py`:

```python
from collections.abc import Callable

import pytest

from pericles.core import lifecycle
from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import EventSink
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.invariants import check_state
from pericles.core.state import Activity, Pregnancy, Proposal, Villager, WorldState

ROWS = ["......", "......", "......"]
MakeWorld = Callable[..., WorldState]
SHORT_DAYS = Calendar(seasons=(Season("year", 10),), day_minutes=4, sunrise_minute=0, sunset_minute=2)


def person(vid: str, **fields: object) -> Villager:
    return Villager(vid, vid.upper(), Coord(0, 0), **fields)  # type: ignore[arg-type]


def kill(life: Registry, state: WorldState, vid: str, cause: str = "raid", **config: object) -> list:  # type: ignore[type-arg]
    sink = EventSink(state.tick)
    Engine(life, EngineConfig(**config)).kill(state, vid, cause, sink)  # type: ignore[arg-type]
    return sink.events


def store(state: WorldState, bid: str, ownership: Ownership, kind: str = "lodge") -> Building:
    building = Building(bid, kind, Coord(3, 0), ownership, complete=True)
    state.buildings[bid] = building
    return building


@pytest.mark.req("REQ-SIM-017")
@pytest.mark.parametrize("cause", ["starvation", "cold", "old_age", "raid", "epidemic"])
def test_the_death_event_records_the_cause(
    life: Registry, make_world: MakeWorld, cause: str
) -> None:
    """AC1: every cause reaches the `died` event; the villager moves to the dead."""
    state = make_world(ROWS, [person("a", born_tick=-8640)])
    events = kill(life, state, "a", cause)
    died = next(e for e in events if e.kind == "died")
    assert died.data == {"villager": "a", "cause": cause, "age_days": 6}
    assert "a" not in state.villagers
    assert state.dead["a"].cause == cause
    assert state.dead["a"].died_tick == state.tick


@pytest.mark.req("REQ-SIM-017")
def test_starvation_kills_through_the_engine(life: Registry, make_world: MakeWorld) -> None:
    """AC1: a starving villager dies in the tick their health runs out, cause starvation."""
    state = make_world(ROWS, [person("a", needs={"hunger": 100.0}, damage=85.0)])
    engine = Engine(life)
    _, events = engine.step(state, [])
    assert "died" not in [e.kind for e in events]
    _, events = engine.step(state, [])
    assert [e.data["cause"] for e in events if e.kind == "died"] == ["starvation"]
    assert "a" not in state.villagers


@pytest.mark.req("REQ-SIM-017")
def test_old_age_death_follows_the_curve(life: Registry, make_world: MakeWorld) -> None:
    """AC2: past old age the daily chance is chance × growth^(days past), capped at 1."""
    config = EngineConfig(
        calendar=SHORT_DAYS, adult_age_days=1, old_age_days=2,
        old_age_death_chance=0.25, old_age_death_growth=2.0,
    )
    ctx = Engine(life, config).context
    state = make_world(ROWS, [person("young", born_tick=0), person("old", born_tick=-16)])
    # "old" is 4 days old at tick 0: 2 days past old age, chance 0.25 × 2² = 1.0.
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert "old" not in state.villagers
    assert state.dead["old"].cause == "old_age"
    assert "young" in state.villagers


@pytest.mark.req("REQ-SIM-017")
def test_old_age_chance_is_drawn_from_the_seeded_rng(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: with chance 0 nobody dies; the same seed gives the same deaths."""
    config = EngineConfig(
        calendar=SHORT_DAYS, adult_age_days=1, old_age_days=1, old_age_death_chance=0.5
    )
    ctx = Engine(life, config).context
    survivors = []
    for _ in range(2):
        state = make_world(ROWS, [person(f"v{i}", born_tick=-8) for i in range(20)], seed=3)
        lifecycle.old_age_deaths(ctx, state, EventSink(0))
        survivors.append(sorted(state.villagers))
    assert survivors[0] == survivors[1]
    assert 0 < len(survivors[0]) < 20
    never = EngineConfig(
        calendar=SHORT_DAYS, adult_age_days=1, old_age_days=1, old_age_death_chance=0.0
    )
    state = make_world(ROWS, [person("v0", born_tick=-8)])
    lifecycle.old_age_deaths(Engine(life, never).context, state, EventSink(0))
    assert "v0" in state.villagers


@pytest.mark.req("REQ-SIM-017")
def test_old_age_deaths_happen_on_the_day_boundary(life: Registry, make_world: MakeWorld) -> None:
    """AC2: the engine rolls old-age deaths once per day, at the last tick of the day."""
    config = EngineConfig(calendar=SHORT_DAYS, adult_age_days=1, old_age_days=1, old_age_death_chance=1.0)
    state = make_world(ROWS, [person("old", born_tick=-8)])
    engine = Engine(life, config)
    for _ in range(3):
        engine.step(state, [])
    assert "old" in state.villagers
    _, events = engine.step(state, [])
    assert [e.data["cause"] for e in events if e.kind == "died"] == ["old_age"]


@pytest.mark.req("REQ-SIM-017")
def test_heirs_are_partner_then_children_oldest_first(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: the inheritance order is the partner, then children by birth."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b"),
            person("b", partner="a"),
            person("c2", parents=("a", "b"), born_tick=50),
            person("c1", parents=("a", "z"), born_tick=10),
            person("c0", parents=("a", "b"), born_tick=50),
            person("x"),
        ],
    )
    assert lifecycle.heirs(state, "a") == ["b", "c1", "c0", "c2"]
    assert lifecycle.heirs(state, "x") == []


@pytest.mark.req("REQ-SIM-017")
def test_the_estate_goes_to_heirs_within_their_carry_limit(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: each heir takes what they can carry; the rest goes on to the next heir."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b", inventory=Inventory({"wood": 4})),  # wood weighs 2
            person("b", partner="a", inventory=Inventory({"plank": 2})),  # planks weigh 1
            person("c", parents=("a", "b")),
        ],
    )
    events = kill(life, state, "a", carry_limit=7.0)
    assert [(e.data["to"], e.data["qty"]) for e in events if e.kind == "inherited"] == [
        ("b", 2),
        ("c", 2),
    ]
    assert state.villagers["b"].inventory.count("wood") == 2
    assert state.villagers["c"].inventory.count("wood") == 2
    assert state.villagers["b"].partner is None


@pytest.mark.req("REQ-SIM-017")
def test_what_heirs_cannot_carry_goes_to_communal_stores_then_is_lost(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: then communal, by store id and within capacity; the remainder is destroyed, recorded."""
    state = make_world(ROWS, [person("a", inventory=Inventory({"berries": 70}))])
    store(state, "b1", Ownership("communal"))
    store(state, "b0", Ownership("communal")).storage.add(life, "berries", 30)
    store(state, "b2", Ownership("personal", ("q",)))
    events = kill(life, state, "a", carry_limit=100.0)
    stored = [(e.data["building"], e.data["qty"]) for e in events if e.kind == "estate_stored"]
    assert stored == [("b0", 20), ("b1", 50)]
    assert "estate_lost" not in [e.kind for e in events]
    assert state.buildings["b2"].storage.count("berries") == 0


@pytest.mark.req("REQ-SIM-017")
def test_an_estate_too_big_for_everyone_is_destroyed_with_an_event(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: nothing vanishes silently; conservation holds through the death."""
    state = make_world(ROWS, [person("a", inventory=Inventory({"berries": 70}))])
    store(state, "b0", Ownership("communal"))
    events = kill(life, state, "a")
    assert [e.data for e in events if e.kind == "estate_lost"] == [
        {"from": "a", "destroyed": {"berries": 20}}
    ]
    assert check_state(Engine(life).context, state) == []


@pytest.mark.req("REQ-SIM-017")
def test_no_estate_lost_event_when_nothing_is_lost(life: Registry, make_world: MakeWorld) -> None:
    """AC3: `estate_lost` appears only when something is destroyed."""
    state = make_world(ROWS, [person("a")])
    assert "estate_lost" not in [e.kind for e in kill(life, state, "a")]


@pytest.mark.req("REQ-SIM-017")
def test_reserved_work_inputs_return_to_the_estate(life: Registry, make_world: MakeWorld) -> None:
    """AC3: dying mid-work interrupts it first, so reserved inputs are inherited, not lost."""
    state = make_world(ROWS, [person("a", partner="b"), person("b", partner="a")])
    villager = state.villagers["a"]
    villager.inventory = Inventory({"wood": 1})
    villager.activity = Activity("recipe", "r", "b9", 10.0, 0.0, 1.0, reserved=Inventory({"plank": 2}))
    events = kill(life, state, "a")
    kinds = [e.kind for e in events]
    assert kinds.index("work_interrupted") < kinds.index("died") < kinds.index("inherited")
    interrupted = next(e for e in events if e.kind == "work_interrupted")
    assert (interrupted.data["cause"], interrupted.data["reason"]) == ("engine", "death")
    assert state.villagers["b"].inventory == Inventory({"plank": 2, "wood": 1})


@pytest.mark.req("REQ-SIM-017")
@pytest.mark.parametrize(
    ("before", "heir_list", "after"),
    [
        (Ownership("personal", ("a",)), ["b"], Ownership("personal", ("b",))),
        (Ownership("personal", ("a",)), [], Ownership("communal")),
        (Ownership("shared", ("a", "q")), ["b"], Ownership("shared", ("b", "q"))),
        (Ownership("shared", ("a", "b")), ["b"], Ownership("personal", ("b",))),
        (Ownership("shared", ("a", "q")), [], Ownership("personal", ("q",))),
        (Ownership("communal"), ["b"], Ownership("communal")),
        (Ownership("personal", ("q",)), ["b"], Ownership("personal", ("q",))),
    ],
)
def test_property_passes_by_the_inheritance_rule(
    life: Registry,
    make_world: MakeWorld,
    before: Ownership,
    heir_list: list[str],
    after: Ownership,
) -> None:
    """AC3: buildings pass to the first heir, or become communal; no owner is ever dead."""
    people = [person("a"), person("q")]
    if heir_list:
        people[0] = person("a", partner="b")
        people.append(person("b", partner="a"))
    state = make_world(ROWS, people)
    store(state, "b0", before)
    events = kill(life, state, "a")
    assert state.buildings["b0"].ownership == after
    changed = [e.data for e in events if e.kind == "ownership_changed"]
    assert len(changed) == (0 if before == after else 1)


@pytest.mark.req("REQ-SIM-017")
def test_death_ends_a_pregnancy_and_open_proposals(life: Registry, make_world: MakeWorld) -> None:
    """AC3: a dying mother loses the pregnancy; proposals to or from the dead are dropped."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b", pregnancy=Pregnancy("b", 99)),
            person("b", partner="a"),
            person("c"),
            person("d"),
        ],
    )
    state.proposals = {"c": Proposal("a", 50), "a": Proposal("d", 50), "d": Proposal("c", 50)}
    events = kill(life, state, "a")
    assert [e.data for e in events if e.kind == "pregnancy_lost"] == [
        {"mother": "a", "father": "b"}
    ]
    assert state.proposals == {"d": Proposal("c", 50)}


@pytest.mark.req("REQ-SIM-017")
def test_two_deaths_in_one_tick_both_resolve(life: Registry, make_world: MakeWorld) -> None:
    """AC3: when both partners starve on the same tick, the second's estate goes to their child."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b", needs={"hunger": 100.0}, damage=95.0, inventory=Inventory({"wood": 1})),
            person("b", partner="a", needs={"hunger": 100.0}, damage=95.0),
            person("c", parents=("a", "b")),
        ],
    )
    _, events = Engine(life, EngineConfig(debug_invariants=True)).step(state, [])
    assert [e.data["villager"] for e in events if e.kind == "died"] == ["a", "b"]
    assert state.villagers["c"].inventory.count("wood") == 1
    assert sorted(state.dead) == ["a", "b"]


def test_age_days_counts_whole_days(life: Registry, make_world: MakeWorld) -> None:
    """Age is whole days since birth (ADR-0015 §5)."""
    ctx = Engine(life, EngineConfig(calendar=SHORT_DAYS)).context
    state = make_world(ROWS, [person("a", born_tick=-9)])
    assert lifecycle.age_days(ctx, state, state.villagers["a"]) == 2
```

Wrap the long lines to 100 columns. Here is the arithmetic behind the assertions. The test pack's weights are: wood 2, plank 1, berries 0.5, seed 0.1, token 0. Lodge storage is 50.

- **Carry test.** b holds 2 planks of a 7.0 limit, so b can take two of the four wood. c takes the other two.
- **Stores test.** b0 already holds 30 of its 50, so it takes 20; b1 takes 50; nothing is lost.
- **Too-big test.** There are no heirs, so one lodge takes 50 and 20 are lost.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_death.py -q`
Expected: FAIL with `ImportError: cannot import name 'lifecycle'`.

- [ ] **Step 3: Implement**

Create `src/pericles/core/lifecycle.py`:

```python
"""Ages, death and inheritance (REQ-SIM-017; ADR-0015 §5, §10). Couples, births and coming of
age are added in later tasks."""

from __future__ import annotations

from pericles.core import work
from pericles.core.buildings import Building, Ownership, storage_capacity
from pericles.core.context import Context
from pericles.core.events import EventSink
from pericles.core.inventory import EPSILON, Inventory, transfer
from pericles.core.state import Deceased, Villager, WorldState

OLD_AGE = "old_age"


def age_days(ctx: Context, state: WorldState, villager: Villager) -> int:
    return (state.tick - villager.born_tick) // ctx.config.calendar.ticks_per_day


def heirs(state: WorldState, vid: str) -> list[str]:
    """The living partner, then living children oldest first (ADR-0015 §10)."""
    villager = state.villagers[vid]
    order: list[str] = []
    if villager.partner is not None and villager.partner in state.villagers:
        order.append(villager.partner)
    children = [v for v in state.villagers.values() if vid in v.parents]
    order += [c.id for c in sorted(children, key=lambda c: (c.born_tick, c.id))]
    return order


def _room(ctx: Context, inventory: Inventory, item: str, qty: int) -> int:
    """How many of `item` (up to qty) fit within the carry limit."""
    weight = ctx.registry.items[item].weight
    if weight <= 0:
        return qty
    free = ctx.config.carry_limit - inventory.weight(ctx.registry)
    return max(0, min(qty, int((free + EPSILON) / weight)))


def _communal_stores(ctx: Context, state: WorldState) -> list[Building]:
    return [
        state.buildings[bid]
        for bid in sorted(state.buildings)
        if state.buildings[bid].ownership.kind == "communal"
        and storage_capacity(ctx.registry, state.buildings[bid]) > 0
    ]


def _distribute(ctx: Context, state: WorldState, dead: Villager, sink: EventSink) -> None:
    registry = ctx.registry
    estate = dead.inventory
    order = heirs(state, dead.id)
    stores = _communal_stores(ctx, state)
    for item, held in sorted(estate.totals().items()):
        left = held
        for heir in order:
            qty = _room(ctx, state.villagers[heir].inventory, item, left)
            if qty:
                transfer(registry, estate, state.villagers[heir].inventory, item, qty)
                sink.emit("inherited", **{"from": dead.id}, to=heir, item=item, qty=qty)
                left -= qty
        for building in stores:
            space = storage_capacity(registry, building) - sum(building.storage.totals().values())
            qty = max(0, min(left, space))
            if qty:
                transfer(registry, estate, building.storage, item, qty)
                sink.emit(
                    "estate_stored", **{"from": dead.id}, building=building.id, item=item, qty=qty
                )
                left -= qty
    remainder = dict(sorted(estate.totals().items()))
    if remainder:
        for item, qty in remainder.items():
            estate.remove(item, qty)
        sink.emit("estate_lost", **{"from": dead.id}, destroyed=remainder)


def _successor(ownership: Ownership, dead: str, heir: str | None) -> Ownership:
    if dead not in ownership.owners:
        return ownership
    owners = set(ownership.owners) - {dead}
    if heir is not None:
        owners.add(heir)
    if len(owners) == 0:
        return Ownership("communal")
    if len(owners) == 1:
        return Ownership("personal", tuple(owners))
    return Ownership("shared", tuple(sorted(owners)))


def _reassign(state: WorldState, dead: str, heir: str | None, sink: EventSink) -> None:
    for bid in sorted(state.buildings):
        building = state.buildings[bid]
        before = building.ownership
        after = _successor(before, dead, heir)
        if after != before:
            building.ownership = after
            sink.emit(
                "ownership_changed",
                building=bid,
                from_kind=before.kind,
                from_owners=list(before.owners),
                to_kind=after.kind,
                to_owners=list(after.owners),
            )


def die(ctx: Context, state: WorldState, vid: str, cause: str, sink: EventSink) -> None:
    """The one death path: work, pregnancy, record, estate, property, links (ADR-0015 §10)."""
    villager = state.villagers[vid]
    work.interrupt(ctx, villager, sink, cause="engine", reason="death")
    if villager.pregnancy is not None:
        sink.emit("pregnancy_lost", mother=vid, father=villager.pregnancy.father)
        villager.pregnancy = None
    sink.emit("died", villager=vid, cause=cause, age_days=age_days(ctx, state, villager))
    order = heirs(state, vid)
    _distribute(ctx, state, villager, sink)
    _reassign(state, vid, order[0] if order else None, sink)
    partner = state.villagers.get(villager.partner) if villager.partner is not None else None
    if partner is not None:
        partner.partner = None
    state.proposals = {
        k: p for k, p in state.proposals.items() if vid not in (k, p.target)
    }
    del state.villagers[vid]
    state.dead[vid] = Deceased(
        id=vid,
        name=villager.name,
        sex=villager.sex,
        born_tick=villager.born_tick,
        died_tick=state.tick,
        cause=cause,
        parents=villager.parents,
        model=villager.model,
    )


def old_age_deaths(ctx: Context, state: WorldState, sink: EventSink) -> None:
    """The daily old-age roll (REQ-SIM-017 AC2); one draw per villager past old age, by id."""
    config = ctx.config
    for vid in sorted(state.villagers):
        past = age_days(ctx, state, state.villagers[vid]) - config.old_age_days
        if past < 0:
            continue
        chance = min(1.0, config.old_age_death_chance * config.old_age_death_growth**past)
        if state.rng.random() < chance:
            die(ctx, state, vid, OLD_AGE, sink)
```

`Building.ownership` must be assignable. `Building` is a mutable dataclass in M1b; if it is frozen, use `dataclasses.replace` and store the replacement in `state.buildings[bid]`. `test_old_age_death_follows_the_curve` puts chance exactly 1.0, so `random() < 1.0` always holds.

In `src/pericles/core/engine.py`, import `lifecycle` and add:

```python
    def kill(self, state: WorldState, villager_id: str, cause: str, sink: EventSink) -> None:
        """Kill a villager (god powers, interventions, tests); the usual death rules apply."""
        lifecycle.die(self.context, state, villager_id, cause, sink)
```

In `step`, replace the `life.update_needs(...)` line and extend the day-boundary block:

```python
        for vid, cause in life.update_needs(self.context, state, sink):
            lifecycle.die(self.context, state, vid, cause, sink)
        if (state.tick + 1) % self.config.calendar.ticks_per_day == 0:
            regrow(state.nodes.values(), self.registry)
            lifecycle.old_age_deaths(self.context, state, sink)
```

The core default `old_age_days` is 600, so no existing test villager (`born_tick=0`) is affected.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles -q`
Expected: PASS.

- [ ] **Step 5: Mutation testing**

Run: `uv run mutmut run "pericles.core.lifecycle.*"`, then `uv run mutmut results`.
Expected: no survivors. The `+ EPSILON` in `_room` is load-bearing when weights are inexact floats. Kill its mutant with `test_room_tolerates_float_weights`: a heir with carry limit 1.0 inherits 10 `seed` (weight 0.1), and all 10 must arrive.

- [ ] **Step 6: Gates and commit**

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): death, old age and inheritance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Homes, couples, pregnancy and births

**Files:**
- Modify: `src/pericles/core/intents.py` (`SetHome`, `ProposeCouple`, `AcceptCouple`)
- Modify: `src/pericles/core/lifecycle.py`
- Modify: `src/pericles/core/engine.py` (handlers; births and proposal expiry each tick; conception daily)
- Test: `tests/pericles/test_family.py` (new)

**Interfaces:**
- Consumes:
  - `lifecycle.age_days`, `lifecycle.die` (Task 5)
  - `buildings.housing_capacity` (M1b)
  - `Pregnancy`, `Proposal` (Task 3)
  - from the `life` fixture: `lodge` (housing 8), `cabin` (housing 5) and `vault` (storage only)
- Produces:
  - Intents:
    - `SetHome(actor, building: str)`, kind `"set_home"`
    - `ProposeCouple(actor, target: str)`, kind `"propose_couple"`
    - `AcceptCouple(actor, proposer: str)`, kind `"accept_couple"`
  - In `lifecycle`:
    - handlers `set_home`, `propose_couple`, `accept_couple`
    - `occupants(state, building_id) -> int`: residents plus their pregnancies
    - `food_stock(ctx, state) -> float`
    - `expire_proposals(state, sink)`
    - `conceive(ctx, state, sink)`, daily
    - `births(ctx, state, sink)`, every tick
  - **Rejection reasons:**
    - `set_home`: `unknown_building`, `incomplete`, `not_housing`, `not_owner`, `house_full`
    - `propose_couple`: `unknown_target`, `self`, `target_too_young`, `already_partnered`, `target_partnered`
    - `accept_couple`: `no_proposal`, `already_partnered`, `target_partnered`
  - **Events:**
    - `moved_in {actor, building}`
    - `couple_proposed {actor, target, expires_tick}`
    - `couple_proposal_expired {actor, target}`
    - `couple_formed {villagers: [a, b]}` (sorted)
    - `conceived {mother, father, due_tick}`
    - `born {child, mother, father, sex}`
  - **Timing:**
    - A proposal made on tick T with TTL n can be accepted on ticks T … T+n−1. It expires at the end of tick T+n−1.
    - Conception happens at the day boundary, and the birth comes `gestation_days × ticks_per_day` ticks later.
    - The child's id is `v{n}`: the smallest n ≥ `state.next_villager` not used by a living or dead villager. `next_villager` is then set to n + 1.
    - The child's name is `child_names[n % len(child_names)]`, or the id when there are no names.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_family.py`:

```python
from collections.abc import Callable

import pytest

from pericles.core import lifecycle
from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import AcceptCouple, ProposeCouple, SetHome
from pericles.core.inventory import Inventory
from pericles.core.state import Deceased, Pregnancy, Proposal, Villager, WorldState

ROWS = ["........", "........", "........", "........"]
MakeWorld = Callable[..., WorldState]
DAYS = Calendar(seasons=(Season("year", 100),), day_minutes=4, sunrise_minute=0, sunset_minute=2)


def adult(vid: str, sex: str = "female", **fields: object) -> Villager:
    return Villager(vid, vid.upper(), Coord(0, 0), sex=sex, **fields)  # type: ignore[arg-type]


def house(
    state: WorldState,
    bid: str = "b0",
    kind: str = "lodge",
    owner: str | None = None,
    at: Coord = Coord(5, 0),
) -> None:
    ownership = Ownership("personal", (owner,)) if owner else Ownership("communal")
    state.buildings[bid] = Building(bid, kind, at, ownership, complete=True)


def rejected(events: list) -> list[str]:  # type: ignore[type-arg]
    return [e.data["reason"] for e in events if e.kind == "intent_rejected"]


def couple(state: WorldState, a: str, b: str, home: str = "b0") -> None:
    for x, y in ((a, b), (b, a)):
        state.villagers[x].partner = y
        state.villagers[x].home = home


# --- homes -------------------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-015")
def test_moving_into_a_home(life: Registry, make_world: MakeWorld) -> None:
    """AC2 (the couple's house): a villager can make a completed house they may use their home."""
    state = make_world(ROWS, [adult("a")])
    house(state, owner="a")
    _, events = Engine(life).step(state, [SetHome("a", "b0")])
    assert [e.data for e in events if e.kind == "moved_in"] == [{"actor": "a", "building": "b0"}]
    assert state.villagers["a"].home == "b0"


@pytest.mark.req("REQ-SIM-015")
def test_a_partner_may_move_into_the_other_partners_house(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: a personal house is usable by the owner's partner."""
    state = make_world(ROWS, [adult("a", partner="b"), adult("b", "male", partner="a")])
    house(state, owner="a")
    Engine(life).step(state, [SetHome("b", "b0")])
    assert state.villagers["b"].home == "b0"


@pytest.mark.req("REQ-SIM-015")
@pytest.mark.parametrize(
    ("setup", "building", "reason"),
    [
        (lambda s: None, "b9", "unknown_building"),
        (lambda s: setattr(s.buildings["b0"], "complete", False), "b0", "incomplete"),
        (lambda s: None, "st", "not_housing"),
        (lambda s: setattr(s.buildings["b0"], "ownership", Ownership("personal", ("q",))), "b0", "not_owner"),
    ],
)
def test_bad_homes_are_rejected(
    life: Registry, make_world: MakeWorld, setup: Callable[[WorldState], object], building: str, reason: str
) -> None:
    """AC2: only a completed house the villager may use can be a home."""
    state = make_world(ROWS, [adult("a"), adult("q")])
    house(state)
    state.buildings["st"] = Building("st", "vault", Coord(0, 3), Ownership("communal"), complete=True)
    setup(state)
    _, events = Engine(life).step(state, [SetHome("a", building)])
    assert rejected(events) == [reason]
    assert state.villagers["a"].home is None


@pytest.mark.req("REQ-SIM-015")
def test_a_full_house_takes_no_one_and_pregnancies_count(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: a cabin houses 5; 4 residents plus one pregnancy leave no room."""
    people = [adult(f"r{i}", home="h") for i in range(4)] + [adult("a")]
    people[0].pregnancy = Pregnancy("r1", 999)
    state = make_world(ROWS, people)
    house(state, "h", "cabin")
    assert lifecycle.occupants(state, "h") == 5
    _, events = Engine(life).step(state, [SetHome("a", "h")])
    assert rejected(events) == ["house_full"]


# --- couples -------------------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-015")
def test_a_couple_forms_only_by_proposal_and_acceptance(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: one villager proposes, the other accepts; only then are they a couple."""
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    engine = Engine(life, EngineConfig(couple_proposal_ttl_ticks=5))
    _, events = engine.step(state, [ProposeCouple("a", "b")])
    assert [e.data for e in events if e.kind == "couple_proposed"] == [
        {"actor": "a", "target": "b", "expires_tick": 5}
    ]
    assert state.villagers["a"].partner is None
    _, events = engine.step(state, [AcceptCouple("b", "a")])
    assert [e.data for e in events if e.kind == "couple_formed"] == [{"villagers": ["a", "b"]}]
    assert (state.villagers["a"].partner, state.villagers["b"].partner) == ("b", "a")
    assert state.proposals == {}


@pytest.mark.req("REQ-SIM-015")
def test_accepting_needs_a_live_proposal_to_you(life: Registry, make_world: MakeWorld) -> None:
    """AC1: no consent without a proposal addressed to the acceptor."""
    state = make_world(ROWS, [adult("a"), adult("b", "male"), adult("c")])
    engine = Engine(life)
    _, events = engine.step(state, [AcceptCouple("b", "a")])
    assert rejected(events) == ["no_proposal"]
    state.proposals["a"] = Proposal("c", 99)
    _, events = engine.step(state, [AcceptCouple("b", "a")])
    assert rejected(events) == ["no_proposal"]


@pytest.mark.req("REQ-SIM-015")
def test_a_proposal_lapses_after_its_ttl(life: Registry, make_world: MakeWorld) -> None:
    """AC1: proposed on tick 0 with TTL 2: acceptable on ticks 0-1, gone after tick 1."""
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    engine = Engine(life, EngineConfig(couple_proposal_ttl_ticks=2))
    engine.step(state, [ProposeCouple("a", "b")])
    _, events = engine.step(state, [])
    assert [e.data for e in events if e.kind == "couple_proposal_expired"] == [
        {"actor": "a", "target": "b"}
    ]
    _, events = engine.step(state, [AcceptCouple("b", "a")])
    assert rejected(events) == ["no_proposal"]


@pytest.mark.req("REQ-SIM-015")
def test_acceptance_on_the_last_valid_tick_works(life: Registry, make_world: MakeWorld) -> None:
    """AC1: the TTL boundary is inclusive of tick T+n-1."""
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    engine = Engine(life, EngineConfig(couple_proposal_ttl_ticks=2))
    engine.step(state, [ProposeCouple("a", "b")])
    engine.step(state, [AcceptCouple("b", "a")])
    assert state.villagers["a"].partner == "b"


@pytest.mark.req("REQ-SIM-015")
@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        (ProposeCouple("a", "zz"), "unknown_target"),
        (ProposeCouple("a", "a"), "self"),
        (ProposeCouple("a", "kid"), "target_too_young"),
        (ProposeCouple("p", "b"), "already_partnered"),
        (ProposeCouple("a", "p"), "target_partnered"),
    ],
)
def test_bad_proposals_are_rejected(
    life: Registry, make_world: MakeWorld, intent: ProposeCouple, reason: str
) -> None:
    """AC1: only two unpartnered adults can be a couple."""
    state = make_world(
        ROWS,
        [adult("a"), adult("b", "male"), adult("kid", adult=False), adult("p", partner="q"), adult("q", partner="p")],
    )
    _, events = Engine(life).step(state, [intent])
    assert rejected(events) == [reason]
    assert state.proposals == {}


@pytest.mark.req("REQ-SIM-015")
def test_acceptance_fails_if_someone_partnered_meanwhile(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: two proposals to the same villager cannot both succeed."""
    state = make_world(ROWS, [adult("a"), adult("c"), adult("b", "male")])
    engine = Engine(life)
    engine.step(state, [ProposeCouple("a", "b")])
    engine.step(state, [ProposeCouple("c", "b")])
    engine.step(state, [AcceptCouple("b", "a")])
    _, events = engine.step(state, [AcceptCouple("b", "c")])
    assert rejected(events) == ["already_partnered"]
    state.proposals["c"] = Proposal("q", 99)
    state.villagers["q"] = adult("q")
    state.villagers["c"].partner = "zz"
    _, events = engine.step(state, [AcceptCouple("q", "c")])
    assert rejected(events) == ["target_partnered"]


# --- conception and births -------------------------------------------------------------------


def family(life: Registry, make_world: MakeWorld, **config: object) -> tuple[Engine, WorldState]:
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    house(state)
    couple(state, "a", "b")
    state.villagers["a"].inventory = Inventory({"berries": 20})  # 200 nutrition
    settings = {"calendar": DAYS, "conception_chance_per_day": 1.0, "gestation_days": 2,
                "birth_food_per_capita": 10.0, **config}
    return Engine(life, EngineConfig(**settings)), state  # type: ignore[arg-type]


def run_days(engine: Engine, state: WorldState, days: int) -> list:  # type: ignore[type-arg]
    events = []
    for _ in range(days * 4):
        events += engine.step(state, [])[1]
    return events


@pytest.mark.req("REQ-SIM-015")
def test_a_couple_with_a_house_and_food_has_a_child_after_gestation(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: conception at the day boundary; the child is born gestation_days later."""
    engine, state = family(life, make_world)
    events = run_days(engine, state, 1)
    assert [e.data for e in events if e.kind == "conceived"] == [
        {"mother": "a", "father": "b", "due_tick": 11}
    ]
    events = run_days(engine, state, 2)
    born = [e for e in events if e.kind == "born"]
    assert len(born) == 1 and born[0].tick == 11
    child = state.villagers[born[0].data["child"]]
    assert child.parents == ("a", "b") and child.adult is False
    assert child.home == "b0" and child.pos == state.villagers["a"].pos
    assert child.born_tick == 11 and child.sex in ("female", "male")
    assert state.villagers["a"].pregnancy is None
    assert state.villagers["a"].last_birth_tick == 11


@pytest.mark.req("REQ-SIM-015")
@pytest.mark.parametrize(
    "spoil",
    [
        lambda s: setattr(s.villagers["a"], "inventory", Inventory({"berries": 1})),  # 10 < 20
        lambda s: setattr(s.villagers["b"], "home", None),
        lambda s: setattr(s.buildings["b0"], "complete", False),
        lambda s: setattr(s.villagers["b"], "sex", "female"),
        lambda s: setattr(s.villagers["b"], "adult", False),
        lambda s: setattr(s.villagers["a"], "last_birth_tick", 0),
    ],
)
def test_no_pregnancy_without_the_conditions(
    life: Registry, make_world: MakeWorld, spoil: Callable[[WorldState], object]
) -> None:
    """AC2: no house, too little food, no fertile pair, or too soon after a birth: no pregnancy."""
    engine, state = family(life, make_world, birth_interval_days=5)
    spoil(state)
    events = run_days(engine, state, 1)
    assert "conceived" not in [e.kind for e in events]


@pytest.mark.req("REQ-SIM-015")
def test_food_threshold_is_inclusive(life: Registry, make_world: MakeWorld) -> None:
    """AC2: a stock exactly at per-capita × population is enough (2 × 10 = 20 = 2 berries)."""
    engine, state = family(life, make_world)
    state.villagers["a"].inventory = Inventory()
    state.buildings["b0"].storage.add(life, "berries", 2)
    assert lifecycle.food_stock(engine.context, state) == 20.0
    events = run_days(engine, state, 1)
    assert "conceived" in [e.kind for e in events]


@pytest.mark.req("REQ-SIM-015")
def test_two_couples_cannot_overfill_a_house(life: Registry, make_world: MakeWorld) -> None:
    """AC2: a cabin of 5 with two couples has one free place; only one conception happens."""
    engine, state = family(life, make_world)
    state.villagers["c"] = adult("c")
    state.villagers["d"] = adult("d", "male")
    house(state, "h", "cabin", at=Coord(0, 2))
    couple(state, "a", "b", "h")
    couple(state, "c", "d", "h")
    state.villagers["c"].inventory = Inventory({"berries": 20})
    events = run_days(engine, state, 1)
    assert [e.data["mother"] for e in events if e.kind == "conceived"] == ["a"]
    events = run_days(engine, state, 4)
    assert lifecycle.occupants(state, "h") == 5
    assert [e.data["mother"] for e in events if e.kind == "conceived"] == []


@pytest.mark.req("REQ-SIM-015")
def test_conception_chance_uses_the_seeded_rng(life: Registry, make_world: MakeWorld) -> None:
    """AC2: chance 0 never conceives; a fractional chance repeats exactly under one seed."""
    engine, state = family(life, make_world, conception_chance_per_day=0.0)
    assert "conceived" not in [e.kind for e in run_days(engine, state, 5)]
    days = []
    for _ in range(2):
        engine, state = family(life, make_world, conception_chance_per_day=0.3)
        events = run_days(engine, state, 10)
        days.append([e.tick for e in events if e.kind == "conceived"])
    assert days[0] == days[1] and days[0]


@pytest.mark.req("REQ-SIM-015")
def test_child_ids_skip_used_ids_and_names_cycle(life: Registry, make_world: MakeWorld) -> None:
    """New villagers get fresh ids v<n> (never reused, even from the dead) and listed names."""
    engine, state = family(life, make_world, child_names=("Io", "Eos"))
    state.villagers["v0"] = adult("v0")
    state.dead["v1"] = Deceased("v1", "Old", None, 0, 0, "cold", (), None)
    state.villagers["a"].pregnancy = Pregnancy("b", state.tick)
    sink = EventSink(state.tick)
    lifecycle.births(engine.context, state, sink)
    assert "v2" in state.villagers and state.villagers["v2"].name == "Io"  # names[2 % 2]
    assert state.next_villager == 3


@pytest.mark.req("REQ-SIM-015")
def test_population_can_double_in_good_conditions(life: Registry, make_world: MakeWorld) -> None:
    """AC3: with fertile settings, four couples, each in a lodge of 8, double the village in 8 days."""
    people = []
    for i in range(4):
        people += [adult(f"m{i}"), adult(f"f{i}", "male")]
    state = make_world(ROWS, people)
    for i, at in enumerate((Coord(5, 0), Coord(0, 2), Coord(2, 2), Coord(4, 2))):
        house(state, f"b{i}", at=at)
        couple(state, f"m{i}", f"f{i}", f"b{i}")
    state.buildings["b0"].storage.add(life, "berries", 50)
    config = EngineConfig(
        calendar=DAYS, conception_chance_per_day=1.0, gestation_days=2,
        birth_interval_days=1, birth_food_per_capita=10.0,
    )
    engine = Engine(life, config)
    run_days(engine, state, 8)
    assert len(state.villagers) >= 16
```

Wrap long lines to 100 columns.

The doubling test's arithmetic, with 4 ticks per day:
- **Conceptions** happen at ticks 3 and 15. Each mother is rested again 1 day after the tick-11 birth.
- **Births** happen at ticks 11 and 23. Each round adds 4, giving 8 → 16 by tick 31, the end of day 8.
- **Housing:** each lodge holds its couple and two children, well within 8.
- **Food:** 50 berries is 500 nutrition, and 500 ≥ 10 × 16.

`test_conception_chance_uses_the_seeded_rng` relies on the seed producing at least one conception in 10 days at chance 0.3. That has about a 97% chance for any given seed. If the default seed gives none, pass `seed=` to `make_world` and say so in the report.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_family.py -q`
Expected: FAIL with `ImportError: cannot import name 'AcceptCouple'`.

- [ ] **Step 3: Implement**

Append to `src/pericles/core/intents.py`:

```python
@dataclass(frozen=True)
class SetHome(Intent):
    building: str
    kind: ClassVar[str] = "set_home"


@dataclass(frozen=True)
class ProposeCouple(Intent):
    target: str
    kind: ClassVar[str] = "propose_couple"


@dataclass(frozen=True)
class AcceptCouple(Intent):
    proposer: str
    kind: ClassVar[str] = "accept_couple"
```

Append to `src/pericles/core/lifecycle.py`. Add `housing_capacity` and `reject` to its imports, along with `AcceptCouple`, `Intent`, `ProposeCouple`, `SetHome`, `Pregnancy`, `Proposal` and `Villager`:

```python
def occupants(state: WorldState, building_id: str) -> int:
    """Residents plus their unborn children (ADR-0015 §7)."""
    residents = [v for v in state.villagers.values() if v.home == building_id]
    return len(residents) + sum(1 for v in residents if v.pregnancy is not None)


def _may_live_in(villager: Villager, building: Building) -> bool:
    ownership = building.ownership
    return ownership.owned_by(villager.id) or (
        villager.partner is not None and ownership.owned_by(villager.partner)
    )


def set_home(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, SetHome)
    villager = state.villagers[intent.actor]
    building = state.buildings.get(intent.building)
    if building is None:
        return reject(sink, intent, "unknown_building")
    if not building.complete:
        return reject(sink, intent, "incomplete")
    capacity = housing_capacity(ctx.registry, building)
    if capacity == 0:
        return reject(sink, intent, "not_housing")
    if not _may_live_in(villager, building):
        return reject(sink, intent, "not_owner")
    if villager.home != building.id:
        incoming = 1 + (1 if villager.pregnancy is not None else 0)
        if occupants(state, building.id) + incoming > capacity:
            return reject(sink, intent, "house_full")
    villager.home = building.id
    sink.emit("moved_in", actor=villager.id, building=building.id)
    return None


def propose_couple(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, ProposeCouple)
    actor = state.villagers[intent.actor]
    target = state.villagers.get(intent.target)
    if target is None:
        return reject(sink, intent, "unknown_target")
    if target.id == actor.id:
        return reject(sink, intent, "self")
    if not target.adult:
        return reject(sink, intent, "target_too_young")
    if actor.partner is not None:
        return reject(sink, intent, "already_partnered")
    if target.partner is not None:
        return reject(sink, intent, "target_partnered")
    expires = state.tick + ctx.config.couple_proposal_ttl_ticks
    state.proposals[actor.id] = Proposal(target.id, expires)
    sink.emit("couple_proposed", actor=actor.id, target=target.id, expires_tick=expires)
    return None


def accept_couple(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, AcceptCouple)
    actor = state.villagers[intent.actor]
    proposal = state.proposals.get(intent.proposer)
    if proposal is None or proposal.target != actor.id or state.tick >= proposal.expires_tick:
        return reject(sink, intent, "no_proposal")
    proposer = state.villagers[intent.proposer]
    if actor.partner is not None:
        return reject(sink, intent, "already_partnered")
    if proposer.partner is not None:
        return reject(sink, intent, "target_partnered")
    actor.partner, proposer.partner = proposer.id, actor.id
    pair = {actor.id, proposer.id}
    state.proposals = {k: p for k, p in state.proposals.items() if k not in pair}
    sink.emit("couple_formed", villagers=sorted(pair))
    return None


def expire_proposals(state: WorldState, sink: EventSink) -> None:
    """Drop proposals that cannot be accepted on the next tick."""
    for proposer in sorted(state.proposals):
        proposal = state.proposals[proposer]
        if proposal.expires_tick <= state.tick + 1:
            del state.proposals[proposer]
            sink.emit("couple_proposal_expired", actor=proposer, target=proposal.target)


def food_stock(ctx: Context, state: WorldState) -> float:
    """Total nutrition held by villagers and in buildings' storage (ADR-0015 §7)."""
    items = ctx.registry.items
    containers = [v.inventory for v in state.villagers.values()]
    containers += [b.storage for b in state.buildings.values()]
    return sum(
        items[item].nutrition * qty for inv in containers for item, qty in inv.totals().items()
    )


def _fertile_pair(ctx: Context, state: WorldState, mother: Villager) -> Villager | None:
    config = ctx.config
    partner = state.villagers.get(mother.partner) if mother.partner is not None else None
    if (
        partner is None
        or not (mother.adult and partner.adult)
        or mother.sex != config.bearing_sex
        or partner.sex == config.bearing_sex
        or partner.sex is None
        or mother.pregnancy is not None
    ):
        return None
    return partner


def _has_room(ctx: Context, state: WorldState, mother: Villager, partner: Villager) -> bool:
    home = state.buildings.get(mother.home) if mother.home is not None else None
    return (
        home is not None
        and partner.home == home.id
        and occupants(state, home.id) < housing_capacity(ctx.registry, home)
    )


def _rested(ctx: Context, state: WorldState, mother: Villager) -> bool:
    if mother.last_birth_tick is None:
        return True
    interval = ctx.config.birth_interval_days * ctx.config.calendar.ticks_per_day
    return state.tick - mother.last_birth_tick >= interval


def conceive(ctx: Context, state: WorldState, sink: EventSink) -> None:
    """The daily conception roll (REQ-SIM-015 AC2). One draw per eligible mother, by id."""
    config = ctx.config
    if food_stock(ctx, state) < config.birth_food_per_capita * len(state.villagers):
        return
    gestation = config.gestation_days * config.calendar.ticks_per_day
    for vid in sorted(state.villagers):
        mother = state.villagers[vid]
        partner = _fertile_pair(ctx, state, mother)
        if partner is None or not _has_room(ctx, state, mother, partner):
            continue
        if not _rested(ctx, state, mother):
            continue
        if state.rng.random() < config.conception_chance_per_day:
            due = state.tick + gestation
            mother.pregnancy = Pregnancy(partner.id, due)
            sink.emit("conceived", mother=vid, father=partner.id, due_tick=due)


def _new_id(state: WorldState) -> tuple[str, int]:
    n = state.next_villager
    while f"v{n}" in state.villagers or f"v{n}" in state.dead:
        n += 1
    state.next_villager = n + 1
    return f"v{n}", n


def births(ctx: Context, state: WorldState, sink: EventSink) -> None:
    """Deliver every pregnancy due by this tick, mothers by id (REQ-SIM-015 AC2)."""
    config = ctx.config
    for vid in sorted(state.villagers):
        mother = state.villagers[vid]
        pregnancy = mother.pregnancy
        if pregnancy is None or pregnancy.due_tick > state.tick:
            continue
        child_id, n = _new_id(state)
        names = config.child_names
        sex = state.rng.choice(config.sexes)
        state.villagers[child_id] = Villager(
            child_id,
            names[n % len(names)] if names else child_id,
            mother.pos,
            sex=sex,
            born_tick=state.tick,
            adult=False,
            home=mother.home,
            parents=tuple(sorted((vid, pregnancy.father))),
        )
        mother.pregnancy = None
        mother.last_birth_tick = state.tick
        sink.emit("born", child=child_id, mother=vid, father=pregnancy.father, sex=sex)
```

Notes on the code:
- `births` adds villagers while iterating `sorted(state.villagers)`. The sorted list is a snapshot, so this is safe, and newborns are never pregnant.
- `_fertile_pair` rejects a partner with `sex is None`. Experiment-created villagers must have a sex to reproduce; test villagers built without one simply never conceive.
- The engine wires the new intents and phases as follows.

In `src/pericles/core/engine.py`, register the handlers:

```python
            SetHome: partial(lifecycle.set_home, self.context),
            ProposeCouple: partial(lifecycle.propose_couple, self.context),
            AcceptCouple: partial(lifecycle.accept_couple, self.context),
```

and extend `step` after the death loop:

```python
        lifecycle.births(self.context, state, sink)
        lifecycle.expire_proposals(state, sink)
        if (state.tick + 1) % self.config.calendar.ticks_per_day == 0:
            regrow(state.nodes.values(), self.registry)
            lifecycle.old_age_deaths(self.context, state, sink)
            lifecycle.conceive(self.context, state, sink)
```

The conception test expects `due_tick: 11`. Conception runs on tick 3, the last tick of day 0 with 4 ticks per day, and gestation is 2 days × 4 ticks, so 3 + 8 = 11. The birth happens in tick 11's birth phase.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles -q`
Expected: PASS.

- [ ] **Step 5: Mutation testing**

Run: `uv run mutmut run "pericles.core.lifecycle.*"`, then `uv run mutmut results`.
Expected: no survivors. Typical survivors are boundary flips:
- `<` → `<=` in `_has_room`, killed by the full-house test;
- `>=` in `_rested`, which needs a test with `last_birth_tick` exactly one interval ago (conception allowed);
- `<=` in `expire_proposals`, killed by the two TTL tests.

Add any test that is missing.

- [ ] **Step 6: Gates and commit**

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): homes, couples by consent, conception and births

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---
### Task 7: Children, witnessing and coming of age

**Files:**
- Modify: `src/pericles/core/engine.py` (the `too_young` filter; witnessing; daily coming of age)
- Modify: `src/pericles/core/work.py` (`start_action`: children only start light actions)
- Modify: `src/pericles/core/lifecycle.py` (`witness`, `come_of_age`)
- Test: `tests/pericles/test_children.py` (new)

**Interfaces:**
- Consumes: `EngineConfig.child_intents`, `child_action_tags`, `family_events`, `village_events`, `childhood_memory_limit`, `model_rule`, `adult_model` (Task 1); `Villager.adult`, `witnessed`, `memories`, `model`, `parents` (Task 3); `lifecycle.age_days`, `births` (Tasks 5–6); `Event(tick, seq, kind, data)` (M1a).
- Produces:
  - `lifecycle.NAMED_FIELDS = ("actor", "child", "father", "mother", "target", "villager")`. These are the event-data keys that name one villager; the `villagers` key holds a list of them.
  - `lifecycle.witness(ctx, state, events) -> None`.
  - `lifecycle.come_of_age(ctx, state, sink) -> None`.
  - The event `came_of_age {villager, model}`.
  - Rejection reason `too_young`. The engine applies it to any intent kind outside `child_intents`, and `start_action` applies it to an action without a `child_action_tags` tag.
  - A witness record is `{"tick": int, "kind": str, "data": dict}`. `witnessed` keeps at most `childhood_memory_limit` records, dropping the oldest.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_children.py`:

```python
from collections.abc import Callable

import pytest

from pericles.core import lifecycle
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import Eat, PlaceBuilding, ProposeCouple, StartAction, Wait
from pericles.core.inventory import Inventory
from pericles.core.state import Deceased, Pregnancy, Villager, WorldState

ROWS = ["......", "......", "......"]
MakeWorld = Callable[..., WorldState]
DAYS = Calendar(seasons=(Season("year", 100),), day_minutes=4, sunrise_minute=0, sunset_minute=2)


def villager(vid: str, **fields: object) -> Villager:
    return Villager(vid, vid.upper(), Coord(0, 0), **fields)  # type: ignore[arg-type]


def kid(**fields: object) -> Villager:
    return villager("k", adult=False, parents=("a", "b"), **fields)


def rejected(events: list[Event]) -> list[str]:
    return [e.data["reason"] for e in events if e.kind == "intent_rejected"]


@pytest.mark.req("REQ-SIM-016")
@pytest.mark.parametrize(
    "intent",
    [
        StartAction("k", "pick"),  # a labour action
        ProposeCouple("k", "a"),
        PlaceBuilding("k", "hut", Coord(2, 0)),
    ],
)
def test_children_cannot_do_adult_things(
    life: Registry, make_world: MakeWorld, intent: object
) -> None:
    """AC1 (engine part): children are limited to their intents and to light actions."""
    state = make_world(ROWS, [villager("a"), kid()])
    _, events = Engine(life).step(state, [intent])  # type: ignore[list-item]
    assert rejected(events) == ["too_young"]


@pytest.mark.req("REQ-SIM-016")
def test_children_eat_wait_and_try_light_work(life: Registry, make_world: MakeWorld) -> None:
    """AC1 (engine part): eating, waiting and light actions pass the child filter."""
    state = make_world(ROWS, [kid(inventory=Inventory({"berries": 1}), needs={"hunger": 50.0})])
    engine = Engine(life)
    _, events = engine.step(state, [Eat("k", "berries")])
    assert "ate" in [e.kind for e in events]
    _, events = engine.step(state, [Wait("k")])
    assert rejected(events) == []
    _, events = engine.step(state, [StartAction("k", "glean")])
    assert "too_young" not in rejected(events)  # rejected only for being away from a bush


@pytest.mark.req("REQ-SIM-016")
def test_an_adult_may_do_what_a_child_may_not(life: Registry, make_world: MakeWorld) -> None:
    """The filter is about age: the same labour intent from an adult is not `too_young`."""
    state = make_world(ROWS, [villager("a")])
    _, events = Engine(life).step(state, [StartAction("a", "pick")])
    assert "too_young" not in rejected(events)


@pytest.mark.req("REQ-SIM-016")
def test_a_child_comes_of_age_at_adult_age(life: Registry, make_world: MakeWorld) -> None:
    """AC2: at the first day boundary at or past adult_age_days the child becomes an adult."""
    config = EngineConfig(calendar=DAYS, adult_age_days=2, old_age_days=50, adult_model="base")
    state = make_world(ROWS, [villager("a", model="m1"), villager("b"), kid(born_tick=-5)])
    engine = Engine(life, config)
    for _ in range(3):  # ticks 0-2; at tick 3 (day boundary) the child is (3+5)//4 = 2 days old
        engine.step(state, [])
    assert state.villagers["k"].adult is False
    _, events = engine.step(state, [])
    assert [e.data for e in events if e.kind == "came_of_age"] == [
        {"villager": "k", "model": "m1"}
    ]
    assert state.villagers["k"].adult is True
    assert state.villagers["k"].model == "m1"


@pytest.mark.req("REQ-SIM-016")
def test_inherit_picks_one_parents_model_with_the_seeded_rng(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: with two parent models the choice is a seeded draw; the same seed repeats it."""
    config = EngineConfig(calendar=DAYS, adult_age_days=1, old_age_days=50)
    picks = set()
    for seed in range(12):
        chosen = []
        for _ in range(2):
            state = make_world(
                ROWS,
                [villager("a", model="m1"), villager("b", model="m2"), kid(born_tick=-4)],
                seed=seed,
            )
            lifecycle.come_of_age(Engine(life, config).context, state, EventSink(0))
            chosen.append(state.villagers["k"].model)
        assert chosen[0] == chosen[1]
        picks.add(chosen[0])
    assert picks == {"m1", "m2"}


@pytest.mark.req("REQ-SIM-016")
def test_a_dead_parents_model_still_counts(life: Registry, make_world: MakeWorld) -> None:
    """AC2: a parent who died still passes on their model."""
    config = EngineConfig(calendar=DAYS, adult_age_days=1, old_age_days=50, adult_model="base")
    state = make_world(ROWS, [villager("b"), kid(born_tick=-4)])
    state.dead["a"] = Deceased("a", "A", None, -99, -1, "cold", (), "m1")
    lifecycle.come_of_age(Engine(life, config).context, state, EventSink(0))
    assert state.villagers["k"].model == "m1"


@pytest.mark.req("REQ-SIM-016")
@pytest.mark.parametrize(
    ("rule", "parent_model", "expected"),
    [("inherit", None, "base"), ("fixed", "m1", "base"), ("inherit", "m1", "m1")],
)
def test_the_model_rule_is_configurable(
    life: Registry,
    make_world: MakeWorld,
    rule: str,
    parent_model: str | None,
    expected: str,
) -> None:
    """AC2: `inherit` falls back to adult_model without parent models; `fixed` always uses it."""
    config = EngineConfig(
        calendar=DAYS, adult_age_days=1, old_age_days=50, model_rule=rule, adult_model="base"
    )
    state = make_world(ROWS, [villager("a", model=parent_model), kid(born_tick=-4)])
    lifecycle.come_of_age(Engine(life, config).context, state, EventSink(0))
    assert state.villagers["k"].model == expected


def event(kind: str, **data: object) -> Event:
    return Event(0, 0, kind, data)


@pytest.mark.req("REQ-SIM-016")
def test_children_witness_family_and_village_events(life: Registry, make_world: MakeWorld) -> None:
    """AC3: family events naming the child, a parent or a sibling, and every village event."""
    state = make_world(
        ROWS,
        [villager("a"), villager("x"), kid(), villager("s", adult=False, parents=("b", "z"))],
    )
    events = [
        event("died", villager="a", cause="cold", age_days=9),  # parent
        event("born", child="s", mother="b", father="z", sex="male"),  # sibling (and parent b)
        event("couple_formed", villagers=["x", "q"]),  # strangers
        event("died", villager="x", cause="raid", age_days=9),  # stranger
        event("building_completed", building="b0", kind="hut", destroyed={}),  # village
        event("ate", actor="k", item="berries", qty=1, nutrition=10.0, destroyed={}),  # not notable
    ]
    lifecycle.witness(Engine(life).context, state, events)
    assert [(r["kind"], r["data"].get("villager")) for r in state.villagers["k"].witnessed] == [
        ("died", "a"),
        ("born", None),
        ("building_completed", None),
    ]
    assert state.villagers["a"].witnessed == []  # adults do not collect childhood memories


@pytest.mark.req("REQ-SIM-016")
def test_witnessing_keeps_the_most_recent_records(life: Registry, make_world: MakeWorld) -> None:
    """AC3: at most childhood_memory_limit records are kept, newest last."""
    state = make_world(ROWS, [kid()])
    ctx = Engine(life, EngineConfig(childhood_memory_limit=2)).context
    lifecycle.witness(ctx, state, [event("building_completed", building=f"b{i}") for i in range(3)])
    assert [r["data"]["building"] for r in state.villagers["k"].witnessed] == ["b1", "b2"]
    ctx = Engine(life, EngineConfig(childhood_memory_limit=0)).context
    lifecycle.witness(ctx, state, [event("building_completed", building="b9")])
    assert state.villagers["k"].witnessed == []


@pytest.mark.req("REQ-SIM-016")
def test_a_newborn_witnesses_its_own_birth(life: Registry, make_world: MakeWorld) -> None:
    """AC3: witnessing runs after births in the tick, so a child remembers being born."""
    state = make_world(ROWS, [villager("a", partner="b"), villager("b", partner="a")])
    state.villagers["a"].pregnancy = Pregnancy("b", 0)
    _, events = Engine(life).step(state, [])
    child = next(e.data["child"] for e in events if e.kind == "born")
    assert [r["kind"] for r in state.villagers[child].witnessed] == ["born"]


@pytest.mark.req("REQ-SIM-016")
def test_coming_of_age_turns_witnessed_events_into_memories(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: the new adult's memories are seeded from what it witnessed."""
    config = EngineConfig(calendar=DAYS, adult_age_days=1, old_age_days=50, adult_model="base")
    records = [{"tick": 1, "kind": "died", "data": {"villager": "a"}}]
    state = make_world(ROWS, [kid(born_tick=-4, witnessed=list(records))])
    lifecycle.come_of_age(Engine(life, config).context, state, EventSink(0))
    assert state.villagers["k"].memories == records
    assert state.villagers["k"].witnessed == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_children.py -q`
Expected: FAIL. There is no `too_young` rejection yet, and `lifecycle.witness` does not exist.

- [ ] **Step 3: Implement**

In `src/pericles/core/engine.py`'s intent loop, add a branch after the `unknown_intent` check:

```python
            elif (
                not state.villagers[intent.actor].adult
                and intent.kind not in self.config.child_intents
            ):
                reason = "too_young"
```

In `src/pericles/core/work.py`'s `start_action`, directly after the `unknown_action` rejection:

```python
    if not villager.adult and not set(action.tags) & set(ctx.config.child_action_tags):
        return reject(sink, intent, "too_young")
```

Append to `src/pericles/core/lifecycle.py`. Add `from collections.abc import Iterable` and `from pericles.core.events import Event`:

```python
NAMED_FIELDS = ("actor", "child", "father", "mother", "target", "villager")


def _named(event: Event) -> set[str]:
    names = {str(event.data[k]) for k in NAMED_FIELDS if event.data.get(k) is not None}
    names.update(str(v) for v in event.data.get("villagers", ()))
    return names


def _family(state: WorldState, child: Villager) -> set[str]:
    """The child, its parents and its siblings, living or dead."""
    parents = set(child.parents)
    people = [(v.id, v.parents) for v in state.villagers.values()]
    people += [(d.id, d.parents) for d in state.dead.values()]
    siblings = {vid for vid, theirs in people if parents & set(theirs)}
    return {child.id} | parents | siblings


def witness(ctx: Context, state: WorldState, events: Iterable[Event]) -> None:
    """Children record the tick's notable events (REQ-SIM-016 AC3; ADR-0015 §9)."""
    config = ctx.config
    events = list(events)
    limit = config.childhood_memory_limit
    for vid in sorted(state.villagers):
        child = state.villagers[vid]
        if child.adult:
            continue
        family = _family(state, child)
        for event in events:
            notable = event.kind in config.village_events or (
                event.kind in config.family_events and bool(_named(event) & family)
            )
            if notable:
                child.witnessed.append(
                    {"tick": event.tick, "kind": event.kind, "data": dict(event.data)}
                )
        del child.witnessed[: max(0, len(child.witnessed) - limit)]


def _model(ctx: Context, state: WorldState, child: Villager) -> str | None:
    config = ctx.config
    if config.model_rule == "fixed":
        return config.adult_model
    models = set()
    for parent in child.parents:
        alive = state.villagers.get(parent)
        model = alive.model if alive is not None else None
        if alive is None and parent in state.dead:
            model = state.dead[parent].model
        if model is not None:
            models.add(model)
    return state.rng.choice(sorted(models)) if models else config.adult_model


def come_of_age(ctx: Context, state: WorldState, sink: EventSink) -> None:
    """Children at adult age become adults, with a model and memories (REQ-SIM-016 AC2-AC3)."""
    for vid in sorted(state.villagers):
        child = state.villagers[vid]
        if child.adult or age_days(ctx, state, child) < ctx.config.adult_age_days:
            continue
        child.adult = True
        child.model = _model(ctx, state, child)
        child.memories = child.witnessed
        child.witnessed = []
        sink.emit("came_of_age", villager=vid, model=child.model)
```

Notes on the code:
- `state.rng.choice` over a single model still consumes a draw. Keep it that way: the draw order then depends only on which children come of age, not on which models their parents have.
- The `del` slice keeps the newest `limit` records. With a limit of 0 it clears the list.
- `dict(event.data)` is a shallow copy. Event data values are JSON-ready scalars, lists and dicts that nothing mutates after emission.

In `step`, add coming of age to the day block, after the old-age deaths and before conception:

```python
            lifecycle.old_age_deaths(self.context, state, sink)
            lifecycle.come_of_age(self.context, state, sink)
            lifecycle.conceive(self.context, state, sink)
```

Then add witnessing after the day block and before modifier expiry:

```python
        lifecycle.witness(self.context, state, sink.events)
```

`test_children_cannot_do_adult_things` uses `PlaceBuilding("k", "hut", …)`. `hut` is an ECON_PACK building, and the intent is rejected before validation. `test_a_child_comes_of_age_at_adult_age` gives parent `b` no model, so the only candidate is `m1`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles -q`
Expected: PASS.

- [ ] **Step 5: Mutation testing**

Run: `uv run mutmut run "pericles.core.lifecycle.*"`, `uv run mutmut run "pericles.core.work.*"` and `uv run mutmut run "pericles.core.engine.*"`, then `uv run mutmut results`.
Expected: no new survivors. Typical survivors and how to kill them:
- `age_days < adult_age_days` → `<=`: the day-before check in `test_a_child_comes_of_age_at_adult_age` kills it.
- `max(0, …)` → `max(1, …)`: kill it with the 0-limit case.

- [ ] **Step 6: Gates and commit**

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): children's limits, witnessed memories and coming of age

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Life invariants, base-pack content, winter and documentation

**Files:**
- Modify: `src/pericles/core/invariants.py` (`check_state`)
- Modify: `src/pericles/content/base/needs.yaml`, `items.yaml`, `buildings.yaml`, `recipes.yaml`, `actions.yaml`
- Modify: `src/pericles/experiment/default_settings.yaml` (winter modifiers)
- Modify: `tests/pericles/test_invariants.py`, `tests/pericles/test_base_pack.py`, `tests/pericles/test_settings.py`
- Modify: `docs/requirements/sim.md`, `docs/requirements/traceability.md` (generated), `docs/superpowers/specs/2026-11-22-pericles-design.md`, `README.md`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `check_state` also reports:
    - a need level outside 0…critical, or a need the registry does not know;
    - damage outside `[0, max_health)`;
    - a partner that is not living, or is not partnered back;
    - a home that is missing, incomplete or not housing;
    - occupants (residents plus pregnancies) over housing;
    - a child with a partner or a pregnancy;
    - a building owner, partner or proposal party who is dead;
    - an id that is both living and dead.
  - Base pack:
    - needs with damage and relief;
    - `grain` nutrition 3;
    - new items `flour` and `bread`;
    - new buildings `mill` and `bakery`;
    - new recipes `grind_flour` and `bake_bread`;
    - `gather_berries` tagged `light`.
  - The default winter carries the need modifiers.

- [ ] **Step 1: Write the failing invariant tests**

Append to `tests/pericles/test_invariants.py`. Add the imports for `AcceptCouple`, `Eat`, `ProposeCouple`, `SetHome`, `Sleep`, `Building`, `Ownership`, `Calendar`, `Season`, `Pregnancy`, `Proposal`, `Deceased` and `Villager` if missing:

```python
@pytest.mark.req("REQ-SIM-018")
@pytest.mark.parametrize(
    ("break_it", "message"),
    [
        (lambda s: s.villagers["a"].needs.update(hunger=101.0), "villager a hunger 101 outside 0..100"),
        (lambda s: s.villagers["a"].needs.update(mood=1.0), "villager a has unknown need mood"),
        (lambda s: setattr(s.villagers["a"], "damage", -1.0), "villager a damage -1 outside [0, 100)"),
        (lambda s: setattr(s.villagers["a"], "partner", "zz"), "villager a partner zz is not living"),
        (lambda s: setattr(s.villagers["a"], "partner", "c"), "villager a partner c is not partnered back"),
        (lambda s: setattr(s.villagers["a"], "home", "b9"), "villager a home b9 is not a completed house"),
        (lambda s: setattr(s.buildings["b0"], "complete", False), "villager a home b0 is not a completed house"),
        (lambda s: setattr(s.villagers["c"], "partner", "a") or setattr(s.villagers["c"], "adult", False) or setattr(s.villagers["a"], "partner", "c"), "child c has a partner"),
        (lambda s: setattr(s.villagers["c"], "adult", False) or setattr(s.villagers["c"], "pregnancy", Pregnancy("a", 9)), "child c is pregnant"),
        (lambda s: s.dead.update(c=Deceased("c", "C", None, 0, 0, "cold", (), None)), "c is both living and dead"),
        (lambda s: setattr(s.buildings["b0"], "ownership", Ownership("personal", ("d",))), "building b0 is owned by the dead d"),
        (lambda s: s.proposals.update(c=__import__("pericles.core.state", fromlist=["Proposal"]).Proposal("d", 9)), "proposal c→d names the dead d"),
    ],
)
def test_life_state_checks_name_the_broken_rule(
    life: Registry, make_world: MakeWorld, break_it: Callable[[WorldState], object], message: str
) -> None:
    """AC2: the invariant checker covers needs, health, couples, homes, children and the dead."""
    state = make_world(
        ["......", "......"],
        [
            Villager("a", "A", Coord(0, 0), home="b0", partner="b", sex="female"),
            Villager("b", "B", Coord(0, 0), home="b0", partner="a", sex="male"),
            Villager("c", "C", Coord(0, 0)),
        ],
    )
    state.buildings["b0"] = Building("b0", "lodge", Coord(3, 0), Ownership("communal"), complete=True)
    state.dead["d"] = Deceased("d", "D", None, 0, 0, "cold", (), None)
    ctx = Engine(life).context
    assert check_state(ctx, state) == []
    break_it(state)
    assert message in check_state(ctx, state)


@pytest.mark.req("REQ-SIM-018")
def test_an_overfull_house_is_reported(life: Registry, make_world: MakeWorld) -> None:
    """AC2: residents plus pregnancies never exceed housing."""
    people = [Villager(f"r{i}", "R", Coord(0, 0), home="h") for i in range(5)]
    people[0].pregnancy = Pregnancy("r1", 9)
    state = make_world(["......", "......"], people)
    state.buildings["h"] = Building("h", "cabin", Coord(4, 0), Ownership("communal"), complete=True)
    assert "building h houses 6, over its housing 5" in check_state(Engine(life).context, state)


LIFE_VIDS = ["a", "b", "c", "d", "e", "f"]
LIFE_INTENT = st.one_of(
    st.builds(Eat, st.sampled_from(LIFE_VIDS), st.sampled_from(["berries", "wood"]), st.integers(0, 3)),
    st.builds(Sleep, st.sampled_from(LIFE_VIDS)),
    st.builds(ProposeCouple, st.sampled_from(LIFE_VIDS), st.sampled_from(LIFE_VIDS)),
    st.builds(AcceptCouple, st.sampled_from(LIFE_VIDS), st.sampled_from(LIFE_VIDS)),
    st.builds(SetHome, st.sampled_from(LIFE_VIDS), st.sampled_from(["b0", "b1", "b9"])),
)
LIVES = st.lists(st.lists(LIFE_INTENT, max_size=4), min_size=1, max_size=150)
LIFE_CONFIG = EngineConfig(
    calendar=Calendar(seasons=(Season("year", 100),), day_minutes=4, sunrise_minute=0, sunset_minute=2),
    adult_age_days=3,
    old_age_days=6,
    old_age_death_chance=0.2,
    gestation_days=2,
    birth_interval_days=1,
    conception_chance_per_day=0.8,
    birth_food_per_capita=0.0,
    couple_proposal_ttl_ticks=8,
    debug_invariants=True,
)


def life_world(make_world: MakeWorld, life: Registry) -> WorldState:
    people = [
        Villager(
            vid,
            vid.upper(),
            Coord(1, 1),
            sex="female" if i % 2 == 0 else "male",
            born_tick=-4 * i,
            inventory=Inventory({"berries": 6}) if i < 3 else Inventory(),
            model=f"m{i % 2}",
        )
        for i, vid in enumerate(LIFE_VIDS)
    ]
    state = make_world(["........", "........", "........"], people)
    state.buildings["b0"] = Building("b0", "lodge", Coord(0, 0), Ownership("communal"), complete=True)
    state.buildings["b1"] = Building("b1", "cabin", Coord(3, 1), Ownership("communal"), complete=True)
    return state


@pytest.mark.req("REQ-SIM-018")
@settings(max_examples=60, deadline=None)
@given(LIVES)
def test_random_lives_keep_every_invariant(
    life: Registry, make_world: MakeWorld, ticks: list[list[object]]
) -> None:
    """AC2: random life (eating, sleeping, couples, homes, births, deaths) never breaks a rule."""
    state = life_world(make_world, life)
    engine = Engine(life, LIFE_CONFIG)
    for intents in ticks:
        engine.step(state, intents)  # type: ignore[arg-type]  # debug mode raises on any breach


@pytest.mark.req("REQ-SIM-018")
def test_a_scripted_life_reaches_every_phase(life: Registry, make_world: MakeWorld) -> None:
    """AC1/AC2: births, coming of age, deaths and estates all happen, and the ledger stays exact."""
    state = life_world(make_world, life)
    engine = Engine(life, LIFE_CONFIG)
    script = {
        0: [ProposeCouple("a", "b"), ProposeCouple("c", "d")],
        1: [AcceptCouple("b", "a"), AcceptCouple("d", "c")],
        2: [SetHome("a", "b0"), SetHome("b", "b0"), SetHome("c", "b0"), SetHome("d", "b0")],
    }
    kinds: set[str] = set()
    for tick in range(240):
        _, events = engine.step(state, script.get(tick, []))
        kinds |= {e.kind for e in events}
    assert {"couple_formed", "conceived", "born", "came_of_age", "died"} <= kinds
    assert {"inherited", "estate_stored", "estate_lost"} & kinds
    assert any(d.cause == "old_age" for d in state.dead.values())
    assert any(d.cause == "starvation" for d in state.dead.values())


@pytest.mark.req("REQ-SIM-018")
def test_a_restored_life_snapshot_continues_identically(
    life: Registry, make_world: MakeWorld
) -> None:
    """Snapshots carry the whole life state: a restored world replays the same future."""
    state = life_world(make_world, life)
    engine = Engine(life, LIFE_CONFIG)
    for tick in range(40):
        engine.step(state, [ProposeCouple("a", "b")] if tick == 0 else [AcceptCouple("b", "a")] if tick == 1 else [])
    copy = WorldState.from_dict(state.to_dict())
    for _ in range(80):
        engine.step(state, [])
        engine.step(copy, [])
    assert copy.digest() == state.digest()
```

Notes on the tests:
- Wrap the long lines to 100 columns.
- In the parametrised cases, replace the `__import__` and `or`-chained lambdas with small named helper functions above the test. They are written inline here only to keep the listing short.
- In `test_a_scripted_life_reaches_every_phase` nobody eats, so everyone eventually starves. The couples live at home in b0 (sheltered, so hunger kills them first), while e and f are outdoors (cold comes first in id order). If the 240-tick timeline gives no old-age death with this seed, raise `old_age_death_chance` in a local `dataclasses.replace(LIFE_CONFIG, …)` rather than lengthening the run, and record the change in the report.
- `LIFE_CONFIG`'s `adult_age_days=3` is below `old_age_days=6`, which `EngineConfig` requires.

- [ ] **Step 2: Write the failing content and settings tests**

In `tests/pericles/test_base_pack.py`, add `"mill"` and `"bakery"` to `BUILDINGS`. Change the docstring of `test_base_pack_has_the_v1_buildings` to name REQ-SIM-009 AC4's new list, keeping its `req` mark. Then append:

```python
@pytest.mark.req("REQ-SIM-009")
def test_grain_becomes_flour_becomes_bread(registry: Registry) -> None:
    """AC4: the mill grinds grain into flour and the bakery bakes it into bread."""
    grind, bake = registry.recipes["grind_flour"], registry.recipes["bake_bread"]
    assert (grind.building, dict(grind.inputs), dict(grind.outputs)) == (
        "mill",
        {"grain": 3},
        {"flour": 2},
    )
    assert (bake.building, dict(bake.inputs), dict(bake.outputs)) == (
        "bakery",
        {"flour": 2, "wood": 1},
        {"bread": 2},
    )
    assert registry.items["grain"].nutrition == 3
    assert registry.items["bread"].nutrition == 20
    assert registry.items["flour"].nutrition == 0
    # Processing pays: 3 grain (9 nutrition) become 2 bread (40).
    assert 2 * registry.items["bread"].nutrition > 3 * registry.items["grain"].nutrition


@pytest.mark.req("REQ-SIM-012")
def test_base_needs_damage_and_relief(registry: Registry) -> None:
    """AC1/AC2: hunger and cold can kill (starvation, cold); fatigue is relieved by sleep."""
    needs = registry.needs
    assert (needs["hunger"].relief, needs["hunger"].death_cause) == ("eat", "starvation")
    assert (needs["cold"].relief, needs["cold"].death_cause) == ("shelter", "cold")
    assert (needs["fatigue"].relief, needs["fatigue"].damage_per_hour) == ("sleep", 0.0)


@pytest.mark.req("REQ-SIM-016")
def test_children_can_gather_berries(registry: Registry) -> None:
    """AC1: berry gathering is light work, the one base action children may do."""
    light = sorted(a.id for a in registry.actions.values() if "light" in a.tags)
    assert light == ["gather_berries"]
```

Append to `tests/pericles/test_settings.py`:

```python
@pytest.mark.req("REQ-SIM-003")
def test_the_default_winter_raises_food_and_warmth_needs() -> None:
    """AC2: the playable winter multiplies hunger and cold rates (values tweakable in the file)."""
    winter = DEFAULT_CALENDAR.seasons[3]
    assert winter.modifiers == (
        Modifier(Target("need", "hunger"), "rate", Op.MUL, 1.5, "season:winter"),
        Modifier(Target("need", "cold"), "rate", Op.MUL, 6.0, "season:winter"),
    )
    assert all(s.modifiers == () for s in DEFAULT_CALENDAR.seasons[:3])
```

Run: `uv run pytest tests/pericles/test_invariants.py tests/pericles/test_base_pack.py tests/pericles/test_settings.py -q`
Expected: FAIL. The new `check_state` messages are missing, the base pack lacks the mill and bakery, and winter has no modifiers.

- [ ] **Step 3: Extend the invariant checker**

In `src/pericles/core/invariants.py`, import `housing_capacity` and `lifecycle.occupants`, and add `_check_life(ctx, state)`, called at the end of `check_state` (`problems += _check_life(ctx, state)`). `invariants` importing `lifecycle` is fine: both are core.

```python
def _check_life(ctx: Context, state: WorldState) -> list[str]:
    registry = ctx.registry
    max_health = ctx.config.max_health
    problems: list[str] = []
    for vid in sorted(state.villagers):
        villager = state.villagers[vid]
        for need, level in sorted(villager.needs.items()):
            if need not in registry.needs:
                problems.append(f"villager {vid} has unknown need {need}")
            elif not 0 <= level <= registry.needs[need].critical:
                critical = registry.needs[need].critical
                problems.append(f"villager {vid} {need} {level:g} outside 0..{critical:g}")
        if not 0 <= villager.damage < max_health:
            problems.append(
                f"villager {vid} damage {villager.damage:g} outside [0, {max_health:g})"
            )
        partner = villager.partner
        if partner is not None:
            if partner not in state.villagers:
                problems.append(f"villager {vid} partner {partner} is not living")
            elif state.villagers[partner].partner != vid:
                problems.append(f"villager {vid} partner {partner} is not partnered back")
        if villager.home is not None:
            home = state.buildings.get(villager.home)
            if home is None or housing_capacity(registry, home) == 0:
                problems.append(f"villager {vid} home {villager.home} is not a completed house")
        if not villager.adult and villager.partner is not None:
            problems.append(f"child {vid} has a partner")
        if not villager.adult and villager.pregnancy is not None:
            problems.append(f"child {vid} is pregnant")
        if vid in state.dead:
            problems.append(f"{vid} is both living and dead")
    for bid in sorted(state.buildings):
        building = state.buildings[bid]
        housing = housing_capacity(registry, building)
        housed = occupants(state, bid)
        if housed > housing and housing > 0:
            problems.append(f"building {bid} houses {housed}, over its housing {housing}")
        for owner in building.ownership.owners:
            if owner in state.dead:
                problems.append(f"building {bid} is owned by the dead {owner}")
    for proposer in sorted(state.proposals):
        target = state.proposals[proposer].target
        for party in (proposer, target):
            if party in state.dead:
                problems.append(f"proposal {proposer}→{target} names the dead {party}")
    return problems
```

`housing_capacity` returns 0 for an incomplete building, so one message covers a missing, incomplete or non-housing home. The `housing > 0` guard leaves a resident of an incomplete home to that message, so it is not reported twice. The partner case "partner c is not partnered back" also triggers for the `child c has a partner` case, which only asserts its own message is present.

- [ ] **Step 4: Update the base pack and default winter**

`src/pericles/content/base/needs.yaml`:

```yaml
needs:
  - {id: hunger, rate_per_hour: 4.0, critical: 100, damage_per_hour: 5.0, death_cause: starvation, relief: eat}
  - {id: fatigue, rate_per_hour: 4.0, critical: 100, relief: sleep}
  - {id: cold, rate_per_hour: 1.0, critical: 100, damage_per_hour: 5.0, death_cause: cold, relief: shelter}
```

In `items.yaml`, change the grain line and add flour and bread after it:

```yaml
  - {id: grain, weight: 0.5, nutrition: 3, tags: [food]}
  - {id: flour, weight: 0.5, tags: [material]}
  - {id: bread, weight: 0.3, nutrition: 20, tags: [food]}
```

In `buildings.yaml`, append:

```yaml
  - {id: mill, cost: {wood: 12, stone: 6}, build_work: 300, footprint: [2, 2], workers: 2, storage: 40, tags: [food]}
  - {id: bakery, cost: {wood: 10, stone: 8}, build_work: 300, footprint: [2, 2], workers: 2, storage: 30, tags: [food]}
```

In `recipes.yaml`, append:

```yaml
  - {id: grind_flour, building: mill, inputs: {grain: 3}, outputs: {flour: 2}, work_ticks: 40, skill: milling}
  - {id: bake_bread, building: bakery, inputs: {flour: 2, wood: 1}, outputs: {bread: 2}, work_ticks: 60, skill: baking}
```

In `actions.yaml`, change `gather_berries`'s tags to `[labour, light]`.

If the registry rejects `material` as an unknown tag or `milling`/`baking` as unknown skills, follow how the existing pack declares them. Tags and skills are free IDs in M1b's schema.

In `src/pericles/experiment/default_settings.yaml`, change the winter season to:

```yaml
      - name: winter
        days: 10
        blocked_tags: [sowing]
        modifiers:
          - {target: {kind: need, id: hunger}, attribute: rate, op: mul, value: 1.5}
          - {target: {kind: need, id: cold}, attribute: rate, op: mul, value: 6.0}
```

The rates work out as follows:
- Hunger at 4/h reaches 100 in 25 hours. Eating 1 bread (20) every 5 hours keeps it steady; grain alone needs 33 a day.
- Starvation at 5/h kills in 20 hours from critical.
- Cold at 1/h outdoors becomes 6/h in winter, so a villager outdoors reaches critical in about 17 hours. A home lowers it by 20/h.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. Base-pack tests that run the engine for a long time (if any) now feel hunger. If one fails because a villager starves, give that test's villagers food or shorten the run, and say so in the report. Do not weaken the needs.

- [ ] **Step 6: Documentation and statuses**

- `docs/requirements/sim.md`:
  - **REQ-SIM-009 AC4:** change the list to "house, storehouse, farm, fishing hut, lumber camp, quarry, mine, smithy, mint, town hall, palisade, school, mill and bakery". Per "Revising requirements", its status goes from Implemented back to Accepted, and Task 8's revisited test returns it to **Implemented** in this same commit. Note the change in the commit message.
  - **Statuses:**
    - REQ-SIM-003, -012, -015, -017 and -018 become **Implemented**.
    - REQ-SIM-016 stays **Accepted**, because AC1's scripted behaviour comes in M1d.
    - REQ-EXP-001 stays Accepted (M4).
- `docs/superpowers/specs/2026-11-22-pericles-design.md`:
  - In §4.2's base-pack content, add the mill and bakery to the buildings and flour and bread to the items. Add a sentence: "Grain is barely edible raw (nutrition 3); milling and baking turn 3 grain into 2 bread (nutrition 20 each)."
  - In §4.4, add "Rules and parameters: ADR-0015."
- `README.md`: set the status line to `Status: M1c Life and population complete; M1d Running villages next.`
- Regenerate the matrix: `PYTHONPATH=tools uv run python -m pericles_tools.traceability matrix`.
- `docs/requirements/milestones.md` keeps M1 as not done; M1d remains.

- [ ] **Step 7: Full gates and the mutation gate**

Run, in order:
1. the five gates
2. `PYTHONPATH=tools uv run python -m pericles_tools.traceability check`
3. `PYTHONPATH=tools uv run python -m pericles_tools.adr check`
4. `PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run`

Expected: all exit 0, with the `pericles.core` mutation score ≥ 80%. If the gate fails, add tests for the survivors it lists; never lower the threshold.

- [ ] **Step 8: Commit**

```bash
git add src/pericles tests/pericles docs README.md
git commit -m "feat(content): needs that kill, mill and bakery, winter needs; life invariants; docs

REQ-SIM-009 AC4 changed: the base pack adds a mill and a bakery (approved 2026-11-23).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-review notes (for the executor)

- **Spec coverage:**

  | Requirement | Task(s) |
  |---|---|
  | REQ-SIM-003 AC2 | 1, 4, 8 |
  | REQ-SIM-009 AC4 | 8 |
  | REQ-SIM-012 | 4 and 8 |
  | REQ-SIM-015 | 6 |
  | REQ-SIM-016 AC1 (engine part) | 7 |
  | REQ-SIM-016 AC2 and AC3 | 7 |
  | REQ-SIM-017 | 5 |
  | REQ-SIM-018 | 4 (`ate`), 5 (`estate_lost`), 8 |
  | REQ-EXP-001 AC2 (engine section) | 2 |
  | The no-magic-values rule | 2, plus every task's constraint |

- **Deferred to M1d:**
  - REQ-AGT-008 and REQ-SIM-016 AC1's scripted behaviour
  - the full `experiment.yaml` sections: seed, map, packs, population with sexes, ages and models
  - REQ-EXP-003 metrics
  - REQ-NFR-003 performance
  - snapshot durability
- **Interfaces that cross tasks:**
  - `life.update_needs` returns `(id, cause)` pairs (4 → 5).
  - `lifecycle.die` is used by 5, the engine and M4.
  - `lifecycle.occupants` is used by 6 and 8.
  - `lifecycle.age_days` is used by 5 and 7.
  - `EngineConfig` fields (1) are read by 2 (completeness test) and by 4–7.
  - `LIFE_PACK`, `LIFE_EXTRA` and the `life` fixture (3) are used by 4–8, and include `lodge`, `cabin` and `glean`.
