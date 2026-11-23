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
  - {id: water, walkable: false, color: "#3b6ea5"}
items:
  - {id: wood, tags: [material]}
  - {id: axe, tags: [tool], modifiers: [
      {target: {kind: need, id: hunger}, attribute: rate, op: mul, value: 0.9}]}
nodes:
  - {id: tree, yields: wood, terrains: [grass], density: 0.5, stock: 10}
needs:
  - {id: hunger, rate_per_hour: 4}
actions:
  - {id: fell, duration_ticks: 60, inputs: {wood: 2}, outputs: {wood: 2},
     location: {node: tree, terrains: [water]}, requires: {tools: [tool]}, tags: [labour]}
  - {id: craft, duration_ticks: 10, location: {building: hut}}
buildings:
  - {id: hut, cost: {wood: 5}, build_work: 100, tags: [home]}
recipes:
  - {id: plank, building: hut, inputs: {wood: 1}, outputs: {wood: 1}, work_ticks: 10}
technologies:
  - {id: carpentry, building: hut, cost: {wood: 3}, research_ticks: 50,
     unlocks_recipes: [plank], unlocks_buildings: [hut],
     modifiers: [{target: {kind: item, id: axe}, attribute: durability, op: add, value: 1}]}
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


DANGLING = {
    "node-yield": (
        "yields: wood",
        "yields: plank_x",
        "nodes[tree].yields: unknown items id 'plank_x'",
    ),
    "node-terrain": (
        "terrains: [grass]",
        "terrains: [sand]",
        "nodes[tree].terrains: unknown terrains id 'sand'",
    ),
    "action-input": (
        "inputs: {wood: 2}",
        "inputs: {rock: 1}",
        "actions[fell].inputs: unknown items id 'rock'",
    ),
    "action-output": (
        "outputs: {wood: 2}",
        "outputs: {wood: 2, gold: 2}",
        "actions[fell].outputs: unknown items id 'gold'",
    ),
    "action-node": (
        "node: tree,",
        "node: bush,",
        "actions[fell].location.node: unknown nodes id 'bush'",
    ),
    "action-building": (
        "location: {building: hut}",
        "location: {building: mill}",
        "actions[craft].location.building: unknown buildings id 'mill'",
    ),
    "action-terrain": (
        "terrains: [water]",
        "terrains: [sand]",
        "actions[fell].location.terrains: unknown terrains id 'sand'",
    ),
    "tool-tag": (
        "tools: [tool]",
        "tools: [hammer]",
        "actions[fell].requires.tools: no items have tag 'hammer'",
    ),
    "recipe-building": (
        "building: hut, inputs",
        "building: mill, inputs",
        "recipes[plank].building: unknown buildings id 'mill'",
    ),
    "recipe-input": (
        "inputs: {wood: 1}, outputs",
        "inputs: {x3: 1}, outputs",
        "recipes[plank].inputs: unknown items id 'x3'",
    ),
    "recipe-output": (
        "outputs: {wood: 1}",
        "outputs: {x4: 1}",
        "recipes[plank].outputs: unknown items id 'x4'",
    ),
    "building-cost": (
        "cost: {wood: 5}",
        "cost: {clay: 5}",
        "buildings[hut].cost: unknown items id 'clay'",
    ),
    "tech-building": (
        "building: hut, cost: {wood: 3}",
        "building: mill, cost: {wood: 3}",
        "technologies[carpentry].building: unknown buildings id 'mill'",
    ),
    "tech-cost": (
        "cost: {wood: 3}",
        "cost: {x5: 3}",
        "technologies[carpentry].cost: unknown items id 'x5'",
    ),
    "tech-recipe": (
        "unlocks_recipes: [plank]",
        "unlocks_recipes: [bread]",
        "technologies[carpentry].unlocks_recipes: unknown recipes id 'bread'",
    ),
    "tech-building-unlock": (
        "unlocks_buildings: [hut]",
        "unlocks_buildings: [tent]",
        "technologies[carpentry].unlocks_buildings: unknown buildings id 'tent'",
    ),
    "tech-modifier": (
        "kind: item, id: axe",
        "kind: item, id: saw",
        "technologies[carpentry].modifiers.target.id: unknown items id 'saw'",
    ),
    "item-modifier-id": (
        "kind: need, id: hunger",
        "kind: need, id: thirst",
        "items[axe].modifiers.target.id: unknown needs id 'thirst'",
    ),
    "item-modifier-tag": (
        "kind: need, id: hunger",
        "kind: need, tag: thirsty",
        "items[axe].modifiers.target.tag: no needs have tag 'thirsty'",
    ),
    "trait-modifier-tag": (
        "tag: labour}",
        "tag: magic}",
        "traits[strong].modifiers.target.tag: no actions have tag 'magic'",
    ),
    "trait-modifier-id": (
        "{kind: action, tag: labour}",
        "{kind: need, id: thirst}",
        "traits[strong].modifiers.target.id: unknown needs id 'thirst'",
    ),
}


@pytest.mark.req("REQ-SIM-005")
@pytest.mark.parametrize(("old", "new", "message"), DANGLING.values(), ids=DANGLING.keys())
def test_dangling_references_are_rejected(tmp_path: Path, old: str, new: str, message: str) -> None:
    """AC2: dangling references are rejected, naming pack, definition and field."""
    assert old in BASE
    with pytest.raises(ContentError) as excinfo:
        load_registry([make_pack(tmp_path, "p", BASE.replace(old, new))])
    assert str(excinfo.value) == f"p: {message}"


@pytest.mark.req("REQ-SIM-005")
def test_all_problems_are_reported_together(tmp_path: Path) -> None:
    text = BASE.replace("yields: wood", "yields: x1").replace("cost: {wood: 5}", "cost: {x2: 5}")
    with pytest.raises(ContentError) as excinfo:
        load_registry([make_pack(tmp_path, "p", text)])
    assert str(excinfo.value) == (
        "p: nodes[tree].yields: unknown items id 'x1'\n"
        "p: buildings[hut].cost: unknown items id 'x2'"
    )


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
    assert caplog.messages == [
        "content override: items[wood] from pack 'base' replaced by pack 'mod'"
    ]


@pytest.mark.req("REQ-SIM-005")
def test_at_least_one_pack_is_required() -> None:
    with pytest.raises(ContentError) as excinfo:
        build_registry([])
    assert str(excinfo.value) == "at least one content pack is required"


@pytest.mark.req("REQ-SIM-005")
def test_unknown_section_name(registry: Registry) -> None:
    with pytest.raises(KeyError) as excinfo:
        registry.section("bogus")
    assert excinfo.value.args == ("bogus",)


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
        ContentError,
        match=r"actions\[chop\]\.outputs: must include 'wood', the yield of node 'tree'",
    ):
        load_registry([pack])


@pytest.mark.req("REQ-SIM-010")
def test_an_action_cannot_consume_the_tool_it_requires(tmp_path: Path) -> None:
    """AC1: an input that satisfies a required tool tag would be reserved away; reject it."""
    pack = make_pack(
        tmp_path,
        "pack",
        """
terrains:
  - {id: grass, walkable: true, color: "#8fb35a"}
items:
  - {id: axe, tags: [tool]}
actions:
  - {id: swing, duration_ticks: 5, inputs: {axe: 1}, requires: {tools: [tool]}}
""",
    )
    with pytest.raises(
        ContentError,
        match=r"actions\[swing\]\.inputs: 'axe' is consumed but also satisfies "
        r"the required tool tag 'tool'",
    ):
        load_registry([pack])
