# M1b Work and Economy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Villagers can work. They carry items in inventories with a weight limit, harvest resource nodes that regrow, and perform timed actions that improve their skills and wear out tools. They also place, supply and construct buildings with an ownership, use stores, craft recipes and research technologies. Every item that appears or disappears is accounted for by an event.

**Architecture:** All new rules live in `pericles.core` and are driven by `Engine.step`.
- **State:** each villager carries an `Inventory` (stackable counts plus individual tool instances) and at most one `Activity`. The `WorldState` gains resource `Node`s, `Building`s, village knowledge and a building counter.
- **Modules:** `work.py` handles actions, recipes and research, and `construction.py` handles sites, construction and stores. Both receive a `Context` that holds the registry, the engine config and the precomputed locked content.
- **Conservation:** items are created or destroyed only by events that carry `created` and `destroyed` bundles. `invariants.py` checks this in tests and, in debug mode, on every tick.

**Tech Stack:** Python ≥ 3.12, pydantic 2, PyYAML, pytest, Hypothesis, mutmut.

**Spec:** `docs/superpowers/specs/2026-11-22-pericles-design.md` (§4.1–4.5, §10). Requirements:
- `docs/requirements/sim.md`: REQ-SIM-003 AC2 (season blocking only), -004 AC3, -007, -008, -009, -010, -011, -013, -014 and -018.
- `docs/requirements/eco.md`: REQ-ECO-001.
- ADRs: ADR-0005 (content and modifiers), ADR-0013 (kernel conventions) and the new ADR-0014.

**Follow-up:** M1c (life and population) gets its own plan after this one merges. It covers:
- REQ-SIM-012 (needs) and the winter need-rate part of REQ-SIM-003 AC2.
- REQ-SIM-015, -016 and -017 (births, children, death).
- REQ-AGT-008 (scripted behaviour).
- REQ-EXP-003 AC1 metrics.
- REQ-NFR-003 (1000 ticks/s).
- The durability items carried over from the M1a review: snapshot fsync, falling back past a corrupt snapshot, and an explicit check that the log is not behind the snapshot.

## Global Constraints

- Work on branch `m1b-work-economy`, which the plan commit creates from `main`. Land it through a PR to `main`.
- `pericles.core` imports nothing from `pericles.agents`, `pericles.llm`, `pericles.experiment`, `pericles.server` or `pericles.analysis`. It never imports `time`, `datetime`, `uuid` or `secrets`. It contains no string literal equal to a base-pack content ID. Existing tests enforce all three.
- Determinism (ADR-0013):
  - All randomness comes from `WorldState.rng`, or from a local `random.Random` seeded from a string that includes the run seed (node placement).
  - Iterate dicts and sets in sorted order wherever the order can affect state or events.
- **Same-tick semantics:**
  - Work starts in the tick its intent is processed and advances in that same tick, as movement already does.
  - Each tick runs in this order: intents (sorted, then shuffled with the state RNG), then work progress for villagers in id order, then movement, then daily node regrowth, then modifier expiry, then `tick += 1`.
- **The tilemap is replaced, never changed in place.** The engine's cost-field cache is keyed on the identity of `state.tilemap` plus the set of blocked tiles.
- Every event that creates or destroys items carries `created` and/or `destroyed` bundles (`{item_id: quantity}`). Events that only move items between containers carry neither. Task 6's invariant checker relies on this contract.
- Content models keep `extra="forbid"`, `frozen=True` and strict numerics (M1a). Content IDs match `^[a-z][a-z0-9_]*$`.
- Every test for a requirement carries `@pytest.mark.req("REQ-…")` (literal IDs) and names the AC in its docstring. Product tests live in `tests/pericles/`.
- Mutation score for `pericles.core` must be ≥ 80%. Each task mutates its own modules and adds tests for survivors. `# pragma: no mutate` is allowed only on a line where every possible mutant is equivalent, with the reason given in the report.
- Gates before every commit, in order:
  1. `uv run ruff format .`
  2. `uv run pytest -q`
  3. `uv run mypy`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`

  Never hide a gate's exit code behind a pipe.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Item conservation under races and interruptions.**
   - Cases: two villagers harvesting the same nearly empty node in one tick, work interrupted mid-way, a tool breaking on its last use, a building completing while several villagers work on it.
   - Expected: no item is created or destroyed without a `created`/`destroyed` event, and stock never goes negative.
   - Tests: Tasks 3, 4 and 6 (the Hypothesis property test runs random play in debug mode).
2. **The carry limit on every path.**
   - Paths: the harvest's main output and its other outputs, recipe outputs, taking from a store, inputs returned on interruption.
   - Expected: none of these can push a villager over the limit. Each is either capped or rejected with `carry_limit`.
   - Tests: Tasks 3, 4, 5 and 6.
3. **Placement edge cases.**
   - Cases: a site at the map edge, partly on water, over a resource node or another building's footprint, or a wall placed on a villager.
   - Expected: each is rejected with a specific reason. A wall can never trap a villager inside its tiles, and a path that a new wall cuts fails with `blocked`.
   - Tests: Task 4.
4. **Ownership of stores.**
   - Expected: `take_unowned` is emitted exactly when the taker is not among the owners of a personal or shared store. A communal store never produces it, and every take produces `item_taken`.
   - Tests: Task 4.
5. **Unknown or locked identifiers in intents.**
   - Cases: an unknown action, recipe, technology, building kind, building id, node id or item id.
   - Expected: a rejection event with a reason, never a `KeyError`. Locked recipes and buildings stay unavailable until a technology unlocks them for the villager or the village.
   - Tests: Tasks 3, 4 and 5.

---

## File Structure

```
docs/adr/0014-gameplay-state-model.md            # + index row
src/pericles/core/calendar.py                     # Season.blocked_tags, Calendar.season_at
src/pericles/core/config.py                       # EngineConfig
src/pericles/core/inventory.py                    # Inventory, Tool, transfer, weights
src/pericles/core/nodes.py                        # Node, place_nodes, regrow
src/pericles/core/buildings.py                    # Ownership, Building, footprint, capacities
src/pericles/core/state.py                        # + Activity, villager and world gameplay fields
src/pericles/core/context.py                      # Context (registry, config, locked content), knows
src/pericles/core/work.py                         # actions, recipes, research, skills, tools, interrupt
src/pericles/core/construction.py                 # sites, delivery, construction, stores, blocking
src/pericles/core/invariants.py                   # item totals, conservation, non-negative, carry
src/pericles/core/intents.py                      # + StartAction, PlaceBuilding, Deliver, Construct, Deposit, Take, Craft, Research
src/pericles/core/engine.py                       # + config, handlers, work progress, regrowth, debug checks
src/pericles/core/content/registry.py             # + rule: node actions must output the node's yield
src/pericles/content/base/*.yaml                  # + buildings, recipes, technologies, tools, farming
src/pericles/experiment/defaults.py               # default four-season calendar and engine config
tests/pericles/conftest.py                        # + ECON_PACK, econ, make_world
tests/pericles/test_*.py
```

---

### Task 1: ADR-0014, engine config, season blocking, inventories

**Files:**
- Create: `docs/adr/0014-gameplay-state-model.md`, `src/pericles/core/config.py`, `src/pericles/core/inventory.py`
- Modify: `docs/adr/README.md`, `src/pericles/core/calendar.py`, `tests/pericles/conftest.py`, `tests/pericles/test_calendar.py`
- Test: `tests/pericles/test_inventory.py`, `tests/pericles/test_config.py`, `tests/pericles/test_calendar.py`

**Interfaces:**
- Consumes: `Registry` (M1a; `registry.items[id]` has `weight`, `durability`, `tags`, `modifiers`), `Calendar`, `Season` (M1a).
- Produces:
  - `calendar.Season(name: str, days: int, blocked_tags: tuple[str, ...] = ())`; `Calendar.season_at(tick: int) -> Season`
  - `config.EngineConfig(calendar: Calendar = <one 40-day season "year">, carry_limit: float = 30.0, max_skill: float = 100.0, skill_practice: float = 1.0, skill_speed_per_level: float = 0.005, debug_invariants: bool = False)`, frozen, validated in `__post_init__`
  - `inventory.UNLIMITED = 10**9`; `class InventoryError(ValueError)`; `@dataclass class Tool: item: str; durability: int` with `to_dict`/`from_dict`
  - `@dataclass class Inventory: items: dict[str, int]; tools: list[Tool]`, with methods:
    - `count(item) -> int`, `totals() -> Counter[str]`
    - `add(registry, item, qty)`, `add_tools(tools)`
    - `remove(item, qty) -> list[Tool]`
    - `has(bundle) -> bool`, `weight(registry) -> float`
    - `to_dict`/`from_dict`
  - Functions: `transfer(registry, source, target, item, qty) -> None`; `bundle_weight(registry, bundle) -> float`; `capacity_for(registry, inventory, item, limit, freed=0.0) -> int`; `fits(registry, inventory, bundle, limit, freed=0.0) -> bool`
  - `tests/pericles/conftest.py`: constant `ECON_PACK` and session fixture `econ` (a registry built from `ECON_PACK`)

- [ ] **Step 1: Write ADR-0014**

`docs/adr/0014-gameplay-state-model.md`:

```markdown
# ADR-0014: Gameplay state model

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

M1b gives villagers work: inventories, resource nodes, actions, tools, skills, buildings, stores, recipes and research (REQ-SIM-007…-014, REQ-SIM-018, REQ-ECO-001). Several mechanics are underspecified in the spec, and the item-conservation invariant (REQ-SIM-018) needs an exact contract for how items appear and disappear.

## Decision

1. **Work is an activity.** A villager has at most one `Activity`: an action, recipe, research or construction.
   - Inputs are *reserved* when the activity starts (moved out of the inventory), *consumed* when it completes, and *returned* if it is interrupted.
   - Work progresses in the tick it starts. It takes `ceil(work / speed)` ticks.
2. **Work speed** is the `work_speed` attribute resolved through the modifier system (base 1). The contributions are:
   - the world's modifiers;
   - the modifiers of each held tool that the work requires or that targets the work, using the first, most worn, instance of each tool item;
   - trait modifiers;
   - an `add` of `skill level × skill_speed_per_level` for the work's skill.
3. **Interruption.** Any new intent from a working villager first interrupts the current work (cause `actor`). The engine interrupts work it can no longer finish (cause `engine`). `Engine.interrupt` exists for interventions by other villagers (cause `intervened`, REQ-SOC-022).
4. **Item ledger.** Items are created or destroyed only by events that carry `created` and/or `destroyed` bundles. Transfers between containers (inventories, reserved inputs, delivered materials, stores) carry neither. The invariant checker compares container totals before and after each tick against these bundles.
5. **Resource nodes.**
   - A node's stock counts units of its yield item. A node action must output that item (registry rule).
   - Harvesting takes the action's yield output from the stock, capped by the remaining stock and by what the villager can carry. The action's other outputs are capped by what can be carried.
   - Regrowth is applied once per in-game day and accumulates fractions, up to the node's maximum.
6. **Locations.** "At" a node or building means within Manhattan distance 1 of the node's tile, or of any tile in the building's footprint.
7. **Buildings.**
   - A building occupies its footprint from the moment its site is placed.
   - The footprint of a building without an entrance is not walkable, and such a site cannot be placed on a villager.
   - Construction completes when every cost item has been delivered and every unit of build work is done. The delivered materials are then destroyed into the structure.
   - The pathfinding cost field is cached on the tilemap's identity plus the set of blocked tiles, so the tilemap must be replaced rather than changed in place.
   - Recipes and research at a building allow at most its `workers` simultaneous workers. Construction has no limit; build speed is `work_speed` resolved against the target `building`.
   - Construction can start only once every cost item has been delivered.
8. **Ownership** is `personal(owner)`, `shared(owners)` or `communal`. Every take from a store emits `item_taken`. A take by a villager who is not an owner of a personal or shared store also emits `take_unowned`. A communal store is owned by every villager, so it never produces `take_unowned`; laws (M3) decide whether such takes are theft.
9. **Knowledge** is a set of content IDs held by each villager and by the village.
   - Completing research adds the technology's ID and the IDs it unlocks.
   - A recipe or building that some technology unlocks is locked until the villager, or the village, knows it.
   - An action with `requires.knowledge: true` needs its own ID in the villager's or the village's knowledge. Teaching (M2) is how that knowledge spreads.
   - Research with `scope: village` unlocks for everyone and adds its modifiers globally. Otherwise it unlocks for the researcher, with villager-scoped modifiers.
   - Research speed is the `research_speed` attribute, resolved against the target `building` and the research building's kind.
10. **Seasons and defaults.**
    - Seasons carry the action tags they block.
    - The core default calendar is a single neutral season. The playable default (four seasons, with winter blocking `sowing`) lives in `pericles.experiment.defaults`, so the engine holds no game knowledge.
11. **Farming in v1** is a single `farm_grain` action at a farm, not the sow/tend/harvest cycle sketched in spec §4.2. The cycle can be added later as content plus a crop-growth mechanic.

## Consequences

+ One mechanism (activities plus modifiers) serves every kind of work. Interruption is uniform.
+ Conservation can be checked mechanically on every tick.
− Interrupting is lossless, so the cost of an interruption is only the time spent.
− Farming is simplified, and spec §4.2's sow/tend/harvest row is deferred (amended here).
```

Add to `docs/adr/README.md` after the 0013 row:

```markdown
| [0014](0014-gameplay-state-model.md) | Gameplay state model | Accepted |
```

- [ ] **Step 2: Add the econ test pack fixture**

Append to `tests/pericles/conftest.py`. Merge the new imports with the existing ones at the top of the file:

```python
ECON_PACK = """
terrains:
  - {id: grass, walkable: true, color: "#8fb35a"}
  - {id: water, walkable: false, color: "#3b6ea5"}
  - {id: forest, walkable: true, move_cost: 2.0, color: "#2f5d2e"}
items:
  - {id: wood, weight: 2.0}
  - {id: berries, weight: 0.5, nutrition: 10, tags: [food]}
  - {id: plank, weight: 1.0}
  - {id: seed, weight: 0.1}
  - {id: token, weight: 0.0}
  - id: axe
    weight: 2.0
    durability: 3
    tags: [tool, axe]
    modifiers:
      - {target: {kind: action, id: chop}, attribute: work_speed, op: mul, value: 2.0}
  - {id: hammer, weight: 1.0, durability: 2, tags: [tool, hammer]}
nodes:
  - {id: tree, yields: wood, terrains: [forest], density: 1.0, stock: 6, regrowth_per_day: 1.5}
  - {id: bush, yields: berries, terrains: [grass], density: 0.01, stock: 4}
actions:
  - {id: chop, duration_ticks: 10, outputs: {wood: 2}, skill: woodcutting, location: {node: tree}, tags: [labour]}
  - {id: pick, duration_ticks: 4, outputs: {berries: 2}, location: {node: bush}, tags: [labour]}
  - {id: whittle, duration_ticks: 6, inputs: {wood: 1}, outputs: {plank: 2}, requires: {tools: [hammer]}, tags: [craft]}
  - {id: sow, duration_ticks: 5, inputs: {seed: 1}, outputs: {berries: 1}, location: {terrains: [grass]}, tags: [sowing]}
  - {id: carve, duration_ticks: 8, outputs: {plank: 1}, skill: carving, requires: {skill: carving, min_skill: 5}}
  - {id: secret_art, duration_ticks: 3, outputs: {plank: 1}, requires: {knowledge: true}}
  - {id: tinker, duration_ticks: 2, outputs: {plank: 1}, location: {building: workshop}}
  - {id: nail, duration_ticks: 2, outputs: {plank: 1}, requires: {tools: [tool, hammer]}}
  - {id: log, duration_ticks: 2, outputs: {wood: 1, plank: 10}, location: {node: tree}}
buildings:
  - {id: hut, cost: {wood: 4}, build_work: 20, footprint: [2, 1], storage: 10, housing: 2}
  - {id: wall, cost: {wood: 1}, build_work: 5, entrance: false}
  - {id: workshop, cost: {wood: 2}, build_work: 10, workers: 1}
  - {id: academy, cost: {wood: 2}, build_work: 10, workers: 2}
  - {id: vault, cost: {plank: 2}, build_work: 10, storage: 5}
recipes:
  - {id: saw, building: workshop, inputs: {wood: 2}, outputs: {plank: 3}, work_ticks: 6, skill: carpentry}
  - {id: press, building: workshop, inputs: {berries: 2}, outputs: {plank: 2}, work_ticks: 2}
  - {id: make_axe, building: workshop, inputs: {wood: 1, plank: 1}, outputs: {axe: 1}, work_ticks: 4}
technologies:
  - id: lore
    building: academy
    cost: {plank: 1}
    research_ticks: 5
    unlocks_recipes: [make_axe]
    unlocks_buildings: [vault]
    modifiers:
      - {target: {kind: recipe, id: saw}, attribute: work_speed, op: mul, value: 2.0}
  - id: commons
    building: academy
    research_ticks: 3
    scope: village
    modifiers:
      - {target: {kind: action, tag: labour}, attribute: work_speed, op: add, value: 1.0}
traits:
  - id: strong
    description: Strong.
    modifiers:
      - {target: {kind: action, tag: labour}, attribute: work_speed, op: mul, value: 2.0}
"""


@pytest.fixture(scope="session")
def econ(tmp_path_factory: pytest.TempPathFactory) -> Registry:
    root = tmp_path_factory.mktemp("packs") / "econ"
    root.mkdir()
    (root / "content.yaml").write_text(ECON_PACK, encoding="utf-8")
    return load_registry([root])
```

- [ ] **Step 3: Write the failing tests**

`tests/pericles/test_inventory.py`:

```python
from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pericles.core.content.registry import Registry
from pericles.core.inventory import (
    UNLIMITED,
    Inventory,
    InventoryError,
    Tool,
    bundle_weight,
    capacity_for,
    fits,
    transfer,
)

pytestmark = pytest.mark.req("REQ-SIM-013")


def test_stackable_items_are_counted(econ: Registry) -> None:
    """AC1: quantities are tracked per item and empty entries disappear."""
    inv = Inventory()
    inv.add(econ, "wood", 3)
    inv.add(econ, "wood", 2)
    inv.add(econ, "berries", 0)
    assert inv.items == {"wood": 5}
    assert (inv.count("wood"), inv.count("plank")) == (5, 0)
    assert inv.remove("wood", 5) == []
    assert inv.items == {}


def test_tools_are_individual_instances(econ: Registry) -> None:
    """AC1: tools are held as instances with their own durability (REQ-SIM-010 AC2)."""
    inv = Inventory()
    inv.add(econ, "axe", 2)
    assert inv.items == {}
    assert inv.tools == [Tool("axe", 3), Tool("axe", 3)]
    assert inv.count("axe") == 2


def test_tools_are_sorted_and_removed_most_worn_first() -> None:
    """AC1: tool order is canonical; the most worn instance leaves first."""
    inv = Inventory()
    inv.add_tools([Tool("hammer", 2), Tool("axe", 3), Tool("axe", 1)])
    assert inv.tools == [Tool("axe", 1), Tool("axe", 3), Tool("hammer", 2)]
    assert inv.remove("axe", 1) == [Tool("axe", 1)]
    assert inv.tools == [Tool("axe", 3), Tool("hammer", 2)]


def test_removing_more_than_held_fails_and_changes_nothing(econ: Registry) -> None:
    """AC1: an inventory never holds a negative quantity."""
    inv = Inventory()
    inv.add(econ, "wood", 2)
    with pytest.raises(InventoryError, match=r"^holds 2 wood, cannot remove 3$"):
        inv.remove("wood", 3)
    assert inv.items == {"wood": 2}
    with pytest.raises(InventoryError, match=r"^holds 0 axe, cannot remove 1$"):
        inv.remove("axe", 1)


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_negative_quantities_are_rejected(econ: Registry, operation: str) -> None:
    """AC1: negative quantities are never accepted."""
    inv = Inventory()
    with pytest.raises(InventoryError, match="negative quantity"):
        if operation == "add":
            inv.add(econ, "wood", -1)
        else:
            inv.remove("wood", -1)
    assert inv == Inventory()


def test_transfer_moves_items_and_keeps_tool_durability(econ: Registry) -> None:
    """AC1: transfers move exact quantities; tools keep their wear."""
    source, target = Inventory(), Inventory()
    source.add(econ, "wood", 4)
    source.add_tools([Tool("axe", 1), Tool("axe", 3)])
    transfer(econ, source, target, "wood", 3)
    transfer(econ, source, target, "axe", 1)
    assert source.items == {"wood": 1}
    assert source.tools == [Tool("axe", 3)]
    assert target.items == {"wood": 3}
    assert target.tools == [Tool("axe", 1)]


def test_totals_and_bundles(econ: Registry) -> None:
    """AC1: totals merge stackables and tools; bundles are checked against them."""
    inv = Inventory()
    inv.add(econ, "wood", 2)
    inv.add(econ, "axe", 2)
    assert inv.totals() == Counter({"wood": 2, "axe": 2})
    assert inv.has({"wood": 2, "axe": 1})
    assert inv.has({})
    assert not inv.has({"wood": 3})


def test_weight_counts_items_and_tools(econ: Registry) -> None:
    """AC2: carried weight is the sum of item weights."""
    inv = Inventory()
    inv.add(econ, "wood", 3)
    inv.add(econ, "axe", 1)
    inv.add(econ, "seed", 2)
    assert inv.weight(econ) == pytest.approx(3 * 2.0 + 2.0 + 2 * 0.1)
    assert bundle_weight(econ, {"wood": 2, "berries": 4}) == pytest.approx(6.0)


def test_capacity_for(econ: Registry) -> None:
    """AC2: how many units of an item still fit under the carry limit."""
    inv = Inventory()
    assert capacity_for(econ, inv, "wood", 30.0) == 15
    assert capacity_for(econ, inv, "seed", 0.3) == 3  # 0.3 / 0.1 must not round down to 2
    inv.add(econ, "wood", 14)
    assert capacity_for(econ, inv, "wood", 30.0) == 1
    assert capacity_for(econ, inv, "wood", 30.0, freed=2.0) == 2
    inv.add(econ, "wood", 1)
    assert capacity_for(econ, inv, "wood", 30.0) == 0
    assert capacity_for(econ, inv, "wood", 29.0) == 0  # over the limit never gives a negative count
    assert capacity_for(econ, inv, "token", 1.0) == UNLIMITED


def test_fits(econ: Registry) -> None:
    """AC2: a bundle fits if the resulting weight stays within the limit."""
    inv = Inventory()
    inv.add(econ, "wood", 14)  # 28
    assert fits(econ, inv, {"wood": 1}, 30.0)
    assert not fits(econ, inv, {"wood": 2}, 30.0)
    assert fits(econ, inv, {"wood": 2}, 30.0, freed=2.0)
    assert fits(econ, inv, {}, 28.0)
    assert not fits(econ, inv, {}, 27.9)


def test_round_trip(econ: Registry) -> None:
    """AC1: inventories serialise exactly."""
    inv = Inventory()
    inv.add(econ, "wood", 2)
    inv.add_tools([Tool("axe", 1)])
    data = inv.to_dict()
    assert data == {"items": {"wood": 2}, "tools": [{"item": "axe", "durability": 1}]}
    assert Inventory.from_dict(data) == inv


ITEMS = ["wood", "berries", "axe", "hammer"]


@settings(max_examples=100, deadline=None)
@given(
    st.lists(
        st.tuples(st.sampled_from(ITEMS), st.integers(-2, 5), st.booleans()), max_size=40
    )
)
def test_quantities_never_go_negative(
    econ: Registry, ops: list[tuple[str, int, bool]]
) -> None:
    """AC1 (property): any sequence of adds and removes keeps every count exact and ≥ 0."""
    inv = Inventory()
    expected: Counter[str] = Counter()
    for item, qty, adding in ops:
        try:
            if adding:
                inv.add(econ, item, qty)
            else:
                inv.remove(item, qty)
        except InventoryError:
            assert qty < 0 or (not adding and expected[item] < qty)
            continue
        expected[item] += qty if adding else -qty
    assert all(n > 0 for n in inv.items.values())
    assert all(tool.durability > 0 for tool in inv.tools)
    assert +inv.totals() == +expected
```

`tests/pericles/test_config.py`:

```python
import pytest

from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig


@pytest.mark.req("REQ-SIM-013")
def test_defaults() -> None:
    """AC2: the carry limit is an engine parameter with a documented default."""
    config = EngineConfig()
    assert config.carry_limit == 30.0
    assert (config.max_skill, config.skill_practice, config.skill_speed_per_level) == (
        100.0,
        1.0,
        0.005,
    )
    assert config.debug_invariants is False
    assert config.calendar == Calendar(seasons=(Season("year", 40),))


@pytest.mark.req("REQ-SIM-014")
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"carry_limit": 0.0}, "carry_limit must be positive"),
        ({"max_skill": 0.0}, "max_skill must be positive"),
        ({"skill_practice": -1.0}, "skill rates must be non-negative"),
        ({"skill_speed_per_level": -0.1}, "skill rates must be non-negative"),
    ],
)
def test_invalid_config_is_rejected(kwargs: dict[str, float], message: str) -> None:
    """AC1/AC2: skill parameters are validated."""
    with pytest.raises(ValueError, match=f"^{message}$"):
        EngineConfig(**kwargs)  # type: ignore[arg-type]
```

Append to `tests/pericles/test_calendar.py`:

```python
@pytest.mark.req("REQ-SIM-003")
def test_season_at_returns_the_season_with_its_blocked_tags() -> None:
    """AC2: seasons carry the action tags they block, looked up by tick."""
    winter = Season("winter", 3, blocked_tags=("sowing",))
    calendar = Calendar(seasons=(Season("spring", 2), winter))
    per_day = calendar.ticks_per_day
    assert calendar.season_at(0) == Season("spring", 2)
    assert calendar.season_at(2 * per_day) is winter
    assert calendar.season_at(5 * per_day - 1) is winter
    assert calendar.season_at(5 * per_day) == Season("spring", 2)
    assert Season("x", 1).blocked_tags == ()
    with pytest.raises(ValueError, match="^tick must be non-negative$"):
        calendar.season_at(-1)
```

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/pericles/test_inventory.py tests/pericles/test_config.py tests/pericles/test_calendar.py -q`
Expected: collection errors, `ModuleNotFoundError: No module named 'pericles.core.inventory'` and `... 'pericles.core.config'`. The new calendar test fails with `TypeError` (unexpected keyword `blocked_tags`).

- [ ] **Step 5: Implement the calendar change**

In `src/pericles/core/calendar.py`, replace the `Season` class:

```python
@dataclass(frozen=True)
class Season:
    name: str
    days: int
    blocked_tags: tuple[str, ...] = ()
```

Replace the `time_of` method with these two methods and a new `season_at`:

```python
    def _locate(self, tick: int) -> tuple[int, int, int, Season, int]:
        """(day, minute_of_day, year, season, day_of_season) for a tick."""
        if tick < 0:
            raise ValueError("tick must be non-negative")
        day, minute = divmod(tick * self.tick_minutes, self.day_minutes)
        year, day_of_year = divmod(day, self.days_per_year)
        for season in self.seasons:
            if day_of_year < season.days:
                return day, minute, year, season, day_of_year
            day_of_year -= season.days
        raise AssertionError("unreachable")  # pragma: no mutate - day_of_year < days_per_year

    def time_of(self, tick: int) -> GameTime:
        day, minute, year, season, day_of_season = self._locate(tick)
        return GameTime(
            tick=tick,
            day=day,
            minute_of_day=minute,
            year=year,
            season=season.name,
            day_of_season=day_of_season,
            is_daytime=self.sunrise_minute <= minute < self.sunset_minute,
        )

    def season_at(self, tick: int) -> Season:
        return self._locate(tick)[3]
```

- [ ] **Step 6: Implement `src/pericles/core/config.py`**

```python
"""Engine parameters (ADR-0014)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pericles.core.calendar import Calendar, Season


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

    def __post_init__(self) -> None:
        if self.carry_limit <= 0:
            raise ValueError("carry_limit must be positive")
        if self.max_skill <= 0:
            raise ValueError("max_skill must be positive")
        if self.skill_practice < 0 or self.skill_speed_per_level < 0:
            raise ValueError("skill rates must be non-negative")
```

- [ ] **Step 7: Implement `src/pericles/core/inventory.py`**

```python
"""Inventories: stackable items, tool instances and carried weight (REQ-SIM-013, ADR-0014)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pericles.core.content.registry import Registry

UNLIMITED = 10**9
EPSILON = 1e-9


class InventoryError(ValueError):
    """An operation would make a held quantity negative."""


@dataclass
class Tool:
    item: str
    durability: int

    def to_dict(self) -> dict[str, Any]:
        return {"item": self.item, "durability": self.durability}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Tool:
        return cls(str(data["item"]), int(data["durability"]))


@dataclass
class Inventory:
    items: dict[str, int] = field(default_factory=dict)
    tools: list[Tool] = field(default_factory=list)

    def count(self, item: str) -> int:
        return self.items.get(item, 0) + sum(1 for tool in self.tools if tool.item == item)

    def totals(self) -> Counter[str]:
        totals = Counter(self.items)
        totals.update(tool.item for tool in self.tools)
        return totals

    def add(self, registry: Registry, item: str, qty: int) -> None:
        if qty < 0:
            raise InventoryError(f"cannot add a negative quantity ({qty} {item})")
        durability = registry.items[item].durability
        if durability is None:
            if qty:
                self.items[item] = self.items.get(item, 0) + qty
        else:
            self.add_tools(Tool(item, durability) for _ in range(qty))

    def add_tools(self, tools: Iterable[Tool]) -> None:
        self.tools.extend(tools)
        self.tools.sort(key=lambda tool: (tool.item, tool.durability))

    def remove(self, item: str, qty: int) -> list[Tool]:
        """Remove `qty` units. Tools leave most-worn first and are returned."""
        if qty < 0:
            raise InventoryError(f"cannot remove a negative quantity ({qty} {item})")
        held = self.count(item)
        if held < qty:
            raise InventoryError(f"holds {held} {item}, cannot remove {qty}")
        if item in self.items:
            left = self.items[item] - qty
            if left:
                self.items[item] = left
            else:
                del self.items[item]
            return []
        removed = [tool for tool in self.tools if tool.item == item][:qty]
        for tool in removed:
            self.tools.remove(tool)
        return removed

    def has(self, bundle: Mapping[str, int]) -> bool:
        return all(self.count(item) >= qty for item, qty in bundle.items())

    def weight(self, registry: Registry) -> float:
        stacked = sum(registry.items[item].weight * qty for item, qty in self.items.items())
        return stacked + sum(registry.items[tool.item].weight for tool in self.tools)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": dict(sorted(self.items.items())),
            "tools": [tool.to_dict() for tool in self.tools],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Inventory:
        return cls(
            {str(item): int(qty) for item, qty in data["items"].items()},
            [Tool.from_dict(tool) for tool in data["tools"]],
        )


def transfer(registry: Registry, source: Inventory, target: Inventory, item: str, qty: int) -> None:
    tools = source.remove(item, qty)
    if tools:
        target.add_tools(tools)
    else:
        target.add(registry, item, qty)


def bundle_weight(registry: Registry, bundle: Mapping[str, int]) -> float:
    return sum(registry.items[item].weight * qty for item, qty in bundle.items())


def capacity_for(
    registry: Registry, inventory: Inventory, item: str, limit: float, freed: float = 0.0
) -> int:
    """How many more units of `item` fit under `limit` (after `freed` weight leaves)."""
    unit = registry.items[item].weight
    if unit == 0:
        return UNLIMITED
    free = limit - inventory.weight(registry) + freed
    return max(0, math.floor(free / unit + EPSILON))


def fits(
    registry: Registry,
    inventory: Inventory,
    bundle: Mapping[str, int],
    limit: float,
    freed: float = 0.0,
) -> bool:
    total = inventory.weight(registry) - freed + bundle_weight(registry, bundle)
    return total <= limit + EPSILON
```

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass, including every existing calendar test.

- [ ] **Step 9: Gates, ADR check, mutation, commit**

Run the gates, then `PYTHONPATH=tools uv run python -m pericles_tools.adr check`. Expected: `ADRs OK`.

Run: `rm -rf mutants && uv run mutmut run "pericles.core.inventory.*" "pericles.core.config.*" "pericles.core.calendar.*" ; uv run mutmut results --all true`
Kill every non-equivalent survivor with a test, then `rm -rf mutants`.

```bash
git add docs/adr src/pericles/core tests/pericles
git commit -m "feat(core): ADR-0014, engine config, season blocking and inventories"
```

---

### Task 2: World data: resource nodes, buildings and ownership, gameplay state

**Files:**
- Create: `src/pericles/core/nodes.py`, `src/pericles/core/buildings.py`
- Modify: `src/pericles/core/state.py`, `tests/pericles/conftest.py`, `tests/pericles/test_state.py`
- Test: `tests/pericles/test_nodes.py`, `tests/pericles/test_buildings_model.py`, `tests/pericles/test_state.py`

**Interfaces:**
- Consumes: `Inventory`, `Tool` (Task 1); `Registry`, `TileMap`, `Coord`, `generate_map`, the `registry`, `map_params` and `small_map` fixtures (M1a); the `econ` fixture (Task 1).
- Produces:
  - `nodes.Node(id: str, kind: str, pos: Coord, stock: int, regrow: float = 0.0)`, mutable, with `to_dict`/`from_dict`
  - `nodes.place_nodes(seed: int, tilemap: TileMap, registry: Registry) -> list[Node]`
  - `nodes.regrow(nodes: Iterable[Node], registry: Registry) -> None` (one in-game day)
  - `buildings.OWNERSHIP_KINDS = ("personal", "shared", "communal")`
  - `buildings.Ownership(kind: str, owners: tuple[str, ...] = ())`, frozen and validated, with `owned_by(villager) -> bool` and `to_dict`/`from_dict`
  - `buildings.Building(id, kind, origin: Coord, ownership: Ownership, delivered: dict[str, int] = {}, work_done: float = 0.0, complete: bool = False, storage: Inventory = Inventory())`, with `to_dict`/`from_dict`
  - Functions in `buildings`: `footprint(origin, size) -> list[Coord]`; `building_tiles(building, registry) -> list[Coord]`; `near(pos, tiles) -> bool`; `remaining_cost(building, registry) -> dict[str, int]`; `housing_capacity(registry, building) -> int`; `storage_capacity(registry, building) -> int`
  - `state.Activity(kind: str, ident: str, target: str | None, work: float, done: float, speed: float, reserved: Inventory = Inventory())`, with `to_dict`/`from_dict`
  - `state.Villager` gains `inventory: Inventory`, `skills: dict[str, float]`, `knowledge: set[str]`, `traits: tuple[str, ...]`, `activity: Activity | None` (all defaulted)
  - `state.WorldState` gains `nodes: dict[str, Node]`, `buildings: dict[str, Building]`, `village_knowledge: set[str]`, `next_building: int` (all defaulted). `WorldState.new(seed, tilemap, villagers=(), nodes=())` raises on a duplicate node id.
  - `tests/pericles/conftest.py`: fixture `make_world`, returning `make(rows: Sequence[str], villagers=(), nodes=(), seed=1) -> WorldState`. In `rows`, `.` is grass, `~` is water and `T` is forest.

- [ ] **Step 1: Add the `make_world` fixture**

Append to `tests/pericles/conftest.py`. Merge the imports at the top: `from collections.abc import Callable, Iterable, Sequence`, `from pericles.core.nodes import Node`, `from pericles.core.state import Villager, WorldState`.

```python
TERRAIN = {".": "grass", "~": "water", "T": "forest"}


@pytest.fixture
def make_world() -> Callable[..., WorldState]:
    def make(
        rows: Sequence[str],
        villagers: Iterable[Villager] = (),
        nodes: Iterable[Node] = (),
        seed: int = 1,
    ) -> WorldState:
        terrain = [TERRAIN[char] for row in rows for char in row]
        tilemap = TileMap(len(rows[0]), len(rows), terrain, [0.0] * len(terrain))
        return WorldState.new(seed, tilemap, villagers, nodes=nodes)

    return make
```

- [ ] **Step 2: Write the failing tests**

`tests/pericles/test_nodes.py`:

```python
import pytest

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import MapParams, generate_map
from pericles.core.nodes import Node, place_nodes, regrow

pytestmark = pytest.mark.req("REQ-SIM-007")


def dicts(nodes: list[Node]) -> list[dict[str, object]]:
    return [node.to_dict() for node in nodes]


def test_placement_is_seeded(registry: Registry, map_params: MapParams) -> None:
    """AC1/AC2: node placement is deterministic per seed and varies across seeds."""
    tilemap = generate_map(3, map_params, registry)
    assert dicts(place_nodes(5, tilemap, registry)) == dicts(place_nodes(5, tilemap, registry))
    assert dicts(place_nodes(5, tilemap, registry)) != dicts(place_nodes(6, tilemap, registry))


def test_nodes_sit_on_their_terrains_one_per_tile(
    registry: Registry, map_params: MapParams
) -> None:
    """AC1/AC2: nodes start full, on a terrain their definition allows, at most one per tile."""
    tilemap = generate_map(3, map_params, registry)
    nodes = place_nodes(5, tilemap, registry)
    assert [node.id for node in nodes] == [f"n{i}" for i in range(len(nodes))]
    indexes = [node.pos.y * tilemap.width + node.pos.x for node in nodes]
    assert indexes == sorted(set(indexes))
    for node in nodes:
        definition = registry.nodes[node.kind]
        assert tilemap.terrain_at(node.pos) in definition.terrains
        assert (node.stock, node.regrow) == (definition.stock, 0.0)
    assert {node.kind for node in nodes} >= {"tree", "boulder", "berry_bush"}


def test_density_is_respected(registry: Registry, map_params: MapParams) -> None:
    """AC2: trees cover about their configured share (0.5) of forest tiles."""
    tilemap = generate_map(3, map_params, registry)
    forest = tilemap.counts()["forest"]
    trees = sum(1 for node in place_nodes(5, tilemap, registry) if node.kind == "tree")
    assert 0.4 <= trees / forest <= 0.6


def test_regrowth_accumulates_fractions_up_to_the_maximum(econ: Registry) -> None:
    """AC2: a node regrows at its configured rate up to its maximum."""
    tree = Node("n0", "tree", Coord(0, 0), stock=2)  # maximum 6, 1.5 per day
    days = []
    for _ in range(4):
        regrow([tree], econ)
        days.append((tree.stock, tree.regrow))
    assert days == [(3, 0.5), (5, 0.0), (6, 0.0), (6, 0.0)]


def test_regrowth_is_capped(econ: Registry) -> None:
    """AC2: regrowth never exceeds the maximum and drops the remainder."""
    tree = Node("n0", "tree", Coord(0, 0), stock=5, regrow=0.9)
    regrow([tree], econ)
    assert (tree.stock, tree.regrow) == (6, 0.0)


def test_nodes_without_regrowth_stay_put(econ: Registry) -> None:
    """AC2: a node with rate 0 never regrows."""
    bush = Node("n1", "bush", Coord(0, 0), stock=1)
    regrow([bush], econ)
    assert (bush.stock, bush.regrow) == (1, 0.0)


def test_round_trip() -> None:
    node = Node("n3", "tree", Coord(4, 2), stock=1, regrow=0.25)
    assert node.to_dict() == {"id": "n3", "kind": "tree", "pos": [4, 2], "stock": 1, "regrow": 0.25}
    clone = Node.from_dict(node.to_dict())
    assert clone == node
    assert isinstance(clone.pos, Coord)
```

`tests/pericles/test_buildings_model.py`:

```python
import pytest

from pericles.core.buildings import (
    Building,
    Ownership,
    building_tiles,
    footprint,
    housing_capacity,
    near,
    remaining_cost,
    storage_capacity,
)
from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord


@pytest.mark.req("REQ-ECO-001")
@pytest.mark.parametrize(
    ("kind", "owners"), [("personal", ("a",)), ("shared", ("a", "b")), ("communal", ())]
)
def test_valid_ownerships(kind: str, owners: tuple[str, ...]) -> None:
    """AC1: ownership is personal(owner), shared(owners) or communal."""
    ownership = Ownership(kind, owners)
    assert ownership.to_dict() == {"kind": kind, "owners": list(owners)}
    assert Ownership.from_dict(ownership.to_dict()) == ownership


@pytest.mark.req("REQ-ECO-001")
@pytest.mark.parametrize(
    ("kind", "owners", "message"),
    [
        ("private", ("a",), "unknown ownership kind 'private'"),
        ("communal", ("a",), "communal ownership has no owners"),
        ("personal", (), "personal ownership needs exactly one owner"),
        ("personal", ("a", "b"), "personal ownership needs exactly one owner"),
        ("shared", ("a",), "shared ownership needs at least two owners"),
        ("shared", ("b", "a"), "owners must be sorted and unique"),
        ("shared", ("a", "a"), "owners must be sorted and unique"),
    ],
)
def test_invalid_ownerships(kind: str, owners: tuple[str, ...], message: str) -> None:
    """AC1: malformed ownership is rejected."""
    with pytest.raises(ValueError, match=f"^{message}$"):
        Ownership(kind, owners)


@pytest.mark.req("REQ-ECO-001")
def test_owned_by() -> None:
    """AC1: owners of personal and shared property; everyone for communal property."""
    assert Ownership("personal", ("a",)).owned_by("a")
    assert not Ownership("personal", ("a",)).owned_by("b")
    shared = Ownership("shared", ("a", "c"))
    assert shared.owned_by("c")
    assert not shared.owned_by("b")
    assert Ownership("communal").owned_by("anyone")


@pytest.mark.req("REQ-SIM-009")
def test_footprint_and_nearness() -> None:
    """AC1: footprints are row-major rectangles; 'near' is Manhattan distance ≤ 1."""
    assert footprint(Coord(3, 4), (2, 1)) == [Coord(3, 4), Coord(4, 4)]
    assert footprint(Coord(0, 0), (2, 2)) == [Coord(0, 0), Coord(1, 0), Coord(0, 1), Coord(1, 1)]
    tiles = footprint(Coord(3, 4), (2, 1))
    assert near(Coord(5, 4), tiles)
    assert near(Coord(3, 3), tiles)
    assert near(Coord(4, 4), tiles)
    assert not near(Coord(5, 5), tiles)
    assert not near(Coord(1, 4), tiles)


@pytest.mark.req("REQ-SIM-009")
def test_building_tiles_and_remaining_cost(econ: Registry) -> None:
    """AC2: the remaining cost shrinks as materials are delivered."""
    hut = Building("b0", "hut", Coord(1, 1), Ownership("personal", ("a",)))
    assert building_tiles(hut, econ) == [Coord(1, 1), Coord(2, 1)]
    assert remaining_cost(hut, econ) == {"wood": 4}
    hut.delivered["wood"] = 3
    assert remaining_cost(hut, econ) == {"wood": 1}
    hut.delivered["wood"] = 4
    assert remaining_cost(hut, econ) == {}


@pytest.mark.req("REQ-SIM-009")
def test_capacities_exist_only_when_complete(econ: Registry) -> None:
    """AC3: a completed building provides its declared housing and storage."""
    hut = Building("b0", "hut", Coord(1, 1), Ownership("personal", ("a",)))
    assert (housing_capacity(econ, hut), storage_capacity(econ, hut)) == (0, 0)
    hut.complete = True
    assert (housing_capacity(econ, hut), storage_capacity(econ, hut)) == (2, 10)


def test_building_round_trip(econ: Registry) -> None:
    hut = Building(
        "b0", "hut", Coord(1, 1), Ownership("shared", ("a", "b")), {"wood": 2}, 3.5, False
    )
    hut.storage.add(econ, "wood", 1)
    data = hut.to_dict()
    assert data == {
        "id": "b0",
        "kind": "hut",
        "origin": [1, 1],
        "ownership": {"kind": "shared", "owners": ["a", "b"]},
        "delivered": {"wood": 2},
        "work_done": 3.5,
        "complete": False,
        "storage": {"items": {"wood": 1}, "tools": []},
    }
    clone = Building.from_dict(data)
    assert clone == hut
    assert isinstance(clone.origin, Coord)
```

Append to `tests/pericles/test_state.py`. Add these imports at the top: `from pericles.core.buildings import Building, Ownership`, `from pericles.core.content.registry import Registry`, `from pericles.core.inventory import Inventory`, `from pericles.core.nodes import Node`, `from pericles.core.state import Activity`.

```python
def rich_state(econ: Registry) -> WorldState:
    tilemap = TileMap(3, 1, ["grass", "forest", "grass"], [0.0] * 3)
    villager = Villager(
        "a",
        "Ana",
        Coord(0, 0),
        skills={"woodcutting": 2.5},
        knowledge={"lore", "commons"},
        traits=("strong",),
    )
    villager.inventory.add(econ, "wood", 2)
    villager.inventory.add(econ, "axe", 1)
    reserved = Inventory()
    reserved.add(econ, "seed", 1)
    villager.activity = Activity("action", "sow", None, 5.0, 2.0, 1.0, reserved)
    state = WorldState.new(
        7, tilemap, [villager], nodes=[Node("n0", "tree", Coord(1, 0), 4, 0.5)]
    )
    state.buildings["b0"] = Building(
        "b0", "hut", Coord(2, 0), Ownership("personal", ("a",)), {"wood": 1}
    )
    state.village_knowledge = {"commons"}
    state.next_building = 1
    return state


def test_gameplay_state_round_trips(econ: Registry) -> None:
    """AC1: nodes, buildings, inventories, skills, knowledge and work survive a round trip."""
    state = rich_state(econ)
    clone = WorldState.from_dict(state.to_dict())
    assert clone.digest() == state.digest()
    assert clone.villagers == state.villagers
    assert clone.nodes == state.nodes
    assert clone.buildings == state.buildings
    assert (clone.village_knowledge, clone.next_building) == ({"commons"}, 1)


def test_villager_dict_is_canonical(econ: Registry) -> None:
    """AC1: sets and dicts serialise in sorted order."""
    data = rich_state(econ).to_dict()["villagers"][0]
    assert data["knowledge"] == ["commons", "lore"]
    assert data["skills"] == {"woodcutting": 2.5}
    assert data["traits"] == ["strong"]
    assert data["inventory"] == {"items": {"wood": 2}, "tools": [{"item": "axe", "durability": 3}]}
    assert data["activity"] == {
        "kind": "action",
        "ident": "sow",
        "target": None,
        "work": 5.0,
        "done": 2.0,
        "speed": 1.0,
        "reserved": {"items": {"seed": 1}, "tools": []},
    }


def _set_stock(s: WorldState) -> None:
    s.nodes["n0"].stock = 3


def _add_village_knowledge(s: WorldState) -> None:
    s.village_knowledge.add("x")


def _bump_building_counter(s: WorldState) -> None:
    s.next_building = 2


def _train(s: WorldState) -> None:
    s.villagers["a"].skills["woodcutting"] = 3.0


def _stop_work(s: WorldState) -> None:
    s.villagers["a"].activity = None


def _deliver_more(s: WorldState) -> None:
    s.buildings["b0"].delivered["wood"] = 2


@pytest.mark.parametrize(
    "mutate",
    [_set_stock, _add_village_knowledge, _bump_building_counter, _train, _stop_work, _deliver_more],
)
def test_digest_covers_gameplay_fields(econ: Registry, mutate: object) -> None:
    """AC1: every gameplay field is part of the state digest."""
    base = rich_state(econ).digest()
    state = rich_state(econ)
    mutate(state)  # type: ignore[operator]
    assert state.digest() != base


def test_duplicate_node_ids_are_rejected(small_map: TileMap) -> None:
    nodes = [Node("n0", "tree", Coord(0, 0), 1), Node("n0", "tree", Coord(1, 0), 1)]
    with pytest.raises(ValueError, match="duplicate node id 'n0'"):
        WorldState.new(1, small_map, nodes=nodes)


def test_new_world_has_empty_gameplay_fields(small_map: TileMap) -> None:
    state = WorldState.new(1, small_map)
    assert (state.nodes, state.buildings, state.village_knowledge, state.next_building) == (
        {},
        {},
        set(),
        0,
    )
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/pericles -q`
Expected: collection errors: `ModuleNotFoundError: No module named 'pericles.core.nodes'` (raised from conftest).

- [ ] **Step 4: Implement `src/pericles/core/nodes.py`**

```python
"""Resource nodes: placement and regrowth (REQ-SIM-007, ADR-0014)."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap


@dataclass
class Node:
    id: str
    kind: str
    pos: Coord
    stock: int
    regrow: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "pos": list(self.pos),
            "stock": self.stock,
            "regrow": self.regrow,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Node:
        return cls(
            str(data["id"]),
            str(data["kind"]),
            Coord(*data["pos"]),
            int(data["stock"]),
            float(data["regrow"]),
        )


def place_nodes(seed: int, tilemap: TileMap, registry: Registry) -> list[Node]:
    """Scatter full nodes over matching terrain, row-major, at most one per tile."""
    rng = random.Random(f"pericles-nodes-{seed}")
    kinds = sorted(registry.nodes)
    nodes: list[Node] = []
    for index, terrain in enumerate(tilemap.terrain):
        for kind in kinds:
            definition = registry.nodes[kind]
            if terrain in definition.terrains and rng.random() < definition.density:
                y, x = divmod(index, tilemap.width)
                nodes.append(Node(f"n{len(nodes)}", kind, Coord(x, y), definition.stock))
                break
    return nodes


def regrow(nodes: Iterable[Node], registry: Registry) -> None:
    """Apply one in-game day of regrowth."""
    for node in nodes:
        maximum = registry.nodes[node.kind].stock
        if node.stock >= maximum:
            node.regrow = 0.0
            continue
        node.regrow += registry.nodes[node.kind].regrowth_per_day
        whole = int(node.regrow)
        node.regrow -= whole
        node.stock = min(maximum, node.stock + whole)
        if node.stock == maximum:
            node.regrow = 0.0
```

- [ ] **Step 5: Implement `src/pericles/core/buildings.py`**

```python
"""Buildings and ownership (REQ-SIM-009, REQ-ECO-001, ADR-0014)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory

OWNERSHIP_KINDS = ("personal", "shared", "communal")


@dataclass(frozen=True)
class Ownership:
    kind: str
    owners: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in OWNERSHIP_KINDS:
            raise ValueError(f"unknown ownership kind {self.kind!r}")
        if self.kind == "communal" and self.owners:
            raise ValueError("communal ownership has no owners")
        if self.kind == "personal" and len(self.owners) != 1:
            raise ValueError("personal ownership needs exactly one owner")
        if self.kind == "shared" and len(self.owners) < 2:
            raise ValueError("shared ownership needs at least two owners")
        if tuple(sorted(set(self.owners))) != self.owners:
            raise ValueError("owners must be sorted and unique")

    def owned_by(self, villager: str) -> bool:
        return self.kind == "communal" or villager in self.owners

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "owners": list(self.owners)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Ownership:
        return cls(str(data["kind"]), tuple(str(owner) for owner in data["owners"]))


@dataclass
class Building:
    id: str
    kind: str
    origin: Coord
    ownership: Ownership
    delivered: dict[str, int] = field(default_factory=dict)
    work_done: float = 0.0
    complete: bool = False
    storage: Inventory = field(default_factory=Inventory)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "origin": list(self.origin),
            "ownership": self.ownership.to_dict(),
            "delivered": dict(sorted(self.delivered.items())),
            "work_done": self.work_done,
            "complete": self.complete,
            "storage": self.storage.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Building:
        return cls(
            str(data["id"]),
            str(data["kind"]),
            Coord(*data["origin"]),
            Ownership.from_dict(data["ownership"]),
            {str(item): int(qty) for item, qty in data["delivered"].items()},
            float(data["work_done"]),
            bool(data["complete"]),
            Inventory.from_dict(data["storage"]),
        )


def footprint(origin: Coord, size: tuple[int, int]) -> list[Coord]:
    width, height = size
    return [Coord(origin.x + dx, origin.y + dy) for dy in range(height) for dx in range(width)]


def building_tiles(building: Building, registry: Registry) -> list[Coord]:
    return footprint(building.origin, registry.buildings[building.kind].footprint)


def near(pos: Coord, tiles: Iterable[Coord]) -> bool:
    return any(pos.manhattan(tile) <= 1 for tile in tiles)


def remaining_cost(building: Building, registry: Registry) -> dict[str, int]:
    cost = registry.buildings[building.kind].cost
    return {
        item: qty - building.delivered.get(item, 0)
        for item, qty in sorted(cost.items())
        if qty > building.delivered.get(item, 0)
    }


def housing_capacity(registry: Registry, building: Building) -> int:
    return registry.buildings[building.kind].housing if building.complete else 0


def storage_capacity(registry: Registry, building: Building) -> int:
    return registry.buildings[building.kind].storage if building.complete else 0
```

- [ ] **Step 6: Replace `src/pericles/core/state.py`**

```python
"""The complete, serialisable world state (ADR-0013, ADR-0014)."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pericles.core.buildings import Building
from pericles.core.canonical import digest
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import Modifier
from pericles.core.nodes import Node


@dataclass
class Activity:
    """Work in progress: an action, recipe, research or construction (ADR-0014)."""

    kind: str
    ident: str
    target: str | None
    work: float
    done: float
    speed: float
    reserved: Inventory = field(default_factory=Inventory)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ident": self.ident,
            "target": self.target,
            "work": self.work,
            "done": self.done,
            "speed": self.speed,
            "reserved": self.reserved.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Activity:
        target = data["target"]
        return cls(
            str(data["kind"]),
            str(data["ident"]),
            None if target is None else str(target),
            float(data["work"]),
            float(data["done"]),
            float(data["speed"]),
            Inventory.from_dict(data["reserved"]),
        )


@dataclass
class Villager:
    id: str
    name: str
    pos: Coord
    path: list[Coord] = field(default_factory=list)
    move_progress: float = 0.0
    inventory: Inventory = field(default_factory=Inventory)
    skills: dict[str, float] = field(default_factory=dict)
    knowledge: set[str] = field(default_factory=set)
    traits: tuple[str, ...] = ()
    activity: Activity | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "pos": list(self.pos),
            "path": [list(c) for c in self.path],
            "move_progress": self.move_progress,
            "inventory": self.inventory.to_dict(),
            "skills": dict(sorted(self.skills.items())),
            "knowledge": sorted(self.knowledge),
            "traits": list(self.traits),
            "activity": None if self.activity is None else self.activity.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Villager:
        activity = data["activity"]
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            pos=Coord(*data["pos"]),
            path=[Coord(*c) for c in data["path"]],
            move_progress=float(data["move_progress"]),
            inventory=Inventory.from_dict(data["inventory"]),
            skills={str(k): float(v) for k, v in data["skills"].items()},
            knowledge={str(k) for k in data["knowledge"]},
            traits=tuple(str(t) for t in data["traits"]),
            activity=None if activity is None else Activity.from_dict(activity),
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
    nodes: dict[str, Node] = field(default_factory=dict)
    buildings: dict[str, Building] = field(default_factory=dict)
    village_knowledge: set[str] = field(default_factory=set)
    next_building: int = 0

    @classmethod
    def new(
        cls,
        seed: int,
        tilemap: TileMap,
        villagers: Iterable[Villager] = (),
        nodes: Iterable[Node] = (),
    ) -> WorldState:
        by_id: dict[str, Villager] = {}
        for villager in sorted(villagers, key=lambda v: v.id):
            if villager.id in by_id:
                raise ValueError(f"duplicate villager id {villager.id!r}")
            by_id[villager.id] = villager
        nodes_by_id: dict[str, Node] = {}
        for node in nodes:
            if node.id in nodes_by_id:
                raise ValueError(f"duplicate node id {node.id!r}")
            nodes_by_id[node.id] = node
        return cls(
            seed=seed,
            tick=0,
            tilemap=tilemap,
            villagers=by_id,
            modifiers=(),
            rng=random.Random(f"pericles-world-{seed}"),
            nodes=nodes_by_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "tick": self.tick,
            "tilemap": self.tilemap.to_dict(),
            "villagers": [self.villagers[k].to_dict() for k in sorted(self.villagers)],
            "modifiers": [m.to_dict() for m in self.modifiers],
            "rng": _rng_to_json(self.rng),
            "nodes": [self.nodes[k].to_dict() for k in sorted(self.nodes)],
            "buildings": [self.buildings[k].to_dict() for k in sorted(self.buildings)],
            "village_knowledge": sorted(self.village_knowledge),
            "next_building": self.next_building,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorldState:
        villagers = [Villager.from_dict(v) for v in data["villagers"]]
        nodes = [Node.from_dict(n) for n in data["nodes"]]
        buildings = [Building.from_dict(b) for b in data["buildings"]]
        return cls(
            seed=int(data["seed"]),
            tick=int(data["tick"]),
            tilemap=TileMap.from_dict(data["tilemap"]),
            villagers={v.id: v for v in villagers},
            modifiers=tuple(Modifier.from_dict(m) for m in data["modifiers"]),
            rng=_rng_from_json(data["rng"]),
            nodes={n.id: n for n in nodes},
            buildings={b.id: b for b in buildings},
            village_knowledge={str(k) for k in data["village_knowledge"]},
            next_building=int(data["next_building"]),
        )

    def digest(self) -> str:
        return digest(self.to_dict())
```

- [ ] **Step 7: Run the tests, gates, mutation, commit**

Run: `uv run pytest tests/pericles -q`
Expected: all pass. That includes every M1a test (engine, runner, state); none of them depend on the new fields.

Run the gates. Then: `rm -rf mutants && uv run mutmut run "pericles.core.nodes.*" "pericles.core.buildings.*" "pericles.core.state.*" ; uv run mutmut results --all true`
Kill the survivors, then `rm -rf mutants`.

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): resource nodes, buildings, ownership and gameplay state"
```

---

### Task 3: Actions: context, work activities, harvesting, skills, tools, interruption, regrowth

**Files:**
- Create: `src/pericles/core/context.py`, `src/pericles/core/work.py`
- Modify: `src/pericles/core/intents.py`, `src/pericles/core/engine.py`
- Test: `tests/pericles/test_work_actions.py`, `tests/pericles/test_engine.py` (one new test)

**Interfaces:**
- Consumes:
  - Tasks 1–2: `EngineConfig`, `Calendar.season_at`, `Inventory`, `Tool`, `transfer`, `bundle_weight`, `capacity_for`, `fits`, `Node`, `regrow`, `Building`, `building_tiles`, `near`, `Activity`, the `Villager` and `WorldState` fields, and the fixtures `econ` and `make_world`.
  - M1a: `Modifier`, `Target`, `Scope`, `Op`, `resolve`, `EventSink`, `Intent`.
- Produces:
  - `context.Context(registry, config, locked: frozenset[str])`, frozen; `Context.build(registry, config)`; `Context.available(state, villager, ident) -> bool`
  - `context.knows(state, villager, ident) -> bool`; `context.reject(sink, intent, reason) -> None` (emits `intent_rejected` with `actor`, `intent` = the intent kind, and `reason`)
  - `intents.StartAction(actor, action: str, target: str | None = None)`, kind `"start_action"`
  - In `work`:
    - `EPSILON = 1e-9`
    - `used_tools(ctx, villager, kind, ident, tags, required) -> list[Tool] | None`
    - `work_speed(ctx, state, villager, *, kind, ident, tags, skill, tools, attribute="work_speed", building=None) -> float`
    - `start_work(ctx, villager, intent, sink, *, kind, ident, target, work, speed, inputs, done=0.0) -> None` (rejects with `cannot_work` when speed ≤ 0)
    - `interrupt(ctx, villager, sink, cause, reason=None) -> None`
    - `start_action(ctx, state, intent, sink)`, `complete(ctx, state, villager, sink)`
    - `finish(ctx, villager, activity, sink, *, created, skill, tool_kind, tool_ident, tags, required) -> None`
    - `_FINISHERS: dict[str, Finisher]`, where `Finisher = Callable[[Context, WorldState, Villager, Activity, EventSink], None]`
  - `engine.Engine(registry, config: EngineConfig | None = None)` with attributes `config` and `context`, method `interrupt(state, villager_id, sink, cause="intervened")`, and per-tick work progress and daily regrowth.
  - **Events:**
    - `work_started {actor, work, ident, target, ticks}`
    - `work_done {actor, work, ident, target, created, destroyed}`
    - `work_interrupted {actor, work, ident, target, cause, reason}`
    - `tool_broken {actor, item, destroyed}`
    - `stopped` (existing), emitted when work starts while the villager is moving
  - **Rejection reasons for `start_action`:** `unknown_action`, `season`, `missing_knowledge`, `skill_too_low`, `missing_tool`, `missing_inputs`, `bad_target`, `incomplete`, `not_at_location`, `depleted`, `carry_limit`, `cannot_work`.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_work_actions.py`:

```python
from collections.abc import Callable, Sequence

import pytest

from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo, StartAction
from pericles.core.inventory import Tool
from pericles.core.modifiers import Modifier, Op, Target
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

MakeWorld = Callable[..., WorldState]
Setup = Callable[[WorldState, Registry], None]
ROWS = ("..T.T", ".....")


def world(make_world: MakeWorld, **fields: object) -> WorldState:
    """Ana at (1,0); tree n0 adjacent, bush n1 adjacent, tree n2 far; workshops b0 (near), b1 (site), b2 (far)."""
    nodes = [
        Node("n0", "tree", Coord(2, 0), 6),
        Node("n1", "bush", Coord(1, 1), 4),
        Node("n2", "tree", Coord(4, 0), 6),
    ]
    state = make_world(ROWS, [Villager("a", "Ana", Coord(1, 0), **fields)], nodes)  # type: ignore[arg-type]
    communal = Ownership("communal")
    state.buildings = {
        "b0": Building("b0", "workshop", Coord(0, 0), communal, complete=True),
        "b1": Building("b1", "workshop", Coord(3, 1), communal),
        "b2": Building("b2", "workshop", Coord(4, 1), communal, complete=True),
    }
    state.next_building = 3
    return state


def run(engine: Engine, state: WorldState, intents: Sequence[Intent], ticks: int) -> list[Event]:
    events = list(engine.step(state, intents)[1])
    for _ in range(ticks - 1):
        events += engine.step(state, [])[1]
    return events


def of(events: list[Event], kind: str) -> list[dict[str, object]]:
    return [dict(event.data) for event in events if event.kind == kind]


def nothing(state: WorldState, registry: Registry) -> None:
    pass


def give(*bundle: tuple[str, int]) -> Setup:
    def setup(state: WorldState, registry: Registry) -> None:
        for item, qty in bundle:
            state.villagers["a"].inventory.add(registry, item, qty)

    return setup


def skill(level: float) -> Setup:
    def setup(state: WorldState, registry: Registry) -> None:
        state.villagers["a"].skills["carving"] = level

    return setup


def deplete(state: WorldState, registry: Registry) -> None:
    state.nodes["n0"].stock = 0


def onto_forest(state: WorldState, registry: Registry) -> None:
    give(("seed", 1))(state, registry)
    state.villagers["a"].pos = Coord(2, 0)


def stall_picking(state: WorldState, registry: Registry) -> None:
    state.modifiers = (Modifier(Target("action", "pick"), "work_speed", Op.MUL, 0.0, "test"),)


def learned_personally(state: WorldState, registry: Registry) -> None:
    state.villagers["a"].knowledge.add("secret_art")


def learned_by_village(state: WorldState, registry: Registry) -> None:
    state.village_knowledge.add("secret_art")


REJECTIONS = [
    ("dance", None, nothing, "unknown_action"),
    ("secret_art", None, nothing, "missing_knowledge"),
    ("carve", None, skill(4.9), "skill_too_low"),
    ("whittle", None, give(("wood", 1)), "missing_tool"),
    ("whittle", None, give(("hammer", 1)), "missing_inputs"),
    ("chop", None, nothing, "bad_target"),
    ("chop", "n9", nothing, "bad_target"),
    ("chop", "n1", nothing, "bad_target"),
    ("chop", "n2", nothing, "not_at_location"),
    ("chop", "n0", deplete, "depleted"),
    ("sow", None, onto_forest, "not_at_location"),
    ("chop", "n0", give(("wood", 15)), "carry_limit"),
    ("pick", "n1", stall_picking, "cannot_work"),
    ("tinker", None, nothing, "bad_target"),
    ("tinker", "n0", nothing, "bad_target"),
    ("tinker", "b1", nothing, "incomplete"),
    ("tinker", "b2", nothing, "not_at_location"),
]


@pytest.mark.req("REQ-SIM-008")
@pytest.mark.parametrize(("action", "target", "setup", "reason"), REJECTIONS)
def test_rejections_name_the_missing_requirement(
    econ: Registry,
    make_world: MakeWorld,
    action: str,
    target: str | None,
    setup: Setup,
    reason: str,
) -> None:
    """AC2: a missing tool, skill, knowledge, input or location rejects with a specific reason."""
    state = world(make_world)
    setup(state, econ)
    before = state.villagers["a"].inventory.to_dict()
    events = Engine(econ).step(state, [StartAction("a", action, target)])[1]
    assert of(events, "intent_rejected") == [
        {"actor": "a", "intent": "start_action", "reason": reason}
    ]
    assert [event.kind for event in events] == ["intent_rejected"]
    assert state.villagers["a"].activity is None
    assert state.villagers["a"].inventory.to_dict() == before


@pytest.mark.req("REQ-SIM-008")
@pytest.mark.parametrize(
    ("action", "target", "setup"),
    [
        ("carve", None, skill(5.0)),
        ("secret_art", None, learned_personally),
        ("secret_art", None, learned_by_village),
        ("whittle", None, give(("hammer", 1), ("wood", 1))),
        ("nail", None, give(("hammer", 1))),
        ("sow", None, give(("seed", 1))),
        ("tinker", "b0", nothing),
        ("chop", "n0", give(("wood", 14))),
    ],
)
def test_met_requirements_start_the_action(
    econ: Registry, make_world: MakeWorld, action: str, target: str | None, setup: Setup
) -> None:
    """AC2: each requirement that is met lets the action start."""
    state = world(make_world)
    setup(state, econ)
    events = Engine(econ).step(state, [StartAction("a", action, target)])[1]
    assert [event.kind for event in events] == ["work_started"]
    activity = state.villagers["a"].activity
    assert activity is not None
    assert (activity.kind, activity.ident, activity.target) == ("action", action, target)


@pytest.mark.req("REQ-SIM-008")
@pytest.mark.req("REQ-SIM-007")
def test_outputs_arrive_only_on_completion(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: chop takes its 10-tick duration and yields wood only when it completes."""
    engine, state = Engine(econ), world(make_world)
    events = run(engine, state, [StartAction("a", "chop", "n0")], 9)
    assert of(events, "work_started") == [
        {"actor": "a", "work": "action", "ident": "chop", "target": "n0", "ticks": 10}
    ]
    villager = state.villagers["a"]
    assert villager.inventory.count("wood") == 0
    assert villager.activity is not None
    assert villager.activity.done == 9.0
    events = engine.step(state, [])[1]
    assert of(events, "work_done") == [
        {
            "actor": "a",
            "work": "action",
            "ident": "chop",
            "target": "n0",
            "created": {"wood": 2},
            "destroyed": {},
        }
    ]
    assert villager.inventory.count("wood") == 2
    assert state.nodes["n0"].stock == 4
    assert villager.activity is None


@pytest.mark.req("REQ-SIM-008")
@pytest.mark.req("REQ-SIM-010")
@pytest.mark.parametrize(
    ("traits", "axe", "ticks"),
    [((), False, 10), (("strong",), False, 5), (("strong",), True, 3)],
)
def test_modifiers_scale_the_duration(
    econ: Registry, make_world: MakeWorld, traits: tuple[str, ...], axe: bool, ticks: int
) -> None:
    """AC1 (SIM-008) / AC2 (SIM-010): traits and held tools divide the duration by the work speed."""
    state = world(make_world, traits=traits)
    if axe:
        state.villagers["a"].inventory.add_tools([Tool("axe", 3)])
    events = Engine(econ).step(state, [StartAction("a", "chop", "n0")])[1]
    assert of(events, "work_started")[0]["ticks"] == ticks


@pytest.mark.req("REQ-SIM-003")
def test_winter_rejects_sowing(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: in winter, sowing actions are rejected."""
    winter = Calendar(seasons=(Season("winter", 1, blocked_tags=("sowing",)),))
    state = world(make_world)
    state.villagers["a"].inventory.add(econ, "seed", 1)
    events = Engine(econ, EngineConfig(calendar=winter)).step(state, [StartAction("a", "sow")])[1]
    assert of(events, "intent_rejected") == [
        {"actor": "a", "intent": "start_action", "reason": "season"}
    ]
    assert state.villagers["a"].inventory.count("seed") == 1


@pytest.mark.req("REQ-SIM-007")
def test_harvest_never_overdraws_and_then_rejects(econ: Registry, make_world: MakeWorld) -> None:
    """AC1/AC3: a harvest takes at most the stock; a depleted node rejects with `depleted`."""
    engine, state = Engine(econ), world(make_world)
    state.nodes["n0"].stock = 1
    events = run(engine, state, [StartAction("a", "chop", "n0")], 10)
    assert of(events, "work_done")[0]["created"] == {"wood": 1}
    assert state.nodes["n0"].stock == 0
    events = engine.step(state, [StartAction("a", "chop", "n0")])[1]
    assert of(events, "intent_rejected")[0]["reason"] == "depleted"


@pytest.mark.req("REQ-SIM-007")
def test_two_harvesters_share_the_last_unit(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: when both finish on one tick, the second finds the node empty and is interrupted."""
    villagers = [Villager("a", "Ana", Coord(1, 0)), Villager("b", "Bo", Coord(3, 0))]
    state = make_world(ROWS, villagers, [Node("n0", "tree", Coord(2, 0), 1)])
    intents = [StartAction("a", "chop", "n0"), StartAction("b", "chop", "n0")]
    events = run(Engine(econ), state, intents, 10)
    assert [(d["actor"], d["created"]) for d in of(events, "work_done")] == [("a", {"wood": 1})]
    assert of(events, "work_interrupted") == [
        {
            "actor": "b",
            "work": "action",
            "ident": "chop",
            "target": "n0",
            "cause": "engine",
            "reason": "depleted",
        }
    ]
    assert state.nodes["n0"].stock == 0
    assert state.villagers["b"].inventory.count("wood") == 0


@pytest.mark.req("REQ-SIM-013")
def test_harvest_is_capped_by_the_carry_limit(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: a harvest that would exceed the carry limit is capped; the node keeps the rest."""
    state = world(make_world)
    state.villagers["a"].inventory.add(econ, "wood", 14)
    events = run(Engine(econ), state, [StartAction("a", "chop", "n0")], 10)
    assert of(events, "work_done")[0]["created"] == {"wood": 1}
    assert state.villagers["a"].inventory.weight(econ) == 30.0
    assert state.nodes["n0"].stock == 5


@pytest.mark.req("REQ-SIM-013")
def test_the_node_yield_is_filled_before_other_outputs(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: when capped, the node's yield is taken first and other outputs get what still fits."""
    state = world(make_world)
    state.villagers["a"].inventory.add(econ, "wood", 14)  # 2.0 of 30.0 left
    events = run(Engine(econ), state, [StartAction("a", "log", "n0")], 2)
    assert of(events, "work_done")[0]["created"] == {"wood": 1}
    assert state.nodes["n0"].stock == 5


@pytest.mark.req("REQ-SIM-008")
def test_inputs_are_reserved_then_consumed(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: inputs leave the inventory when work starts and are consumed when it completes."""
    engine, state = Engine(econ), world(make_world)
    give(("hammer", 1), ("wood", 1))(state, econ)
    engine.step(state, [StartAction("a", "whittle")])
    villager = state.villagers["a"]
    assert villager.inventory.count("wood") == 0
    assert villager.activity is not None
    assert villager.activity.reserved.items == {"wood": 1}
    events = run(engine, state, [], 5)
    assert of(events, "work_done")[0]["created"] == {"plank": 2}
    assert of(events, "work_done")[0]["destroyed"] == {"wood": 1}
    assert villager.inventory.items == {"plank": 2}


@pytest.mark.req("REQ-SIM-008")
def test_a_new_intent_interrupts_and_returns_inputs(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: an interrupted action produces no outputs and returns its unconsumed inputs."""
    engine, state = Engine(econ), world(make_world)
    give(("hammer", 1), ("wood", 1))(state, econ)
    run(engine, state, [StartAction("a", "whittle")], 5)
    events = engine.step(state, [MoveTo("a", Coord(0, 1))])[1]
    assert events[0].kind == "work_interrupted"
    assert dict(events[0].data) == {
        "actor": "a",
        "work": "action",
        "ident": "whittle",
        "target": None,
        "cause": "actor",
        "reason": None,
    }
    villager = state.villagers["a"]
    assert villager.activity is None
    assert villager.inventory.items == {"wood": 1}
    assert villager.inventory.count("plank") == 0


@pytest.mark.req("REQ-SIM-008")
def test_engine_interrupt_models_an_intervention(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: another villager's intervention interrupts through Engine.interrupt."""
    engine, state = Engine(econ), world(make_world)
    give(("hammer", 1), ("wood", 1))(state, econ)
    engine.step(state, [StartAction("a", "whittle")])
    sink = EventSink(state.tick)
    engine.interrupt(state, "a", sink)
    assert [d["cause"] for d in of(sink.events, "work_interrupted")] == ["intervened"]
    assert state.villagers["a"].inventory.items == {"wood": 1}
    idle = EventSink(state.tick)
    engine.interrupt(state, "a", idle)
    assert idle.events == []


def test_starting_work_stops_movement(econ: Registry, make_world: MakeWorld) -> None:
    """Starting work clears the path and the progress into the next tile."""
    villagers = [Villager("a", "Ana", Coord(0, 0))]
    state = make_world([".T", ".."], villagers, [Node("n1", "bush", Coord(0, 1), 4)])
    engine = Engine(econ)
    engine.step(state, [MoveTo("a", Coord(1, 0))])  # forest costs 2: progress 1, no step yet
    assert state.villagers["a"].move_progress == 1.0
    events = engine.step(state, [StartAction("a", "pick", "n1")])[1]
    assert [event.kind for event in events] == ["stopped", "work_started"]
    villager = state.villagers["a"]
    assert (villager.path, villager.move_progress, villager.pos) == ([], 0.0, Coord(0, 0))


@pytest.mark.req("REQ-SIM-014")
def test_practice_raises_the_skill_up_to_the_maximum(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC1: each completed action adds the practice rate to its skill, capped at the maximum."""
    engine = Engine(econ, EngineConfig(skill_practice=1.0, max_skill=1.5))
    state = world(make_world)
    run(engine, state, [StartAction("a", "chop", "n0")], 10)
    assert state.villagers["a"].skills == {"woodcutting": 1.0}
    run(engine, state, [StartAction("a", "chop", "n0")], 10)
    assert state.villagers["a"].skills == {"woodcutting": 1.5}
    run(engine, state, [StartAction("a", "pick", "n1")], 4)
    assert state.villagers["a"].skills == {"woodcutting": 1.5}


@pytest.mark.req("REQ-SIM-014")
def test_skill_level_speeds_up_matching_actions(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: the skill level adds skill_speed_per_level × level to matching actions only."""
    engine = Engine(econ, EngineConfig(skill_speed_per_level=0.01))
    state = world(make_world, skills={"woodcutting": 100.0})
    events = engine.step(state, [StartAction("a", "chop", "n0")])[1]
    assert of(events, "work_started")[0]["ticks"] == 5
    events = engine.step(state, [StartAction("a", "pick", "n1")])[1]
    assert of(events, "work_started")[0]["ticks"] == 4


@pytest.mark.req("REQ-SIM-010")
def test_tools_wear_per_use_and_break_at_zero(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: each use costs a used tool one durability; at 0 it is destroyed with an event."""
    engine, state = Engine(econ), world(make_world)
    give(("hammer", 1), ("wood", 2), ("axe", 1))(state, econ)
    inventory = state.villagers["a"].inventory
    run(engine, state, [StartAction("a", "whittle")], 6)
    assert inventory.tools == [Tool("axe", 3), Tool("hammer", 1)]
    events = run(engine, state, [StartAction("a", "whittle")], 6)
    assert of(events, "tool_broken") == [
        {"actor": "a", "item": "hammer", "destroyed": {"hammer": 1}}
    ]
    assert inventory.tools == [Tool("axe", 3)]
    run(engine, state, [StartAction("a", "chop", "n0")], 5)  # the axe doubles chop speed
    assert inventory.tools == [Tool("axe", 2)]


@pytest.mark.req("REQ-SIM-010")
def test_one_tool_meeting_two_required_tags_wears_once(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: a tool counts once per use even when it satisfies several required tags."""
    engine, state = Engine(econ), world(make_world)
    give(("hammer", 1))(state, econ)
    run(engine, state, [StartAction("a", "nail")], 2)
    assert state.villagers["a"].inventory.tools == [Tool("hammer", 1)]


@pytest.mark.req("REQ-SIM-007")
def test_nodes_regrow_at_the_end_of_each_day(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: regrowth is applied once per in-game day, on the day's last tick."""
    engine, state = Engine(econ), world(make_world)
    state.nodes["n0"].stock = 2
    per_day = engine.config.calendar.ticks_per_day
    run(engine, state, [], per_day - 1)
    assert state.nodes["n0"].stock == 2
    engine.step(state, [])
    assert (state.nodes["n0"].stock, state.nodes["n0"].regrow) == (3, 0.5)
```

Append to `tests/pericles/test_engine.py` (add `from pericles.core.config import EngineConfig` to the imports):

```python
def test_engine_uses_the_default_config(registry: Registry) -> None:
    engine = Engine(registry)
    assert engine.config == EngineConfig()
    assert engine.context.config is engine.config
    assert engine.context.registry is registry
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/pericles/test_work_actions.py tests/pericles/test_engine.py -q`
Expected: collection error `ImportError: cannot import name 'StartAction' from 'pericles.core.intents'`.

- [ ] **Step 3: Add `StartAction` to `src/pericles/core/intents.py`**

Append:

```python
@dataclass(frozen=True)
class StartAction(Intent):
    action: str
    target: str | None = None
    kind: ClassVar[str] = "start_action"
```

- [ ] **Step 4: Implement `src/pericles/core/context.py`**

```python
"""What every gameplay rule needs: content, parameters and locked content (ADR-0014)."""

from __future__ import annotations

from dataclasses import dataclass

from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.events import EventSink
from pericles.core.intents import Intent
from pericles.core.state import Villager, WorldState


@dataclass(frozen=True)
class Context:
    registry: Registry
    config: EngineConfig
    locked: frozenset[str]

    @classmethod
    def build(cls, registry: Registry, config: EngineConfig) -> Context:
        locked: set[str] = set()
        for tech in registry.technologies.values():
            locked.update(tech.unlocks_recipes)
            locked.update(tech.unlocks_buildings)
        return cls(registry, config, frozenset(locked))

    def available(self, state: WorldState, villager: Villager, ident: str) -> bool:
        """A recipe or building is available unless a technology unlocks it and it is unknown."""
        return ident not in self.locked or knows(state, villager, ident)


def knows(state: WorldState, villager: Villager, ident: str) -> bool:
    return ident in villager.knowledge or ident in state.village_knowledge


def reject(sink: EventSink, intent: Intent, reason: str) -> None:
    sink.emit("intent_rejected", actor=intent.actor, intent=intent.kind, reason=reason)
```

- [ ] **Step 5: Implement `src/pericles/core/work.py`**

```python
"""Work: actions, tools, skills and interruption (REQ-SIM-008, -010, -014; ADR-0014)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping

from pericles.core.buildings import building_tiles, near
from pericles.core.context import Context, knows, reject
from pericles.core.events import EventSink
from pericles.core.intents import Intent, StartAction
from pericles.core.inventory import Inventory, Tool, bundle_weight, capacity_for, transfer
from pericles.core.modifiers import Modifier, Op, Target, resolve
from pericles.core.state import Activity, Villager, WorldState

EPSILON = 1e-9

Finisher = Callable[[Context, WorldState, Villager, Activity, EventSink], None]


def used_tools(
    ctx: Context,
    villager: Villager,
    kind: str,
    ident: str,
    tags: Iterable[str],
    required: Iterable[str],
) -> list[Tool] | None:
    """The tool instances a piece of work uses, or None if a required tool is missing.

    One instance per required tag (the first, most worn, holder of that tag), plus the first
    instance of every other held tool item that has a modifier targeting the work.
    """
    registry = ctx.registry
    tag_tuple = tuple(tags)
    used: list[Tool] = []
    for tag in sorted(required):
        tool = next(
            (t for t in villager.inventory.tools if tag in registry.items[t.item].tags), None
        )
        if tool is None:
            return None
        if all(tool is not other for other in used):
            used.append(tool)
    seen = {tool.item for tool in used}
    for tool in villager.inventory.tools:
        if tool.item in seen:
            continue
        seen.add(tool.item)
        targets = (m.target for m in registry.items[tool.item].modifiers)
        if any(Target(t.kind, t.id, t.tag).matches(kind, ident, tag_tuple) for t in targets):
            used.append(tool)
    return used


def work_speed(
    ctx: Context,
    state: WorldState,
    villager: Villager,
    *,
    kind: str,
    ident: str,
    tags: Iterable[str],
    skill: str | None,
    tools: Iterable[Tool],
    attribute: str = "work_speed",
    building: str | None = None,
) -> float:
    """World, tool, trait and skill modifiers folded over a base speed of 1 (ADR-0014 §2)."""
    registry = ctx.registry
    modifiers = list(state.modifiers)
    for tool in tools:
        modifiers.extend(
            Modifier.from_def(m, f"item:{tool.item}") for m in registry.items[tool.item].modifiers
        )
    for trait in villager.traits:
        modifiers.extend(
            Modifier.from_def(m, f"trait:{trait}") for m in registry.traits[trait].modifiers
        )
    if skill is not None:
        bonus = villager.skills.get(skill, 0.0) * ctx.config.skill_speed_per_level
        modifiers.append(Modifier(Target(kind, ident), attribute, Op.ADD, bonus, f"skill:{skill}"))
    return resolve(
        modifiers,
        kind=kind,
        ident=ident,
        attribute=attribute,
        base=1.0,
        tick=state.tick,
        tags=tags,
        villager=villager.id,
        building=building,
    ).value


def start_work(
    ctx: Context,
    villager: Villager,
    intent: Intent,
    sink: EventSink,
    *,
    kind: str,
    ident: str,
    target: str | None,
    work: float,
    speed: float,
    inputs: Mapping[str, int],
    done: float = 0.0,
) -> None:
    """Reserve the inputs, stop any movement and start the activity."""
    if speed <= 0:
        return reject(sink, intent, "cannot_work")
    reserved = Inventory()
    for item, qty in sorted(inputs.items()):
        transfer(ctx.registry, villager.inventory, reserved, item, qty)
    if villager.path:
        villager.path = []
        villager.move_progress = 0.0
        sink.emit("stopped", actor=villager.id, at=list(villager.pos))
    villager.activity = Activity(kind, ident, target, float(work), done, speed, reserved)
    ticks = math.ceil((work - done - EPSILON) / speed)
    sink.emit("work_started", actor=villager.id, work=kind, ident=ident, target=target, ticks=ticks)


def interrupt(
    ctx: Context, villager: Villager, sink: EventSink, cause: str, reason: str | None = None
) -> None:
    """Stop the current work; reserved inputs return to the inventory (REQ-SIM-008 AC3)."""
    activity = villager.activity
    if activity is None:
        return
    for item, qty in sorted(activity.reserved.totals().items()):
        transfer(ctx.registry, activity.reserved, villager.inventory, item, qty)
    villager.activity = None
    sink.emit(
        "work_interrupted",
        actor=villager.id,
        work=activity.kind,
        ident=activity.ident,
        target=activity.target,
        cause=cause,
        reason=reason,
    )


def start_action(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, StartAction)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    action = registry.actions.get(intent.action)
    if action is None:
        return reject(sink, intent, "unknown_action")
    blocked = ctx.config.calendar.season_at(state.tick).blocked_tags
    if any(tag in blocked for tag in action.tags):
        return reject(sink, intent, "season")
    requires = action.requires
    if requires.knowledge and not knows(state, villager, action.id):
        return reject(sink, intent, "missing_knowledge")
    if requires.skill is not None and villager.skills.get(requires.skill, 0.0) < requires.min_skill:
        return reject(sink, intent, "skill_too_low")
    tools = used_tools(ctx, villager, "action", action.id, action.tags, requires.tools)
    if tools is None:
        return reject(sink, intent, "missing_tool")
    if not villager.inventory.has(action.inputs):
        return reject(sink, intent, "missing_inputs")
    location = action.location
    target: str | None = None
    building_id: str | None = None
    if location.node is not None:
        node = state.nodes.get(intent.target) if intent.target is not None else None
        if node is None or node.kind != location.node:
            return reject(sink, intent, "bad_target")
        if not near(villager.pos, [node.pos]):
            return reject(sink, intent, "not_at_location")
        if node.stock == 0:
            return reject(sink, intent, "depleted")
        target = node.id
    if location.building is not None:
        building = state.buildings.get(intent.target) if intent.target is not None else None
        if building is None or building.kind != location.building:
            return reject(sink, intent, "bad_target")
        if not building.complete:
            return reject(sink, intent, "incomplete")
        if not near(villager.pos, building_tiles(building, registry)):
            return reject(sink, intent, "not_at_location")
        target = building_id = building.id
    if location.terrains and state.tilemap.terrain_at(villager.pos) not in location.terrains:
        return reject(sink, intent, "not_at_location")
    freed = bundle_weight(registry, action.inputs)
    limit = ctx.config.carry_limit
    room = [capacity_for(registry, villager.inventory, item, limit, freed) for item in action.outputs]
    if room and not any(room):
        return reject(sink, intent, "carry_limit")
    speed = work_speed(
        ctx,
        state,
        villager,
        kind="action",
        ident=action.id,
        tags=action.tags,
        skill=action.skill,
        tools=tools,
        building=building_id,
    )
    return start_work(
        ctx,
        villager,
        intent,
        sink,
        kind="action",
        ident=action.id,
        target=target,
        work=action.duration_ticks,
        speed=speed,
        inputs=action.inputs,
    )


def finish(
    ctx: Context,
    villager: Villager,
    activity: Activity,
    sink: EventSink,
    *,
    created: Mapping[str, int],
    skill: str | None,
    tool_kind: str,
    tool_ident: str,
    tags: Iterable[str],
    required: Iterable[str],
) -> None:
    """Consume the reserved inputs, train the skill, wear the tools and report the result."""
    config = ctx.config
    destroyed = dict(sorted(activity.reserved.totals().items()))
    if skill is not None:
        villager.skills[skill] = min(
            config.max_skill, villager.skills.get(skill, 0.0) + config.skill_practice
        )
    tools = used_tools(ctx, villager, tool_kind, tool_ident, tags, required) or []
    villager.activity = None
    sink.emit(
        "work_done",
        actor=villager.id,
        work=activity.kind,
        ident=activity.ident,
        target=activity.target,
        created=dict(sorted(created.items())),
        destroyed=destroyed,
    )
    for tool in tools:
        tool.durability -= 1
        if tool.durability <= 0:
            villager.inventory.tools.remove(tool)
            sink.emit("tool_broken", actor=villager.id, item=tool.item, destroyed={tool.item: 1})


def _finish_action(
    ctx: Context, state: WorldState, villager: Villager, activity: Activity, sink: EventSink
) -> None:
    registry = ctx.registry
    action = registry.actions[activity.ident]
    node = None
    if action.location.node is not None:
        assert activity.target is not None
        node = state.nodes[activity.target]
        if node.stock == 0:
            interrupt(ctx, villager, sink, cause="engine", reason="depleted")
            return
    yields = None if node is None else registry.nodes[node.kind].yields
    created: dict[str, int] = {}
    for item in sorted(action.outputs, key=lambda name: (name != yields, name)):
        qty = action.outputs[item]
        if node is not None and item == yields:
            qty = min(qty, node.stock)
        qty = min(qty, capacity_for(registry, villager.inventory, item, ctx.config.carry_limit))
        if qty > 0:
            villager.inventory.add(registry, item, qty)
            created[item] = qty
            if node is not None and item == yields:
                node.stock -= qty
    finish(
        ctx,
        villager,
        activity,
        sink,
        created=created,
        skill=action.skill,
        tool_kind="action",
        tool_ident=action.id,
        tags=action.tags,
        required=action.requires.tools,
    )


_FINISHERS: dict[str, Finisher] = {"action": _finish_action}


def complete(ctx: Context, state: WorldState, villager: Villager, sink: EventSink) -> None:
    activity = villager.activity
    assert activity is not None
    _FINISHERS[activity.kind](ctx, state, villager, activity, sink)
```

- [ ] **Step 6: Replace `src/pericles/core/engine.py`**

```python
"""The deterministic tick loop (REQ-SIM-002, ADR-0001, ADR-0013, ADR-0014)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial

from pericles.core import work
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.events import Event, EventSink
from pericles.core.intents import Intent, MoveTo, StartAction, Wait
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import expire
from pericles.core.nodes import regrow
from pericles.core.pathfinding import TerrainCostField, find_path
from pericles.core.state import WorldState

Handler = Callable[[WorldState, Intent, EventSink], None]


class Engine:
    def __init__(self, registry: Registry, config: EngineConfig | None = None) -> None:
        self.registry = registry
        self.config = config if config is not None else EngineConfig()
        self.context = Context.build(registry, self.config)
        self._handlers: dict[type[Intent], Handler] = {
            MoveTo: self._move_to,
            Wait: self._wait,
            StartAction: partial(work.start_action, self.context),
        }
        self._field_map: TileMap | None = (
            None  # pragma: no mutate - cache sentinel; any non-matching value just forces a rebuild
        )
        self._field: TerrainCostField | None = (
            None  # pragma: no mutate - cache sentinel; any non-None value just forces a rebuild
        )

    def register(self, intent_type: type[Intent], handler: Handler) -> None:
        self._handlers[intent_type] = handler

    def interrupt(
        self, state: WorldState, villager_id: str, sink: EventSink, cause: str = "intervened"
    ) -> None:
        """Interrupt a villager's work on behalf of someone else (REQ-SIM-008 AC3)."""
        work.interrupt(self.context, state.villagers[villager_id], sink, cause=cause)

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
            work.interrupt(self.context, state.villagers[intent.actor], sink, cause="actor")
            self._handlers[type(intent)](state, intent, sink)
        self._advance_work(state, sink)
        self._advance_movement(state, sink)
        if (state.tick + 1) % self.config.calendar.ticks_per_day == 0:
            regrow(state.nodes.values(), self.registry)
        state.modifiers = expire(state.modifiers, state.tick + 1)
        state.tick += 1
        return state, sink.events

    def _advance_work(self, state: WorldState, sink: EventSink) -> None:
        for vid in sorted(state.villagers):
            villager = state.villagers[vid]
            activity = villager.activity
            if activity is None:
                continue
            activity.done += activity.speed
            if activity.done >= activity.work - work.EPSILON:
                work.complete(self.context, state, villager, sink)

    def _cost_field(self, state: WorldState) -> TerrainCostField:
        if self._field is None or self._field_map is not state.tilemap:
            self._field = TerrainCostField(state.tilemap, self.registry)
            self._field_map = state.tilemap
        return self._field

    # _move_to, _wait and _advance_movement stay exactly as they are in M1a.
```

Copy `_move_to`, `_wait` and `_advance_movement` unchanged from the current file, below `_cost_field`.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass, including every M1a engine and runner test. A villager with no activity is unaffected by `work.interrupt` and `_advance_work`.

- [ ] **Step 8: Gates, mutation, commit**

Run the gates. Then: `rm -rf mutants && uv run mutmut run "pericles.core.work.*" "pericles.core.context.*" "pericles.core.engine.*" ; uv run mutmut results --all true`
Kill every non-equivalent survivor with a test, then `rm -rf mutants`. Two mutants are expected to be equivalent:
- `tool.durability <= 0` → `tool.durability == 0`, because durability never goes below 0;
- `or []` in `finish`, because `used_tools` can only return None if a required tool is missing, and a working villager's inventory cannot change.

Report them; do not add a pragma unless every mutant on the line is equivalent.

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): timed actions with harvesting, skills, tool wear, interruption and regrowth"
```

---

### Task 4: Construction: sites, delivery, building work, walls, stores and ownership

**Files:**
- Create: `src/pericles/core/construction.py`
- Modify: `src/pericles/core/intents.py`, `src/pericles/core/engine.py`
- Test: `tests/pericles/test_construction.py`

**Interfaces:**
- Consumes:
  - Task 2: `Building`, `Ownership`, `footprint`, `building_tiles`, `near`, `remaining_cost`, `storage_capacity`.
  - Task 3: `Context`, `reject`, `work.EPSILON`, `work.start_work`, `work.used_tools`, `work.work_speed`, and the `Engine` from Task 3.
  - M1a: `TerrainCostField(tilemap, registry, blocked: Callable[[Coord], bool] | None)`, `TileMap.in_bounds`.
- Produces:
  - Intents:
    - `PlaceBuilding(actor, building: str, origin: Coord, ownership: str = "personal", co_owners: tuple[str, ...] = ())`, kind `"place_building"`
    - `Deliver(actor, building: str, item: str, qty: int)`, kind `"deliver"`
    - `Construct(actor, building: str)`, kind `"construct"`
    - `Deposit(actor, building: str, item: str, qty: int)`, kind `"deposit"`
    - `Take(actor, building: str, item: str, qty: int)`, kind `"take"`
  - Functions in `construction`: `blocked_tiles(ctx, state) -> frozenset[Coord]`; `place_building`, `deliver`, `construct`, `deposit`, `take` (all handlers taking `(ctx, state, intent, sink)`); `progress(ctx, state, villager, sink)`.
  - Engine changes:
    - Registers the five handlers.
    - Construction activities advance through `construction.progress`.
    - The cost-field cache is keyed on `(state.tilemap identity, blocked_tiles)`.
  - **Events:**
    - `site_placed {actor, building, kind, origin, ownership}`
    - `delivered {actor, building, item, qty}`
    - `building_completed {building, kind, destroyed}`, followed by one `work_done` (empty bundles) per villager who was constructing it, in id order
    - `item_deposited {actor, building, item, qty}`
    - `item_taken {actor, building, item, qty, ownership}`
    - `take_unowned {actor, store, item, qty, owners}`
  - **Rejection reasons:**
    - Placement: `unknown_building`, `locked`, `bad_ownership`, `out_of_bounds`, `bad_terrain`, `occupied`, `not_at_location`.
    - Delivery: `unknown_building`, `already_complete`, `not_at_location`, `bad_quantity`, `not_needed`, `missing_items`.
    - Construction: `unknown_building`, `already_complete`, `not_at_location`, `missing_materials`, `cannot_work`.
    - Stores: `unknown_building`, `no_storage`, `not_at_location`, `bad_quantity`, `missing_items`, `store_full`, `carry_limit`.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_construction.py`:

```python
from collections.abc import Callable, Sequence

import pytest

from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import (
    Construct,
    Deliver,
    Deposit,
    Intent,
    MoveTo,
    PlaceBuilding,
    Take,
)
from pericles.core.inventory import Tool
from pericles.core.modifiers import Modifier, Op, Target
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

MakeWorld = Callable[..., WorldState]
ROWS = ("......", "......", "..~...")
PERSONAL_A = Ownership("personal", ("a",))


def world(make_world: MakeWorld) -> WorldState:
    """Ana (1,0) and Bo (4,0) flank the hut plot (2,0)-(3,0); Cy (1,2) is far; a bush at (5,2)."""
    villagers = [
        Villager("a", "Ana", Coord(1, 0)),
        Villager("b", "Bo", Coord(4, 0)),
        Villager("c", "Cy", Coord(1, 2)),
    ]
    return make_world(ROWS, villagers, [Node("n0", "bush", Coord(5, 2), 4)])


def with_hut(
    state: WorldState, ownership: Ownership = PERSONAL_A, complete: bool = False
) -> Building:
    hut = Building("b0", "hut", Coord(2, 0), ownership, complete=complete)
    state.buildings["b0"] = hut
    state.next_building = 1
    return hut


def run(engine: Engine, state: WorldState, intents: Sequence[Intent], ticks: int) -> list[Event]:
    events = list(engine.step(state, intents)[1])
    for _ in range(ticks - 1):
        events += engine.step(state, [])[1]
    return events


def of(events: list[Event], kind: str) -> list[dict[str, object]]:
    return [dict(event.data) for event in events if event.kind == kind]


def reasons(events: list[Event]) -> list[object]:
    return [d["reason"] for d in of(events, "intent_rejected")]


# --- placement -----------------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.req("REQ-ECO-001")
def test_placing_a_site(econ: Registry, make_world: MakeWorld) -> None:
    """AC1 (SIM-009): a site on valid terrain with a free footprint is placed with its ownership."""
    state = world(make_world)
    events = Engine(econ).step(state, [PlaceBuilding("a", "hut", Coord(2, 0))])[1]
    assert of(events, "site_placed") == [
        {
            "actor": "a",
            "building": "b0",
            "kind": "hut",
            "origin": [2, 0],
            "ownership": {"kind": "personal", "owners": ["a"]},
        }
    ]
    assert state.buildings == {"b0": Building("b0", "hut", Coord(2, 0), PERSONAL_A)}
    assert state.next_building == 1


@pytest.mark.req("REQ-ECO-001")
@pytest.mark.parametrize(
    ("ownership", "co_owners", "expected"),
    [
        ("personal", (), Ownership("personal", ("a",))),
        ("shared", ("c",), Ownership("shared", ("a", "c"))),
        ("communal", (), Ownership("communal")),
    ],
)
def test_sites_carry_the_requested_ownership(
    econ: Registry,
    make_world: MakeWorld,
    ownership: str,
    co_owners: tuple[str, ...],
    expected: Ownership,
) -> None:
    """AC1: a building is owned personally, shared among named owners, or communally."""
    state = world(make_world)
    Engine(econ).step(state, [PlaceBuilding("a", "hut", Coord(2, 0), ownership, co_owners)])
    assert state.buildings["b0"].ownership == expected


def test_building_ids_count_up(econ: Registry, make_world: MakeWorld) -> None:
    state = world(make_world)
    engine = Engine(econ)
    engine.step(state, [PlaceBuilding("a", "wall", Coord(1, 1))])
    engine.step(state, [PlaceBuilding("a", "wall", Coord(0, 0))])
    assert sorted(state.buildings) == ["b0", "b1"]
    assert state.next_building == 2


def place(building: str, x: int, y: int, ownership: str = "personal", *co: str) -> PlaceBuilding:
    return PlaceBuilding("a", building, Coord(x, y), ownership, co)


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.parametrize(
    ("intent", "existing_hut", "reason"),
    [
        (place("castle", 2, 0), False, "unknown_building"),
        (place("vault", 2, 0), False, "locked"),
        (place("hut", 2, 0, "private"), False, "bad_ownership"),
        (place("hut", 2, 0, "shared"), False, "bad_ownership"),
        (place("hut", 2, 0, "personal", "c"), False, "bad_ownership"),
        (place("hut", 2, 0, "communal", "c"), False, "bad_ownership"),
        (place("hut", 2, 0, "shared", "zed"), False, "bad_ownership"),
        (place("hut", 5, 0), False, "out_of_bounds"),
        (place("hut", -1, 0), False, "out_of_bounds"),
        (place("wall", 0, 3), False, "out_of_bounds"),
        (place("hut", 1, 2), False, "bad_terrain"),
        (place("wall", 3, 0), True, "occupied"),
        (place("hut", 4, 2), False, "occupied"),
        (place("wall", 4, 0), False, "occupied"),
        (place("hut", 3, 1), False, "not_at_location"),
    ],
)
def test_invalid_placements_are_rejected(
    econ: Registry,
    make_world: MakeWorld,
    intent: PlaceBuilding,
    existing_hut: bool,
    reason: str,
) -> None:
    """AC1: placement needs a known, unlocked kind, valid ownership and terrain, and a free footprint."""
    state = world(make_world)
    if existing_hut:
        with_hut(state)
    before = dict(state.buildings)
    events = Engine(econ).step(state, [intent])[1]
    assert reasons(events) == [reason]
    assert state.buildings == before


@pytest.mark.req("REQ-SIM-009")
def test_a_building_with_an_entrance_may_cover_a_villager(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC1: only footprints without an entrance must be free of villagers."""
    state = world(make_world)
    events = Engine(econ).step(state, [place("hut", 1, 0)])[1]
    assert [event.kind for event in events] == ["site_placed"]


@pytest.mark.req("REQ-SIM-011")
def test_a_known_technology_unlocks_a_building(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: a building unlocked by a technology can be placed once it is known."""
    state = world(make_world)
    state.villagers["a"].knowledge.add("vault")
    events = Engine(econ).step(state, [place("vault", 2, 0)])[1]
    assert [event.kind for event in events] == ["site_placed"]


# --- walls and walking ---------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-004")
def test_a_wall_is_not_walkable(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: a building without an entrance blocks paths as soon as its site is placed."""
    villagers = [Villager("a", "Ana", Coord(3, 0)), Villager("b", "Bo", Coord(0, 0))]
    state = make_world(["....."], villagers)
    engine = Engine(econ)
    engine.step(state, [PlaceBuilding("a", "wall", Coord(2, 0))])
    events = engine.step(state, [MoveTo("b", Coord(4, 0))])[1]
    assert of(events, "move_failed") == [{"actor": "b", "target": [4, 0], "reason": "no_path"}]


@pytest.mark.req("REQ-SIM-004")
def test_a_new_wall_cuts_a_path_in_progress(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: a villager whose next tile becomes a wall stops with `blocked`."""
    villagers = [Villager("a", "Ana", Coord(3, 0)), Villager("b", "Bo", Coord(0, 0))]
    state = make_world(["....."], villagers)
    engine = Engine(econ)
    engine.step(state, [MoveTo("b", Coord(4, 0))])
    assert state.villagers["b"].pos == Coord(1, 0)
    events = engine.step(state, [PlaceBuilding("a", "wall", Coord(2, 0))])[1]
    assert of(events, "move_failed") == [{"actor": "b", "target": [4, 0], "reason": "blocked"}]
    assert state.villagers["b"].pos == Coord(1, 0)


@pytest.mark.req("REQ-SIM-004")
def test_a_building_with_an_entrance_is_walkable(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: only buildings without an entrance block movement."""
    villagers = [Villager("a", "Ana", Coord(4, 0)), Villager("b", "Bo", Coord(0, 0))]
    state = make_world(["....."], villagers)
    engine = Engine(econ)
    engine.step(state, [PlaceBuilding("a", "hut", Coord(2, 0))])
    run(engine, state, [MoveTo("b", Coord(4, 0))], 4)
    assert state.villagers["b"].pos == Coord(4, 0)


# --- delivery and construction -------------------------------------------------------------


@pytest.mark.req("REQ-SIM-009")
def test_delivery_moves_materials_onto_the_site(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: delivered cost items are recorded on the site, from anyone near it."""
    state = world(make_world)
    hut = with_hut(state)
    state.villagers["a"].inventory.add(econ, "wood", 5)
    state.villagers["b"].inventory.add(econ, "wood", 1)
    engine = Engine(econ)
    events = engine.step(state, [Deliver("a", "b0", "wood", 3), Deliver("b", "b0", "wood", 1)])[1]
    assert sorted(of(events, "delivered"), key=lambda d: str(d["actor"])) == [
        {"actor": "a", "building": "b0", "item": "wood", "qty": 3},
        {"actor": "b", "building": "b0", "item": "wood", "qty": 1},
    ]
    assert hut.delivered == {"wood": 4}
    assert state.villagers["a"].inventory.items == {"wood": 2}
    assert reasons(engine.step(state, [Deliver("a", "b0", "wood", 1)])[1]) == ["not_needed"]


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.parametrize(
    ("intent", "complete", "reason"),
    [
        (Deliver("a", "b9", "wood", 1), False, "unknown_building"),
        (Deliver("a", "b0", "wood", 1), True, "already_complete"),
        (Deliver("c", "b0", "wood", 1), False, "not_at_location"),
        (Deliver("a", "b0", "wood", 0), False, "bad_quantity"),
        (Deliver("a", "b0", "wood", -1), False, "bad_quantity"),
        (Deliver("a", "b0", "berries", 1), False, "not_needed"),
        (Deliver("a", "b0", "dragon", 1), False, "not_needed"),
        (Deliver("a", "b0", "wood", 5), False, "not_needed"),
        (Deliver("a", "b0", "wood", 3), False, "missing_items"),
    ],
)
def test_invalid_deliveries_are_rejected(
    econ: Registry, make_world: MakeWorld, intent: Deliver, complete: bool, reason: str
) -> None:
    """AC2: only missing cost items, held and brought to the site, can be delivered."""
    state = world(make_world)
    with_hut(state, complete=complete)
    for vid in "ac":
        state.villagers[vid].inventory.add(econ, "wood", 2)
        state.villagers[vid].inventory.add(econ, "berries", 1)
    events = Engine(econ).step(state, [intent])[1]
    assert reasons(events) == [reason]
    assert state.buildings["b0"].delivered == {}


@pytest.mark.req("REQ-SIM-009")
def test_construction_completes_when_materials_and_work_are_done(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: two builders do the 20 units of build work in 10 ticks; the materials are consumed."""
    state = world(make_world)
    hut = with_hut(state)
    hut.delivered = {"wood": 4}
    engine = Engine(econ)
    run(engine, state, [Construct("a", "b0"), Construct("b", "b0")], 9)
    assert (hut.work_done, hut.complete) == (18.0, False)
    events = engine.step(state, [])[1]
    assert [event.kind for event in events] == ["building_completed", "work_done", "work_done"]
    assert dict(events[0].data) == {"building": "b0", "kind": "hut", "destroyed": {"wood": 4}}
    assert [(d["actor"], d["created"], d["destroyed"]) for d in of(events, "work_done")] == [
        ("a", {}, {}),
        ("b", {}, {}),
    ]
    assert (hut.complete, hut.work_done, hut.delivered) == (True, 20.0, {})
    assert state.villagers["a"].activity is None
    assert state.villagers["b"].activity is None


@pytest.mark.req("REQ-SIM-009")
def test_construction_cannot_start_before_every_material_arrives(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: build work needs every cost item delivered first."""
    state = world(make_world)
    with_hut(state).delivered = {"wood": 3}
    events = Engine(econ).step(state, [Construct("a", "b0")])[1]
    assert reasons(events) == ["missing_materials"]


@pytest.mark.req("REQ-SIM-009")
def test_interrupted_construction_keeps_its_progress(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: build work done so far stays on the site and resumes from there."""
    state = world(make_world)
    hut = with_hut(state)
    hut.delivered = {"wood": 4}
    engine = Engine(econ)
    run(engine, state, [Construct("a", "b0")], 3)
    events = engine.step(state, [MoveTo("a", Coord(1, 1))])[1]
    assert of(events, "work_interrupted")[0]["cause"] == "actor"
    assert hut.work_done == 3.0
    engine.step(state, [MoveTo("a", Coord(1, 0))])
    events = engine.step(state, [Construct("a", "b0")])[1]
    assert of(events, "work_started")[0]["ticks"] == 17
    assert hut.work_done == 4.0


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.parametrize(
    ("intent", "complete", "reason"),
    [
        (Construct("a", "b9"), False, "unknown_building"),
        (Construct("a", "b0"), True, "already_complete"),
        (Construct("c", "b0"), False, "not_at_location"),
    ],
)
def test_invalid_construction_is_rejected(
    econ: Registry, make_world: MakeWorld, intent: Construct, complete: bool, reason: str
) -> None:
    """AC2: construction needs a known, unfinished site within reach."""
    state = world(make_world)
    with_hut(state, complete=complete).delivered = {"wood": 4}
    assert reasons(Engine(econ).step(state, [intent])[1]) == [reason]


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.parametrize(("factor", "outcome"), [(4.0, 5), (0.0, "cannot_work")])
def test_build_speed_follows_modifiers(
    econ: Registry, make_world: MakeWorld, factor: float, outcome: object
) -> None:
    """AC2: build speed is `work_speed` on the building; a speed of 0 cannot start."""
    state = world(make_world)
    with_hut(state).delivered = {"wood": 4}
    state.modifiers = (Modifier(Target("building", "hut"), "work_speed", Op.MUL, factor, "test"),)
    events = Engine(econ).step(state, [Construct("a", "b0")])[1]
    if isinstance(outcome, int):
        assert of(events, "work_started")[0]["ticks"] == outcome
    else:
        assert reasons(events) == [outcome]


# --- stores and ownership ------------------------------------------------------------------


@pytest.mark.req("REQ-ECO-001")
@pytest.mark.parametrize(
    ("ownership", "taker", "unowned"),
    [
        (Ownership("personal", ("a",)), "a", False),
        (Ownership("personal", ("a",)), "b", True),
        (Ownership("shared", ("a", "b")), "b", False),
        (Ownership("shared", ("a", "b")), "c", True),
        (Ownership("communal"), "b", False),
    ],
)
def test_taking_from_a_store_reports_unowned_takes(
    econ: Registry, make_world: MakeWorld, ownership: Ownership, taker: str, unowned: bool
) -> None:
    """AC2: a take by someone who does not own the store also emits `take_unowned`."""
    state = world(make_world)
    state.villagers["c"].pos = Coord(2, 1)
    hut = with_hut(state, ownership, complete=True)
    hut.storage.add(econ, "wood", 3)
    events = Engine(econ).step(state, [Take(taker, "b0", "wood", 2)])[1]
    assert of(events, "item_taken") == [
        {"actor": taker, "building": "b0", "item": "wood", "qty": 2, "ownership": ownership.kind}
    ]
    expected = [
        {
            "actor": taker,
            "store": "b0",
            "item": "wood",
            "qty": 2,
            "owners": list(ownership.owners),
        }
    ]
    assert of(events, "take_unowned") == (expected if unowned else [])
    assert state.villagers[taker].inventory.items == {"wood": 2}
    assert hut.storage.items == {"wood": 1}


@pytest.mark.req("REQ-SIM-009")
def test_deposit_and_take_keep_tool_wear(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: a completed building provides storage; stored tools keep their durability."""
    state = world(make_world)
    hut = with_hut(state, complete=True)
    state.villagers["a"].inventory.add_tools([Tool("axe", 1)])
    engine = Engine(econ)
    events = engine.step(state, [Deposit("a", "b0", "axe", 1)])[1]
    assert of(events, "item_deposited") == [{"actor": "a", "building": "b0", "item": "axe", "qty": 1}]
    assert hut.storage.tools == [Tool("axe", 1)]
    engine.step(state, [Take("a", "b0", "axe", 1)])
    assert state.villagers["a"].inventory.tools == [Tool("axe", 1)]


def store_world(make_world: MakeWorld, econ: Registry) -> WorldState:
    state = world(make_world)
    with_hut(state, complete=True).storage.add(econ, "wood", 9)
    state.buildings["b1"] = Building("b1", "hut", Coord(4, 1), PERSONAL_A)
    state.buildings["b2"] = Building("b2", "workshop", Coord(0, 0), PERSONAL_A, complete=True)
    state.villagers["a"].inventory.add(econ, "wood", 2)
    state.villagers["b"].inventory.add(econ, "wood", 15)
    return state


@pytest.mark.req("REQ-SIM-013")
@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        (Deposit("a", "b9", "wood", 1), "unknown_building"),
        (Deposit("b", "b1", "wood", 1), "no_storage"),
        (Deposit("a", "b2", "wood", 1), "no_storage"),
        (Deposit("c", "b0", "wood", 1), "not_at_location"),
        (Deposit("a", "b0", "wood", 0), "bad_quantity"),
        (Deposit("a", "b0", "wood", 3), "missing_items"),
        (Deposit("a", "b0", "wood", 2), "store_full"),
        (Take("a", "b9", "wood", 1), "unknown_building"),
        (Take("a", "b2", "wood", 1), "no_storage"),
        (Take("c", "b0", "wood", 1), "not_at_location"),
        (Take("a", "b0", "wood", -2), "bad_quantity"),
        (Take("a", "b0", "wood", 10), "missing_items"),
        (Take("a", "b0", "dragon", 1), "missing_items"),
        (Take("b", "b0", "wood", 1), "carry_limit"),
    ],
)
def test_invalid_store_transfers_are_rejected(
    econ: Registry, make_world: MakeWorld, intent: Intent, reason: str
) -> None:
    """AC2: a take that would exceed the carry limit is rejected, like every invalid transfer."""
    state = store_world(make_world, econ)
    before = state.to_dict()
    events = Engine(econ).step(state, [intent])[1]
    assert reasons(events) == [reason]
    after = state.to_dict()
    assert after["villagers"] == before["villagers"]
    assert after["buildings"] == before["buildings"]


def test_a_store_fills_up_to_its_capacity(econ: Registry, make_world: MakeWorld) -> None:
    state = store_world(make_world, econ)
    events = Engine(econ).step(state, [Deposit("a", "b0", "wood", 1)])[1]
    assert [event.kind for event in events] == ["item_deposited"]
    assert state.buildings["b0"].storage.items == {"wood": 10}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/pericles/test_construction.py -q`
Expected: collection error `ImportError: cannot import name 'Construct' from 'pericles.core.intents'`.

- [ ] **Step 3: Add the intents**

Append to `src/pericles/core/intents.py`:

```python
@dataclass(frozen=True)
class PlaceBuilding(Intent):
    building: str
    origin: Coord
    ownership: str = "personal"
    co_owners: tuple[str, ...] = ()
    kind: ClassVar[str] = "place_building"


@dataclass(frozen=True)
class Deliver(Intent):
    building: str
    item: str
    qty: int
    kind: ClassVar[str] = "deliver"


@dataclass(frozen=True)
class Construct(Intent):
    building: str
    kind: ClassVar[str] = "construct"


@dataclass(frozen=True)
class Deposit(Intent):
    building: str
    item: str
    qty: int
    kind: ClassVar[str] = "deposit"


@dataclass(frozen=True)
class Take(Intent):
    building: str
    item: str
    qty: int
    kind: ClassVar[str] = "take"
```

- [ ] **Step 4: Implement `src/pericles/core/construction.py`**

```python
"""Construction sites, building work and stores (REQ-SIM-009, REQ-SIM-004, REQ-ECO-001)."""

from __future__ import annotations

from pericles.core.buildings import (
    Building,
    Ownership,
    building_tiles,
    footprint,
    near,
    remaining_cost,
    storage_capacity,
)
from pericles.core.context import Context, reject
from pericles.core.events import EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import Construct, Deliver, Deposit, Intent, PlaceBuilding, Take
from pericles.core.inventory import fits, transfer
from pericles.core.state import Villager, WorldState
from pericles.core.work import EPSILON, start_work, used_tools, work_speed


def blocked_tiles(ctx: Context, state: WorldState) -> frozenset[Coord]:
    """Footprint tiles of buildings and sites without an entrance (REQ-SIM-004 AC3)."""
    registry = ctx.registry
    return frozenset(
        tile
        for building in state.buildings.values()
        if not registry.buildings[building.kind].entrance
        for tile in building_tiles(building, registry)
    )


def _occupied(ctx: Context, state: WorldState) -> set[Coord]:
    tiles = {tile for b in state.buildings.values() for tile in building_tiles(b, ctx.registry)}
    tiles.update(node.pos for node in state.nodes.values())
    return tiles


def _ownership(state: WorldState, intent: PlaceBuilding) -> Ownership | None:
    if any(owner not in state.villagers for owner in intent.co_owners):
        return None
    if intent.ownership == "communal":
        owners = intent.co_owners
    else:
        owners = tuple(sorted({intent.actor, *intent.co_owners}))
    try:
        return Ownership(intent.ownership, owners)
    except ValueError:
        return None


def place_building(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, PlaceBuilding)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    definition = registry.buildings.get(intent.building)
    if definition is None:
        return reject(sink, intent, "unknown_building")
    if not ctx.available(state, villager, definition.id):
        return reject(sink, intent, "locked")
    ownership = _ownership(state, intent)
    if ownership is None:
        return reject(sink, intent, "bad_ownership")
    origin = Coord(*intent.origin)
    tiles = footprint(origin, definition.footprint)
    if not all(state.tilemap.in_bounds(tile) for tile in tiles):
        return reject(sink, intent, "out_of_bounds")
    if not all(registry.terrains[state.tilemap.terrain_at(tile)].walkable for tile in tiles):
        return reject(sink, intent, "bad_terrain")
    if not _occupied(ctx, state).isdisjoint(tiles):
        return reject(sink, intent, "occupied")
    if not definition.entrance and any(v.pos in tiles for v in state.villagers.values()):
        return reject(sink, intent, "occupied")
    if not near(villager.pos, tiles):
        return reject(sink, intent, "not_at_location")
    building_id = f"b{state.next_building}"
    state.next_building += 1
    state.buildings[building_id] = Building(building_id, definition.id, origin, ownership)
    sink.emit(
        "site_placed",
        actor=villager.id,
        building=building_id,
        kind=definition.id,
        origin=list(origin),
        ownership=ownership.to_dict(),
    )


def _site(
    ctx: Context, state: WorldState, villager: Villager, intent: Intent, building_id: str, sink: EventSink
) -> Building | None:
    """An unfinished building within reach, or None after rejecting the intent."""
    building = state.buildings.get(building_id)
    if building is None:
        problem = "unknown_building"
    elif building.complete:
        problem = "already_complete"
    elif not near(villager.pos, building_tiles(building, ctx.registry)):
        problem = "not_at_location"
    else:
        return building
    reject(sink, intent, problem)
    return None


def deliver(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Deliver)
    villager = state.villagers[intent.actor]
    building = _site(ctx, state, villager, intent, intent.building, sink)
    if building is None:
        return None
    if intent.qty <= 0:
        return reject(sink, intent, "bad_quantity")
    if intent.qty > remaining_cost(building, ctx.registry).get(intent.item, 0):
        return reject(sink, intent, "not_needed")
    if villager.inventory.count(intent.item) < intent.qty:
        return reject(sink, intent, "missing_items")
    villager.inventory.remove(intent.item, intent.qty)
    building.delivered[intent.item] = building.delivered.get(intent.item, 0) + intent.qty
    sink.emit(
        "delivered", actor=villager.id, building=building.id, item=intent.item, qty=intent.qty
    )
    return None


def construct(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Construct)
    villager = state.villagers[intent.actor]
    building = _site(ctx, state, villager, intent, intent.building, sink)
    if building is None:
        return None
    if remaining_cost(building, ctx.registry):
        return reject(sink, intent, "missing_materials")
    definition = ctx.registry.buildings[building.kind]
    tools = used_tools(ctx, villager, "building", building.kind, definition.tags, ()) or []
    speed = work_speed(
        ctx,
        state,
        villager,
        kind="building",
        ident=building.kind,
        tags=definition.tags,
        skill=None,
        tools=tools,
        building=building.id,
    )
    return start_work(
        ctx,
        villager,
        intent,
        sink,
        kind="construction",
        ident=building.kind,
        target=building.id,
        work=definition.build_work,
        speed=speed,
        inputs={},
        done=building.work_done,
    )


def progress(ctx: Context, state: WorldState, villager: Villager, sink: EventSink) -> None:
    """Add one tick of this villager's build work; complete the building when it is done."""
    activity = villager.activity
    assert activity is not None
    assert activity.target is not None
    building = state.buildings[activity.target]
    work = float(ctx.registry.buildings[building.kind].build_work)
    building.work_done = min(work, building.work_done + activity.speed)
    activity.done = building.work_done
    if building.work_done >= work - EPSILON:
        _complete(state, building, sink)


def _complete(state: WorldState, building: Building, sink: EventSink) -> None:
    building.complete = True
    destroyed = dict(sorted(building.delivered.items()))
    building.delivered = {}
    sink.emit("building_completed", building=building.id, kind=building.kind, destroyed=destroyed)
    for vid in sorted(state.villagers):
        villager = state.villagers[vid]
        activity = villager.activity
        if activity is not None and activity.kind == "construction" and activity.target == building.id:
            villager.activity = None
            sink.emit(
                "work_done",
                actor=vid,
                work="construction",
                ident=building.kind,
                target=building.id,
                created={},
                destroyed={},
            )


def _store(
    ctx: Context, state: WorldState, villager: Villager, intent: Deposit | Take, sink: EventSink
) -> Building | None:
    """A completed store within reach and a positive quantity, or None after rejecting."""
    building = state.buildings.get(intent.building)
    if building is None:
        problem = "unknown_building"
    elif storage_capacity(ctx.registry, building) == 0:
        problem = "no_storage"
    elif not near(villager.pos, building_tiles(building, ctx.registry)):
        problem = "not_at_location"
    elif intent.qty <= 0:
        problem = "bad_quantity"
    else:
        return building
    reject(sink, intent, problem)
    return None


def deposit(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Deposit)
    villager = state.villagers[intent.actor]
    building = _store(ctx, state, villager, intent, sink)
    if building is None:
        return None
    if villager.inventory.count(intent.item) < intent.qty:
        return reject(sink, intent, "missing_items")
    stored = sum(building.storage.totals().values())
    if stored + intent.qty > storage_capacity(ctx.registry, building):
        return reject(sink, intent, "store_full")
    transfer(ctx.registry, villager.inventory, building.storage, intent.item, intent.qty)
    sink.emit(
        "item_deposited", actor=villager.id, building=building.id, item=intent.item, qty=intent.qty
    )
    return None


def take(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Take)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    building = _store(ctx, state, villager, intent, sink)
    if building is None:
        return None
    if building.storage.count(intent.item) < intent.qty:
        return reject(sink, intent, "missing_items")
    if not fits(registry, villager.inventory, {intent.item: intent.qty}, ctx.config.carry_limit):
        return reject(sink, intent, "carry_limit")
    transfer(registry, building.storage, villager.inventory, intent.item, intent.qty)
    ownership = building.ownership
    sink.emit(
        "item_taken",
        actor=villager.id,
        building=building.id,
        item=intent.item,
        qty=intent.qty,
        ownership=ownership.kind,
    )
    if not ownership.owned_by(villager.id):
        sink.emit(
            "take_unowned",
            actor=villager.id,
            store=building.id,
            item=intent.item,
            qty=intent.qty,
            owners=list(ownership.owners),
        )
    return None
```

- [ ] **Step 5: Wire the engine**

In `src/pericles/core/engine.py`:
- Import `construction` next to `work`: `from pericles.core import construction, work`.
- Extend the intents import to `Construct, Deliver, Deposit, Intent, MoveTo, PlaceBuilding, StartAction, Take, Wait`.
- Add `from pericles.core.geometry import Coord`.

Add to the `_handlers` dict:

```python
            PlaceBuilding: partial(construction.place_building, self.context),
            Deliver: partial(construction.deliver, self.context),
            Construct: partial(construction.construct, self.context),
            Deposit: partial(construction.deposit, self.context),
            Take: partial(construction.take, self.context),
```

Replace the two cache attributes in `__init__`:

```python
        self._field_key: tuple[TileMap, frozenset[Coord]] | None = (
            None  # pragma: no mutate - cache sentinel; any non-matching value just forces a rebuild
        )
        self._field: TerrainCostField | None = (
            None  # pragma: no mutate - cache sentinel; any non-None value just forces a rebuild
        )
```

Replace `_cost_field`:

```python
    def _cost_field(self, state: WorldState) -> TerrainCostField:
        """Cached per tilemap object and blocked-tile set (ADR-0014 §7)."""
        blocked = construction.blocked_tiles(self.context, state)
        key = self._field_key
        if self._field is None or key is None or key[0] is not state.tilemap or key[1] != blocked:
            self._field = TerrainCostField(state.tilemap, self.registry, blocked.__contains__)
            self._field_key = (state.tilemap, blocked)
        return self._field
```

In `_advance_work`, route construction to `progress` before the generic branch:

```python
            if activity is None:
                continue
            if activity.kind == "construction":
                construction.progress(self.context, state, villager, sink)
                continue
            activity.done += activity.speed
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass. That includes M1a's `test_path_blocked_after_terrain_change`, which replaces the tilemap.

- [ ] **Step 7: Gates, mutation, commit**

Run the gates. Then: `rm -rf mutants && uv run mutmut run "pericles.core.construction.*" "pericles.core.engine.*" ; uv run mutmut results --all true`
Kill the survivors, then `rm -rf mutants`.

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): construction sites, building work, walls and owned stores"
```

---

### Task 5: Recipes and research

**Files:**
- Modify: `src/pericles/core/intents.py`, `src/pericles/core/work.py`, `src/pericles/core/engine.py`
- Test: `tests/pericles/test_work_recipes.py`

**Interfaces:**
- Consumes (Task 3): `Context`, `reject`, `used_tools`, `work_speed`, `start_work`, `finish`, `interrupt`, `_FINISHERS`. Also `Building`, `Ownership`, `building_tiles`, `near`, `bundle_weight`, `fits`, and `Modifier`, `Scope` (M1a).
- Produces:
  - `intents.Craft(actor, recipe: str, building: str)`, kind `"craft"`
  - `intents.Research(actor, technology: str, building: str)`, kind `"research"`
  - In `work`:
    - `WORKPLACE_KINDS = ("recipe", "research")`
    - `workplace(ctx, state, villager, intent, building_id, kind, sink) -> Building | None`
    - `start_recipe` and `start_research` (handlers)
    - `_FINISHERS` gains `"recipe"` and `"research"`
  - **Events:** `technology_learned {actor, technology, scope}`, emitted after the researcher's `work_done`.
  - **Rejection reasons:**
    - Recipes: `unknown_recipe`, `locked`, `bad_target`, `incomplete`, `not_at_location`, `building_full`, `missing_inputs`, `carry_limit`, `cannot_work`.
    - Research: `unknown_technology`, `already_known`, the four workplace reasons, `missing_inputs`, `cannot_work`.
  - A village-scoped research that someone else completes first is interrupted with cause `engine`, reason `already_known`.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_work_recipes.py`:

```python
from collections.abc import Callable, Sequence

import pytest

from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Craft, Intent, MoveTo, PlaceBuilding, Research, StartAction
from pericles.core.modifiers import Modifier, Op, Scope, Target
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

MakeWorld = Callable[..., WorldState]
COMMUNAL = Ownership("communal")


def world(make_world: MakeWorld) -> WorldState:
    """Workshop w0 at (1,1), academy s0 at (3,1), site w1 at (5,1), far workshop w2 at (5,3).

    Ana (1,0) and Bo (2,1) reach the workshop; Bo and Cy (3,0) reach the academy.
    """
    villagers = [
        Villager("a", "Ana", Coord(1, 0)),
        Villager("b", "Bo", Coord(2, 1)),
        Villager("c", "Cy", Coord(3, 0)),
    ]
    rows = ["......"] * 4
    state = make_world(rows, villagers, [Node("n0", "tree", Coord(0, 0), 6)])
    state.buildings = {
        "w0": Building("w0", "workshop", Coord(1, 1), COMMUNAL, complete=True),
        "s0": Building("s0", "academy", Coord(3, 1), COMMUNAL, complete=True),
        "w1": Building("w1", "workshop", Coord(5, 1), COMMUNAL),
        "w2": Building("w2", "workshop", Coord(5, 3), COMMUNAL, complete=True),
    }
    return state


def run(engine: Engine, state: WorldState, intents: Sequence[Intent], ticks: int) -> list[Event]:
    events = list(engine.step(state, intents)[1])
    for _ in range(ticks - 1):
        events += engine.step(state, [])[1]
    return events


def of(events: list[Event], kind: str) -> list[dict[str, object]]:
    return [dict(event.data) for event in events if event.kind == kind]


def reasons(events: list[Event]) -> list[object]:
    return [d["reason"] for d in of(events, "intent_rejected")]


@pytest.mark.req("REQ-SIM-010")
@pytest.mark.req("REQ-SIM-009")
def test_a_recipe_turns_inputs_into_outputs_after_its_work_time(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC1 (SIM-010) / AC3 (SIM-009): a completed workshop hosts saw: 2 wood → 3 planks in 6 ticks."""
    state = world(make_world)
    villager = state.villagers["a"]
    villager.inventory.add(econ, "wood", 2)
    engine = Engine(econ)
    events = run(engine, state, [Craft("a", "saw", "w0")], 5)
    assert of(events, "work_started")[0] == {
        "actor": "a",
        "work": "recipe",
        "ident": "saw",
        "target": "w0",
        "ticks": 6,
    }
    assert villager.inventory.items == {}
    events = engine.step(state, [])[1]
    assert of(events, "work_done") == [
        {
            "actor": "a",
            "work": "recipe",
            "ident": "saw",
            "target": "w0",
            "created": {"plank": 3},
            "destroyed": {"wood": 2},
        }
    ]
    assert villager.inventory.items == {"plank": 3}
    assert villager.skills == {"carpentry": 1.0}


@pytest.mark.req("REQ-SIM-010")
def test_an_interrupted_recipe_returns_its_inputs(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: inputs are consumed only when the work time is complete."""
    state = world(make_world)
    state.villagers["a"].inventory.add(econ, "wood", 2)
    engine = Engine(econ)
    run(engine, state, [Craft("a", "saw", "w0")], 5)
    engine.step(state, [MoveTo("a", Coord(0, 1))])
    assert state.villagers["a"].inventory.items == {"wood": 2}


@pytest.mark.req("REQ-SIM-010")
@pytest.mark.parametrize(
    ("intent", "wood", "reason"),
    [
        (Craft("a", "glue", "w0"), 2, "unknown_recipe"),
        (Craft("a", "make_axe", "w0"), 2, "locked"),
        (Craft("a", "saw", "s0"), 2, "bad_target"),
        (Craft("a", "saw", "w9"), 2, "bad_target"),
        (Craft("a", "saw", "w1"), 2, "incomplete"),
        (Craft("a", "saw", "w2"), 2, "not_at_location"),
        (Craft("a", "saw", "w0"), 1, "missing_inputs"),
        (Craft("a", "press", "w0"), 15, "carry_limit"),
    ],
)
def test_invalid_recipes_are_rejected(
    econ: Registry, make_world: MakeWorld, intent: Craft, wood: int, reason: str
) -> None:
    """AC1: a recipe needs a known, unlocked recipe at a complete building of its kind."""
    state = world(make_world)
    state.villagers["a"].inventory.add(econ, "wood", wood)
    state.villagers["a"].inventory.add(econ, "berries", 2)
    events = Engine(econ).step(state, [intent])[1]
    assert reasons(events) == [reason]
    assert state.villagers["a"].activity is None


@pytest.mark.req("REQ-SIM-009")
def test_a_building_hosts_at_most_its_workers(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: the workshop has one workplace; a second crafter is turned away."""
    state = world(make_world)
    for vid in "ab":
        state.villagers[vid].inventory.add(econ, "wood", 2)
    engine = Engine(econ)
    engine.step(state, [Craft("b", "saw", "w0")])
    assert reasons(engine.step(state, [Craft("a", "saw", "w0")])[1]) == ["building_full"]
    engine.step(state, [MoveTo("b", Coord(2, 2))])
    events = engine.step(state, [Craft("a", "saw", "w0")])[1]
    assert [event.kind for event in events] == ["work_started"]


@pytest.mark.req("REQ-SIM-011")
def test_villager_research_unlocks_for_the_researcher_only(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC1/AC2: lore unlocks make_axe and vault and speeds saw, for its researcher only."""
    state = world(make_world)
    state.villagers["c"].inventory.add(econ, "plank", 1)
    engine = Engine(econ)
    events = run(engine, state, [Research("c", "lore", "s0")], 5)
    assert of(events, "work_done")[0]["destroyed"] == {"plank": 1}
    assert of(events, "technology_learned") == [
        {"actor": "c", "technology": "lore", "scope": "villager"}
    ]
    assert [event.kind for event in events][-2:] == ["work_done", "technology_learned"]
    assert state.villagers["c"].knowledge == {"lore", "make_axe", "vault"}
    assert state.village_knowledge == set()
    assert state.modifiers == (
        Modifier(
            Target("recipe", "saw"), "work_speed", Op.MUL, 2.0, "technology:lore", Scope(villager="c")
        ),
    )
    assert engine.context.available(state, state.villagers["c"], "make_axe")
    assert not engine.context.available(state, state.villagers["a"], "make_axe")


@pytest.mark.req("REQ-SIM-011")
def test_village_research_unlocks_for_everyone(econ: Registry, make_world: MakeWorld) -> None:
    """AC1/AC2: commons is village-scoped; its labour bonus applies to every villager."""
    state = world(make_world)
    engine = Engine(econ)
    run(engine, state, [Research("c", "commons", "s0")], 3)
    assert state.village_knowledge == {"commons"}
    assert state.villagers["c"].knowledge == set()
    events = engine.step(state, [StartAction("a", "chop", "n0")])[1]
    assert of(events, "work_started")[0]["ticks"] == 5  # 1 + 1 from commons


@pytest.mark.req("REQ-SIM-011")
def test_learned_technologies_unlock_recipes_and_buildings(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: after lore, its researcher can craft make_axe and place a vault."""
    state = world(make_world)
    researcher = state.villagers["b"]
    researcher.inventory.add(econ, "plank", 2)
    researcher.inventory.add(econ, "wood", 1)
    engine = Engine(econ)
    run(engine, state, [Research("b", "lore", "s0")], 5)
    events = run(engine, state, [Craft("b", "make_axe", "w0")], 4)
    assert of(events, "work_done")[0]["created"] == {"axe": 1}
    events = engine.step(state, [PlaceBuilding("b", "vault", Coord(2, 2))])[1]
    assert [event.kind for event in events] == ["site_placed"]


@pytest.mark.req("REQ-SIM-011")
def test_two_village_researchers_learn_once(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: if two villagers finish the same village research together, only the first learns it."""
    state = world(make_world)
    engine = Engine(econ)
    intents = [Research("b", "commons", "s0"), Research("c", "commons", "s0")]
    events = run(engine, state, intents, 3)
    assert [d["actor"] for d in of(events, "technology_learned")] == ["b"]
    assert of(events, "work_interrupted") == [
        {
            "actor": "c",
            "work": "research",
            "ident": "commons",
            "target": "s0",
            "cause": "engine",
            "reason": "already_known",
        }
    ]
    assert len(state.modifiers) == 1
    assert reasons(engine.step(state, [Research("c", "commons", "s0")])[1]) == ["already_known"]


@pytest.mark.req("REQ-SIM-011")
@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        (Research("c", "alchemy", "s0"), "unknown_technology"),
        (Research("c", "lore", "w0"), "bad_target"),
        (Research("a", "lore", "s0"), "not_at_location"),
        (Research("c", "lore", "s0"), "missing_inputs"),
    ],
)
def test_invalid_research_is_rejected(
    econ: Registry, make_world: MakeWorld, intent: Research, reason: str
) -> None:
    """AC1: research needs a known technology, its research building and its cost."""
    state = world(make_world)
    assert reasons(Engine(econ).step(state, [intent])[1]) == [reason]


@pytest.mark.req("REQ-SIM-011")
def test_known_villager_research_is_rejected(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: a villager cannot research a technology they already know."""
    state = world(make_world)
    state.villagers["c"].knowledge.add("lore")
    state.villagers["c"].inventory.add(econ, "plank", 1)
    assert reasons(Engine(econ).step(state, [Research("c", "lore", "s0")])[1]) == ["already_known"]


@pytest.mark.req("REQ-SIM-011")
@pytest.mark.parametrize(("factor", "outcome"), [(5.0, 1), (0.0, "cannot_work")])
def test_research_speed_follows_modifiers(
    econ: Registry, make_world: MakeWorld, factor: float, outcome: object
) -> None:
    """AC1: research speed is `research_speed` on the research building."""
    state = world(make_world)
    state.villagers["c"].inventory.add(econ, "plank", 1)
    state.modifiers = (
        Modifier(Target("building", "academy"), "research_speed", Op.MUL, factor, "test"),
    )
    events = Engine(econ).step(state, [Research("c", "lore", "s0")])[1]
    if isinstance(outcome, int):
        assert of(events, "work_started")[0]["ticks"] == outcome
    else:
        assert reasons(events) == [outcome]


@pytest.mark.req("REQ-SIM-011")
def test_the_academy_seats_two_researchers(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: research is limited by the research building's workers."""
    state = world(make_world)
    state.villagers["a"].pos = Coord(4, 1)
    for vid in "abc":
        state.villagers[vid].inventory.add(econ, "plank", 1)
    engine = Engine(econ)
    engine.step(state, [Research("b", "lore", "s0"), Research("c", "lore", "s0")])
    assert reasons(engine.step(state, [Research("a", "lore", "s0")])[1]) == ["building_full"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/pericles/test_work_recipes.py -q`
Expected: collection error `ImportError: cannot import name 'Craft' from 'pericles.core.intents'`.

- [ ] **Step 3: Add the intents**

Append to `src/pericles/core/intents.py`:

```python
@dataclass(frozen=True)
class Craft(Intent):
    recipe: str
    building: str
    kind: ClassVar[str] = "craft"


@dataclass(frozen=True)
class Research(Intent):
    technology: str
    building: str
    kind: ClassVar[str] = "research"
```

- [ ] **Step 4: Extend `src/pericles/core/work.py`**

Update the imports:
- `from pericles.core.buildings import Building, building_tiles, near`
- `from pericles.core.intents import Craft, Intent, Research, StartAction`
- `from pericles.core.inventory import Inventory, Tool, bundle_weight, capacity_for, fits, transfer`
- `from pericles.core.modifiers import Modifier, Op, Scope, Target, resolve`

Add after `EPSILON`:

```python
WORKPLACE_KINDS = ("recipe", "research")
```

Add before `finish`:

```python
def workplace(
    ctx: Context,
    state: WorldState,
    villager: Villager,
    intent: Intent,
    building_id: str,
    kind: str,
    sink: EventSink,
) -> Building | None:
    """A complete building of `kind`, within reach and with a free workplace, or None."""
    building = state.buildings.get(building_id)
    if building is None or building.kind != kind:
        problem = "bad_target"
    elif not building.complete:
        problem = "incomplete"
    elif not near(villager.pos, building_tiles(building, ctx.registry)):
        problem = "not_at_location"
    elif _workers(state, building.id) >= ctx.registry.buildings[kind].workers:
        problem = "building_full"
    else:
        return building
    reject(sink, intent, problem)
    return None


def _workers(state: WorldState, building_id: str) -> int:
    return sum(
        1
        for villager in state.villagers.values()
        if villager.activity is not None
        and villager.activity.kind in WORKPLACE_KINDS
        and villager.activity.target == building_id
    )


def start_recipe(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Craft)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    recipe = registry.recipes.get(intent.recipe)
    if recipe is None:
        return reject(sink, intent, "unknown_recipe")
    if not ctx.available(state, villager, recipe.id):
        return reject(sink, intent, "locked")
    building = workplace(ctx, state, villager, intent, intent.building, recipe.building, sink)
    if building is None:
        return None
    if not villager.inventory.has(recipe.inputs):
        return reject(sink, intent, "missing_inputs")
    freed = bundle_weight(registry, recipe.inputs)
    if not fits(registry, villager.inventory, recipe.outputs, ctx.config.carry_limit, freed):
        return reject(sink, intent, "carry_limit")
    tools = used_tools(ctx, villager, "recipe", recipe.id, (), ()) or []
    speed = work_speed(
        ctx,
        state,
        villager,
        kind="recipe",
        ident=recipe.id,
        tags=(),
        skill=recipe.skill,
        tools=tools,
        building=building.id,
    )
    return start_work(
        ctx,
        villager,
        intent,
        sink,
        kind="recipe",
        ident=recipe.id,
        target=building.id,
        work=recipe.work_ticks,
        speed=speed,
        inputs=recipe.inputs,
    )


def start_research(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Research)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    tech = registry.technologies.get(intent.technology)
    if tech is None:
        return reject(sink, intent, "unknown_technology")
    known = state.village_knowledge if tech.scope == "village" else villager.knowledge
    if tech.id in known:
        return reject(sink, intent, "already_known")
    building = workplace(ctx, state, villager, intent, intent.building, tech.building, sink)
    if building is None:
        return None
    if not villager.inventory.has(tech.cost):
        return reject(sink, intent, "missing_inputs")
    tags = registry.buildings[building.kind].tags
    tools = used_tools(ctx, villager, "building", building.kind, tags, ()) or []
    speed = work_speed(
        ctx,
        state,
        villager,
        kind="building",
        ident=building.kind,
        tags=tags,
        skill=None,
        tools=tools,
        attribute="research_speed",
        building=building.id,
    )
    return start_work(
        ctx,
        villager,
        intent,
        sink,
        kind="research",
        ident=tech.id,
        target=building.id,
        work=tech.research_ticks,
        speed=speed,
        inputs=tech.cost,
    )
```

Add after `_finish_action`:

```python
def _finish_recipe(
    ctx: Context, state: WorldState, villager: Villager, activity: Activity, sink: EventSink
) -> None:
    registry = ctx.registry
    recipe = registry.recipes[activity.ident]
    for item, qty in sorted(recipe.outputs.items()):
        villager.inventory.add(registry, item, qty)
    finish(
        ctx,
        villager,
        activity,
        sink,
        created=recipe.outputs,
        skill=recipe.skill,
        tool_kind="recipe",
        tool_ident=recipe.id,
        tags=(),
        required=(),
    )


def _finish_research(
    ctx: Context, state: WorldState, villager: Villager, activity: Activity, sink: EventSink
) -> None:
    registry = ctx.registry
    tech = registry.technologies[activity.ident]
    village = tech.scope == "village"
    known = state.village_knowledge if village else villager.knowledge
    if tech.id in known:
        interrupt(ctx, villager, sink, cause="engine", reason="already_known")
        return
    known.update((tech.id, *tech.unlocks_recipes, *tech.unlocks_buildings))
    scope = Scope() if village else Scope(villager=villager.id)
    source = f"technology:{tech.id}"
    state.modifiers = state.modifiers + tuple(
        Modifier.from_def(m, source, scope) for m in tech.modifiers
    )
    assert activity.target is not None
    kind = state.buildings[activity.target].kind
    finish(
        ctx,
        villager,
        activity,
        sink,
        created={},
        skill=None,
        tool_kind="building",
        tool_ident=kind,
        tags=registry.buildings[kind].tags,
        required=(),
    )
    sink.emit("technology_learned", actor=villager.id, technology=tech.id, scope=tech.scope)
```

Replace the `_FINISHERS` line:

```python
_FINISHERS: dict[str, Finisher] = {
    "action": _finish_action,
    "recipe": _finish_recipe,
    "research": _finish_research,
}
```

- [ ] **Step 5: Register the handlers**

In `src/pericles/core/engine.py`:
- Add `Craft` and `Research` to the intents import.
- Add these two entries to `_handlers`:

```python
            Craft: partial(work.start_recipe, self.context),
            Research: partial(work.start_research, self.context),
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass.

- [ ] **Step 7: Gates, mutation, commit**

Run the gates. Then: `rm -rf mutants && uv run mutmut run "pericles.core.work.*" ; uv run mutmut results --all true`
Kill the survivors, then `rm -rf mutants`.

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): recipes at buildings and technology research"
```

---

### Task 6: Engine invariants: conservation checker, debug mode, random-play property test

**Files:**
- Create: `src/pericles/core/invariants.py`
- Modify: `src/pericles/core/engine.py`
- Test: `tests/pericles/test_invariants.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5. That includes the full `Engine`, every intent, `storage_capacity`, `inventory.EPSILON` and `canonical_json` (M1a).
- Produces:
  - `invariants.InvariantError(AssertionError)`
  - `item_totals(state) -> Counter[str]`, summing inventories, reserved inputs, delivered materials and stores
  - `ledger(events) -> Counter[str]`, the net of `created` minus `destroyed`
  - `check_conservation(before, after, events) -> list[str]`
  - `check_state(ctx, state) -> list[str]`
  - `check_tick(ctx, before, state, events) -> list[str]`
  - With `EngineConfig(debug_invariants=True)`, `Engine.step` raises `InvariantError("tick N: …")` after any tick that breaks an invariant.

- [ ] **Step 1: Write the failing tests**

`tests/pericles/test_invariants.py`:

```python
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pericles.core.buildings import Building, Ownership
from pericles.core.canonical import canonical_json
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import (
    Construct,
    Craft,
    Deliver,
    Deposit,
    Intent,
    MoveTo,
    PlaceBuilding,
    Research,
    StartAction,
    Take,
    Wait,
)
from pericles.core.inventory import Inventory, Tool
from pericles.core.invariants import (
    InvariantError,
    check_conservation,
    check_state,
    item_totals,
    ledger,
)
from pericles.core.nodes import Node
from pericles.core.state import Activity, Villager, WorldState

MakeWorld = Callable[..., WorldState]
COMMUNAL = Ownership("communal")


def village(make_world: MakeWorld, econ: Registry) -> WorldState:
    """Three stocked villagers around a workshop, an academy, a store and two nodes."""
    villagers = [
        Villager("a", "Ana", Coord(1, 0)),
        Villager("b", "Bo", Coord(2, 1)),
        Villager("c", "Cy", Coord(3, 0)),
    ]
    for villager in villagers:
        for item, qty in (("wood", 4), ("berries", 2), ("plank", 2), ("seed", 1)):
            villager.inventory.add(econ, item, qty)
    villagers[0].inventory.add(econ, "hammer", 1)
    villagers[1].inventory.add(econ, "axe", 1)
    nodes = [Node("n0", "tree", Coord(0, 0), 6), Node("n1", "bush", Coord(4, 2), 4)]
    state = make_world(["......", "......", "...~..", "......"], villagers, nodes)
    state.buildings = {
        "w0": Building("w0", "workshop", Coord(1, 1), COMMUNAL, complete=True),
        "s0": Building("s0", "academy", Coord(3, 1), COMMUNAL, complete=True),
        "h0": Building("h0", "hut", Coord(4, 0), Ownership("personal", ("c",)), complete=True),
    }
    state.buildings["h0"].storage.add(econ, "wood", 5)
    return state


# --- the checker ---------------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-018")
def test_item_totals_cover_every_container(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: inventories, reserved inputs, delivered materials and stores all count."""
    state = village(make_world, econ)
    reserved = Inventory()
    reserved.add(econ, "wood", 1)
    state.villagers["a"].activity = Activity("action", "whittle", None, 6.0, 0.0, 1.0, reserved)
    state.buildings["w1"] = Building("w1", "hut", Coord(0, 3), COMMUNAL, {"wood": 2})
    totals = item_totals(state)
    assert totals["wood"] == 3 * 4 + 1 + 2 + 5
    assert (totals["hammer"], totals["axe"], totals["plank"]) == (1, 1, 6)


@pytest.mark.req("REQ-SIM-018")
def test_ledger_nets_created_and_destroyed() -> None:
    """AC1: item totals may change only by what events create or destroy."""
    events = [
        Event(0, 0, "work_done", {"created": {"plank": 2}, "destroyed": {"wood": 1}}),
        Event(0, 1, "tool_broken", {"destroyed": {"hammer": 1}}),
        Event(0, 2, "moved", {"to": [1, 0]}),
    ]
    assert ledger(events) == Counter({"plank": 2, "wood": -1, "hammer": -1})
    before = Counter({"wood": 3, "hammer": 1})
    after = Counter({"wood": 2, "plank": 2})
    assert check_conservation(before, after, events) == []
    assert check_conservation(before, Counter({"wood": 3, "plank": 2}), events) == [
        "item 'wood': expected 2, found 3"
    ]
    assert check_conservation(Counter(), Counter({"seed": 1}), []) == [
        "item 'seed': expected 0, found 1"
    ]


def _negative(state: WorldState) -> None:
    state.villagers["a"].inventory.items["wood"] = -1


def _worn_out(state: WorldState) -> None:
    state.villagers["a"].inventory.tools[0].durability = 0


def _overloaded(state: WorldState) -> None:
    state.villagers["a"].inventory.items["wood"] = 16


def _overgrown(state: WorldState) -> None:
    state.nodes["n0"].stock = 7


def _overdrawn(state: WorldState) -> None:
    state.nodes["n1"].stock = -1


def _overdelivered(state: WorldState) -> None:
    state.buildings["w1"] = Building("w1", "wall", Coord(0, 3), COMMUNAL, {"wood": 2})


def _overstuffed(state: WorldState) -> None:
    state.buildings["h0"].storage.items["wood"] = 11


def _bad_reserve(state: WorldState) -> None:
    state.villagers["b"].activity = Activity(
        "action", "chop", "n0", 10.0, 0.0, 1.0, Inventory({"wood": 0})
    )


@pytest.mark.req("REQ-SIM-018")
@pytest.mark.parametrize(
    ("corrupt", "problem"),
    [
        (_negative, "villager a holds -1 wood"),
        (_worn_out, "villager a holds a hammer with durability 0"),
        (_overloaded, "villager a carries 36.1, over the limit 30"),
        (_overgrown, "node n0 stock 7 outside 0..6"),
        (_overdrawn, "node n1 stock -1 outside 0..4"),
        (_overdelivered, "building w1 has 2 wood delivered, cost 1"),
        (_overstuffed, "building h0 stores 11, over its capacity 10"),
        (_bad_reserve, "villager b (reserved) holds 0 wood"),
    ],
)
def test_state_checks_name_the_broken_rule(
    econ: Registry,
    make_world: MakeWorld,
    corrupt: Callable[[WorldState], None],
    problem: str,
) -> None:
    """AC1 (REQ-SIM-018) with REQ-SIM-013 AC1/AC2: negative counts, overload and overflow are caught."""
    state = village(make_world, econ)
    ctx = Context.build(econ, EngineConfig())
    assert check_state(ctx, state) == []
    corrupt(state)
    assert check_state(ctx, state) == [problem]


@dataclass(frozen=True)
class Conjure(Intent):
    kind: ClassVar[str] = "conjure"


def conjure_seeds(state: WorldState, intent: Intent, sink: EventSink) -> None:
    state.villagers[intent.actor].inventory.items["seed"] = 5


@pytest.mark.req("REQ-SIM-018")
def test_debug_mode_stops_a_tick_that_breaks_conservation(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: in debug mode the engine checks the invariants after every tick."""
    engine = Engine(econ, EngineConfig(debug_invariants=True))
    engine.register(Conjure, conjure_seeds)
    state = village(make_world, econ)
    with pytest.raises(InvariantError, match=r"^tick 0: item 'seed': expected 3, found 7$"):
        engine.step(state, [Conjure("a")])
    relaxed = Engine(econ)
    relaxed.register(Conjure, conjure_seeds)
    relaxed.step(village(make_world, econ), [Conjure("a")])


# --- random play ---------------------------------------------------------------------------

ACTORS = st.sampled_from(["a", "b", "c", "z"])
BUILDINGS = st.sampled_from(["b0", "b1", "b2", "w0", "s0", "h0", "x"])
ITEMS = st.sampled_from(["wood", "berries", "plank", "seed", "hammer", "axe", "x"])
COORDS = st.builds(Coord, st.integers(-1, 6), st.integers(-1, 4))
QTY = st.integers(-1, 6)
INTENTS = st.one_of(
    st.builds(
        StartAction,
        ACTORS,
        st.sampled_from(["chop", "pick", "whittle", "log", "nail", "sow", "tinker", "x"]),
        st.sampled_from([None, "n0", "n1", "w0", "x"]),
    ),
    st.builds(MoveTo, ACTORS, COORDS),
    st.builds(Wait, ACTORS),
    st.builds(
        PlaceBuilding,
        ACTORS,
        st.sampled_from(["hut", "wall", "workshop", "vault", "x"]),
        COORDS,
        st.sampled_from(["personal", "shared", "communal"]),
        st.sampled_from([(), ("b",), ("c",)]),
    ),
    st.builds(Deliver, ACTORS, BUILDINGS, ITEMS, QTY),
    st.builds(Construct, ACTORS, BUILDINGS),
    st.builds(Deposit, ACTORS, BUILDINGS, ITEMS, QTY),
    st.builds(Take, ACTORS, BUILDINGS, ITEMS, QTY),
    st.builds(Craft, ACTORS, st.sampled_from(["saw", "press", "make_axe", "x"]), BUILDINGS),
    st.builds(Research, ACTORS, st.sampled_from(["lore", "commons", "x"]), BUILDINGS),
)


@pytest.mark.req("REQ-SIM-018")
@pytest.mark.req("REQ-SIM-013")
@settings(
    max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(st.lists(INTENTS, max_size=4), min_size=1, max_size=40))
def test_random_play_keeps_every_invariant(
    econ: Registry, make_world: MakeWorld, ticks: list[list[Intent]]
) -> None:
    """AC2 (property): random play in debug mode conserves items and never breaks a state rule."""
    engine = Engine(econ, EngineConfig(debug_invariants=True))
    state = village(make_world, econ)
    for intents in ticks:
        engine.step(state, intents)
    for _ in range(30):  # let unfinished work complete
        engine.step(state, [])
    assert check_state(engine.context, state) == []


def scripted(tick: int) -> list[Intent]:
    return {
        0: [StartAction("a", "chop", "n0"), Research("b", "commons", "s0"), Wait("c")],
        2: [PlaceBuilding("c", "hut", Coord(3, 3))],
        4: [Deliver("c", "b0", "wood", 4)],
        5: [Construct("c", "b0"), Craft("b", "saw", "w0")],
    }.get(tick, [])


def test_a_restored_snapshot_continues_identically(econ: Registry, make_world: MakeWorld) -> None:
    """A snapshot taken mid-work resumes to the same states and events as the original run."""
    engine = Engine(econ, EngineConfig(debug_invariants=True))
    state = village(make_world, econ)
    state.villagers["c"].pos = Coord(2, 3)
    for tick in range(7):
        engine.step(state, scripted(tick))
    assert state.villagers["c"].activity is not None
    restored = WorldState.from_dict(json.loads(canonical_json(state.to_dict())))
    other = Engine(econ, EngineConfig(debug_invariants=True))
    for tick in range(7, 40):
        _, events = engine.step(state, scripted(tick))
        _, replayed = other.step(restored, scripted(tick))
        assert [e.to_dict() for e in replayed] == [e.to_dict() for e in events]
        assert restored.digest() == state.digest()
    assert state.buildings["b0"].complete
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/pericles/test_invariants.py -q`
Expected: collection error `ModuleNotFoundError: No module named 'pericles.core.invariants'`.

- [ ] **Step 3: Implement `src/pericles/core/invariants.py`**

```python
"""Engine invariants: item conservation and state sanity (REQ-SIM-018, ADR-0014 §4)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pericles.core.buildings import storage_capacity
from pericles.core.context import Context
from pericles.core.events import Event
from pericles.core.inventory import EPSILON, Inventory
from pericles.core.state import WorldState


class InvariantError(AssertionError):
    """The world broke a rule the engine guarantees."""


def item_totals(state: WorldState) -> Counter[str]:
    totals: Counter[str] = Counter()
    for villager in state.villagers.values():
        totals.update(villager.inventory.totals())
        if villager.activity is not None:
            totals.update(villager.activity.reserved.totals())
    for building in state.buildings.values():
        totals.update(building.delivered)
        totals.update(building.storage.totals())
    return totals


def ledger(events: Iterable[Event]) -> Counter[str]:
    """The net change in item totals that the events account for."""
    net: Counter[str] = Counter()
    for event in events:
        for item, qty in event.data.get("created", {}).items():
            net[item] += qty
        for item, qty in event.data.get("destroyed", {}).items():
            net[item] -= qty
    return net


def check_conservation(
    before: Counter[str], after: Counter[str], events: Iterable[Event]
) -> list[str]:
    net = ledger(events)
    problems = []
    for item in sorted(set(before) | set(after) | set(net)):
        expected = before[item] + net[item]
        if after[item] != expected:
            problems.append(f"item {item!r}: expected {expected}, found {after[item]}")
    return problems


def _check_inventory(owner: str, inventory: Inventory) -> list[str]:
    problems = [
        f"{owner} holds {qty} {item}" for item, qty in sorted(inventory.items.items()) if qty <= 0
    ]
    problems += [
        f"{owner} holds a {tool.item} with durability {tool.durability}"
        for tool in inventory.tools
        if tool.durability <= 0
    ]
    return problems


def check_state(ctx: Context, state: WorldState) -> list[str]:
    registry = ctx.registry
    limit = ctx.config.carry_limit
    problems: list[str] = []
    for vid in sorted(state.villagers):
        villager = state.villagers[vid]
        problems += _check_inventory(f"villager {vid}", villager.inventory)
        if villager.activity is not None:
            problems += _check_inventory(f"villager {vid} (reserved)", villager.activity.reserved)
        weight = villager.inventory.weight(registry)
        if weight > limit + EPSILON:
            problems.append(f"villager {vid} carries {weight:g}, over the limit {limit:g}")
    for nid in sorted(state.nodes):
        node = state.nodes[nid]
        maximum = registry.nodes[node.kind].stock
        if not 0 <= node.stock <= maximum:
            problems.append(f"node {nid} stock {node.stock} outside 0..{maximum}")
    for bid in sorted(state.buildings):
        building = state.buildings[bid]
        problems += _check_inventory(f"building {bid}", building.storage)
        cost = registry.buildings[building.kind].cost
        for item, qty in sorted(building.delivered.items()):
            if not 0 < qty <= cost.get(item, 0):
                problems.append(
                    f"building {bid} has {qty} {item} delivered, cost {cost.get(item, 0)}"
                )
        stored = sum(building.storage.totals().values())
        capacity = storage_capacity(registry, building)
        if stored > capacity:
            problems.append(f"building {bid} stores {stored}, over its capacity {capacity}")
    return problems


def check_tick(
    ctx: Context, before: Counter[str], state: WorldState, events: Iterable[Event]
) -> list[str]:
    return check_conservation(before, item_totals(state), events) + check_state(ctx, state)
```

- [ ] **Step 4: Check every tick in debug mode**

In `src/pericles/core/engine.py`, add `from pericles.core.invariants import InvariantError, check_tick, item_totals`.

In `step`, make the first line after `sink = EventSink(state.tick)`:

```python
        before = item_totals(state) if self.config.debug_invariants else None
```

Replace the final `return state, sink.events` with:

```python
        if before is not None:
            problems = check_tick(self.context, before, state, sink.events)
            if problems:
                raise InvariantError(f"tick {state.tick - 1}: " + "; ".join(problems))
        return state, sink.events
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass. If the property test finds a counter-example, it has found a real conservation or carry bug in Tasks 3–5. Fix the engine rule with its own regression test in the owning test file; never weaken the checker.

- [ ] **Step 6: Gates, mutation, commit**

Run the gates. Then: `rm -rf mutants && uv run mutmut run "pericles.core.invariants.*" "pericles.core.engine.*" ; uv run mutmut results --all true`
Kill the survivors, then `rm -rf mutants`.

```bash
git add src/pericles/core tests/pericles
git commit -m "feat(core): item conservation and state invariants with a debug mode"
```

---

### Task 7: Base content, playable defaults, documentation

**Files:**
- Create:
  - `src/pericles/content/base/buildings.yaml`, `recipes.yaml`, `technologies.yaml`
  - `src/pericles/experiment/defaults.py`
  - `tests/pericles/test_base_pack.py`
- Modify:
  - `src/pericles/content/base/items.yaml`, `actions.yaml`
  - `src/pericles/core/content/registry.py`, `tests/pericles/test_registry.py`
  - `docs/requirements/sim.md`, `docs/requirements/eco.md`, `docs/requirements/traceability.md` (generated)
  - `docs/superpowers/specs/2026-11-22-pericles-design.md`, `README.md`

**Interfaces:**
- Consumes: everything from Tasks 1–6, plus `load_registry`, `base_pack_path` and `ContentError` (M1a).
- Produces:
  - `experiment.defaults.DEFAULT_CALENDAR`: four 10-day seasons; winter blocks `sowing`.
  - `experiment.defaults.default_config(**overrides) -> EngineConfig`
  - Registry rule: an action at a node must output that node's yield.

- [ ] **Step 1: Write the failing tests**

Append to `tests/pericles/test_registry.py`:

```python
@pytest.mark.req("REQ-SIM-007")
def test_node_actions_must_output_the_node_yield(tmp_path: Path) -> None:
    """AC1: harvesting draws on a node's stock, so its action must output the node's item."""
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "content.yaml").write_text(
        """
terrains:
  - {id: grass, walkable: true, color: "#8fb35a"}
items:
  - {id: wood}
  - {id: stone}
nodes:
  - {id: tree, yields: wood, terrains: [grass], density: 0.1, stock: 5}
actions:
  - {id: chop, duration_ticks: 5, outputs: {stone: 1}, location: {node: tree}}
""",
        encoding="utf-8",
    )
    with pytest.raises(
        ContentError, match=r"actions\[chop\]\.outputs: must include 'wood', the yield of node 'tree'"
    ):
        load_registry([pack])
```

`tests/pericles/test_base_pack.py`:

```python
import pytest

from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import Research, StartAction
from pericles.core.mapgen import TileMap
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import DEFAULT_CALENDAR, default_config

BUILDINGS = {
    "house",
    "storehouse",
    "farm",
    "fishing_hut",
    "lumber_camp",
    "quarry",
    "mine",
    "smithy",
    "mint",
    "town_hall",
    "palisade",
    "school",
}


def grass_world(villagers: list[Villager]) -> WorldState:
    return WorldState.new(1, TileMap(8, 8, ["grass"] * 64, [0.0] * 64), villagers)


@pytest.mark.req("REQ-SIM-009")
def test_base_pack_has_the_v1_buildings(registry: Registry) -> None:
    """AC4: the base pack includes the twelve v1 buildings."""
    assert set(registry.buildings) == BUILDINGS
    assert registry.buildings["palisade"].entrance is False
    assert registry.buildings["house"].housing > 0
    assert registry.buildings["storehouse"].storage > 0
    hosts = {recipe.building for recipe in registry.recipes.values()}
    assert {"smithy", "mint", "lumber_camp", "fishing_hut"} <= hosts


@pytest.mark.req("REQ-SIM-011")
def test_base_pack_ships_two_school_technologies(registry: Registry) -> None:
    """AC3: at least two sample technologies are researchable at the school."""
    techs = [tech for tech in registry.technologies.values() if tech.building == "school"]
    assert len(techs) >= 2
    assert {tech.scope for tech in techs} == {"villager", "village"}


@pytest.mark.req("REQ-SIM-011")
def test_a_school_technology_can_be_researched(registry: Registry) -> None:
    """AC3: crop_rotation is researched at a completed school and unlocks for the village."""
    villager = Villager("a", "Ana", Coord(0, 0))
    villager.inventory.add(registry, "grain", 10)
    state = grass_world([villager])
    state.buildings["b0"] = Building("b0", "school", Coord(1, 0), Ownership("communal"), complete=True)
    engine = Engine(registry, default_config(debug_invariants=True))
    engine.step(state, [Research("a", "crop_rotation", "b0")])
    for _ in range(registry.technologies["crop_rotation"].research_ticks):
        engine.step(state, [])
    assert "crop_rotation" in state.village_knowledge


@pytest.mark.req("REQ-SIM-003")
def test_the_default_winter_blocks_farming(registry: Registry) -> None:
    """AC2: in the default calendar, winter rejects sowing actions such as farm_grain."""
    assert DEFAULT_CALENDAR.seasons[-1].name == "winter"
    assert DEFAULT_CALENDAR.seasons[-1].blocked_tags == ("sowing",)
    assert "sowing" in registry.actions["farm_grain"].tags
    winter_start = 30 * DEFAULT_CALENDAR.ticks_per_day
    outcomes = []
    for tick in (0, winter_start):
        state = grass_world([Villager("a", "Ana", Coord(0, 0))])
        state.tick = tick
        state.buildings["b0"] = Building(
            "b0", "farm", Coord(1, 0), Ownership("communal"), complete=True
        )
        events = Engine(registry, default_config()).step(state, [StartAction("a", "farm_grain", "b0")])[1]
        outcomes.append((events[0].kind, events[0].data.get("reason")))
    assert outcomes == [("work_started", None), ("intent_rejected", "season")]


def test_default_config_accepts_overrides() -> None:
    config = default_config(carry_limit=12.0)
    assert (config.calendar, config.carry_limit) == (DEFAULT_CALENDAR, 12.0)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/pericles/test_base_pack.py tests/pericles/test_registry.py -q`
Expected:
- `ModuleNotFoundError: No module named 'pericles.experiment.defaults'`
- the registry test fails with `DID NOT RAISE`.

- [ ] **Step 3: Add the registry rule**

In `check_references` in `src/pericles/core/content/registry.py`, add inside the `for ident, action in registry.actions.items():` loop, after the `location.node` reference check:

```python
        node = registry.nodes.get(action.location.node) if action.location.node else None
        if node is not None and node.yields not in action.outputs:
            problems.append(
                f"{where('actions', ident, 'outputs')}: must include {node.yields!r}, "
                f"the yield of node {action.location.node!r}"
            )
```

- [ ] **Step 4: Add the base content**

Append to `src/pericles/content/base/items.yaml`:

```yaml
  - {id: plank, weight: 1.0, tags: [material]}
  - {id: iron, weight: 2.0, tags: [material]}
  - {id: coin, weight: 0.01, tags: [money]}
  - id: axe
    weight: 2.0
    durability: 100
    tags: [tool, axe]
    modifiers:
      - {target: {kind: action, id: fell_tree}, attribute: work_speed, op: mul, value: 1.5}
  - id: pickaxe
    weight: 3.0
    durability: 100
    tags: [tool, pickaxe]
    modifiers:
      - {target: {kind: action, id: quarry_stone}, attribute: work_speed, op: mul, value: 1.5}
      - {target: {kind: action, id: mine_iron}, attribute: work_speed, op: mul, value: 1.5}
      - {target: {kind: action, id: mine_gold}, attribute: work_speed, op: mul, value: 1.5}
  - id: fishing_rod
    weight: 1.0
    durability: 80
    tags: [tool, fishing_rod]
    modifiers:
      - {target: {kind: action, id: catch_fish}, attribute: work_speed, op: mul, value: 1.5}
```

Append to `src/pericles/content/base/actions.yaml`:

```yaml
  - {id: farm_grain, duration_ticks: 120, outputs: {grain: 6}, skill: farming, location: {building: farm}, tags: [labour, sowing]}
```

`src/pericles/content/base/buildings.yaml`:

```yaml
buildings:
  - {id: house, cost: {wood: 10, stone: 4}, build_work: 240, footprint: [2, 2], housing: 4, storage: 20, tags: [home]}
  - {id: storehouse, cost: {wood: 16, stone: 8}, build_work: 360, footprint: [3, 2], storage: 300, tags: [store]}
  - {id: farm, cost: {wood: 6}, build_work: 180, footprint: [3, 3], workers: 4, tags: [food]}
  - {id: fishing_hut, cost: {wood: 8}, build_work: 150, footprint: [2, 1], workers: 2, storage: 30, tags: [food]}
  - {id: lumber_camp, cost: {wood: 8}, build_work: 150, footprint: [2, 1], workers: 2, storage: 40, tags: [industry]}
  - {id: quarry, cost: {wood: 8}, build_work: 180, footprint: [2, 2], storage: 60, tags: [industry]}
  - {id: mine, cost: {wood: 12, stone: 6}, build_work: 300, footprint: [2, 2], storage: 60, tags: [industry]}
  - {id: smithy, cost: {wood: 10, stone: 10}, build_work: 360, footprint: [2, 2], workers: 2, tags: [industry]}
  - {id: mint, cost: {stone: 16, iron: 2}, build_work: 480, footprint: [2, 2], workers: 1, storage: 50, tags: [civic]}
  - {id: town_hall, cost: {wood: 20, stone: 20}, build_work: 600, footprint: [3, 3], storage: 50, tags: [civic]}
  - {id: palisade, cost: {wood: 2}, build_work: 20, entrance: false, tags: [defence]}
  - {id: school, cost: {wood: 14, stone: 6}, build_work: 420, footprint: [3, 2], workers: 3, tags: [research]}
```

`src/pericles/content/base/recipes.yaml`:

```yaml
recipes:
  - {id: saw_planks, building: lumber_camp, inputs: {wood: 1}, outputs: {plank: 2}, work_ticks: 30, skill: carpentry}
  - {id: make_fishing_rod, building: fishing_hut, inputs: {wood: 1, hide: 1}, outputs: {fishing_rod: 1}, work_ticks: 30, skill: fishing}
  - {id: smelt_iron, building: smithy, inputs: {iron_ore: 2, wood: 1}, outputs: {iron: 1}, work_ticks: 60, skill: smithing}
  - {id: forge_axe, building: smithy, inputs: {iron: 1, wood: 1}, outputs: {axe: 1}, work_ticks: 90, skill: smithing}
  - {id: forge_pickaxe, building: smithy, inputs: {iron: 2, wood: 1}, outputs: {pickaxe: 1}, work_ticks: 120, skill: smithing}
  - {id: mint_coins, building: mint, inputs: {gold_ore: 1}, outputs: {coin: 20}, work_ticks: 60, skill: minting}
```

`src/pericles/content/base/technologies.yaml`:

```yaml
technologies:
  - id: metallurgy
    building: school
    cost: {iron_ore: 2}
    research_ticks: 600
    unlocks_recipes: [forge_axe, forge_pickaxe]
  - id: crop_rotation
    building: school
    cost: {grain: 10}
    research_ticks: 900
    scope: village
    modifiers:
      - {target: {kind: action, id: farm_grain}, attribute: work_speed, op: mul, value: 1.25}
```

- [ ] **Step 5: Implement `src/pericles/experiment/defaults.py`**

```python
"""The playable defaults: a four-season year whose winter blocks sowing (ADR-0014 §10)."""

from __future__ import annotations

from typing import Any

from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig

DEFAULT_CALENDAR = Calendar(
    seasons=(
        Season("spring", 10),
        Season("summer", 10),
        Season("autumn", 10),
        Season("winter", 10, blocked_tags=("sowing",)),
    )
)


def default_config(**overrides: Any) -> EngineConfig:
    return EngineConfig(calendar=DEFAULT_CALENDAR, **overrides)
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/pericles -q`
Expected: all pass. `test_core_boundaries` also passes, which confirms that no core string literal equals one of the new base-pack IDs. If it fails, rename the core literal; do not rename the content.

- [ ] **Step 7: Update the documentation**

- `docs/requirements/sim.md`: change the status line from `Must · M1 · Accepted` (or `Should · M1 · Accepted`) to `… · Implemented` for REQ-SIM-004, -007, -008, -009, -010, -011, -013 and -014.
  - Leave REQ-SIM-003 and REQ-SIM-018 `Accepted`. Their remaining parts (winter need rates; consumption and decay events) land in M1c.
- `docs/requirements/eco.md`: set REQ-ECO-001 to `Implemented`.
- In the spec, at `docs/superpowers/specs/2026-11-22-pericles-design.md` line 127, replace

  ```
  | Field (at farm) | sow / tend / harvest | grain (food) |
  ```

  with

  ```
  | Field (at farm) | `farm_grain` (v1, ADR-0014; sow/tend/harvest deferred) | grain (food) |
  ```

- `README.md`: replace the status line with `Status: M1b Work and economy complete; M1c Life and population next.`
- Regenerate and check traceability:

```bash
PYTHONPATH=tools uv run python -m pericles_tools.traceability matrix
PYTHONPATH=tools uv run python -m pericles_tools.traceability check
PYTHONPATH=tools uv run python -m pericles_tools.adr check
```

Expected: the matrix is rewritten, and both checks print OK.

- [ ] **Step 8: Gates, full mutation gate, commit**

Run the gates. Then: `PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run --changed-since origin/main`
Expected: core ≥ 80%. Kill the survivors that remain, if any.

```bash
git add src tests docs README.md
git commit -m "feat(content): base buildings, recipes, tools and technologies; playable defaults; docs"
```
