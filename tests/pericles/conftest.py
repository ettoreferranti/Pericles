# ruff: noqa: E501 (the econ pack keeps one content record per line)
import pytest

from pericles.core.content.registry import Registry, base_pack_path, load_registry
from pericles.core.mapgen import Band, MapParams, TileMap, Vein, generate_map


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
