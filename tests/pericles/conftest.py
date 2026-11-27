# ruff: noqa: E501 (the econ pack keeps one content record per line)
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.executor import Outcome, Progress, advance, begin
from pericles.agents.plan import Step
from pericles.agents.view import Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry, base_pack_path, load_registry
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.mapgen import Band, MapParams, TileMap, Vein, generate_map
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config


@pytest.fixture(scope="session")
def registry() -> Registry:
    return load_registry([base_pack_path()])


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
  - id: hammer
    weight: 1.0
    durability: 2
    tags: [tool, hammer]
    modifiers:
      - {target: {kind: building, id: hut}, attribute: work_speed, op: mul, value: 2.0}
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


TERRAIN = {".": "grass", "~": "water", "T": "forest", "R": "rock"}


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


class FailureLog:
    """Each failed (villager, remembered target) the controller is about to learn from, by
    tick: read it after `engine.step` and before `controller.observe`."""

    WATCHED = ("move_failed", "intent_rejected")

    def __init__(self) -> None:
        self.failures: list[tuple[int, str, str]] = []

    def record(self, memory: Mapping[str, Any], tick: int, events: Iterable[Any]) -> None:
        for event in events:
            interrupted = event.kind == "work_interrupted" and event.data.get("cause") == "engine"
            if event.kind not in self.WATCHED and not interrupted:
                continue
            actor = str(event.data.get("actor"))
            mind = memory.get(actor)
            if mind is not None and mind.target is not None:
                self.failures.append((tick, actor, mind.target))

    def repeats(self, window: int) -> list[tuple[int, str, str]]:
        """Failures of a (villager, target) less than `window` ticks after the last one."""
        last: dict[tuple[str, str], int] = {}
        found = []
        for tick, actor, target in self.failures:
            before = last.get((actor, target))
            if before is not None and tick - before < window:
                found.append((tick, actor, target))
            last[(actor, target)] = tick
        return found


@pytest.fixture
def failure_log() -> Callable[[], FailureLog]:
    return FailureLog


ROWS = ["." * 16] * 16  # a plain 16x16 grass map


@pytest.fixture
def rows() -> list[str]:
    return list(ROWS)


@pytest.fixture
def view_of(registry: Registry) -> Callable[..., View]:
    def build(
        state: WorldState,
        memory: Mapping[str, Memory] | None = None,
        config: AgentConfig | None = None,
    ) -> View:
        config = AgentConfig() if config is None else config
        ctx = Context.build(registry, default_config())
        index = NodeIndex(state.nodes.values(), config.index_cell)
        return View(ctx, state, config, index, {} if memory is None else dict(memory))

    return build


@pytest.fixture
def run(view_of: Callable[..., View]) -> Callable[..., tuple[Outcome, Progress]]:
    def go(
        state: WorldState,
        vid: str,
        step: Step,
        p: Progress | None = None,
        memory: Mapping[str, Memory] | None = None,
        config: AgentConfig | None = None,
    ) -> tuple[Outcome, Progress]:
        villager = state.villagers[vid]
        progress = p if p is not None else begin(state.tick, villager, step)
        return advance(view_of(state, memory, config), villager, step, progress), progress

    return go


@pytest.fixture
def store() -> Callable[..., Building]:
    def build(bid: str, at: Coord, items: dict[str, int] | None = None) -> Building:
        return Building(
            bid,
            "storehouse",
            at,
            Ownership("communal"),
            complete=True,
            storage=Inventory(dict(items or {})),
        )

    return build
