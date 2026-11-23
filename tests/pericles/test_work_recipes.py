from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry, load_registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Craft, Intent, MoveTo, PlaceBuilding, Research, StartAction
from pericles.core.inventory import Tool
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
    """AC1 (SIM-010) / AC3 (SIM-009): a workshop hosts saw: 2 wood → 3 planks in 6 ticks."""
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
            Target("recipe", "saw"),
            "work_speed",
            Op.MUL,
            2.0,
            "technology:lore",
            Scope(villager="c"),
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


@pytest.mark.req("REQ-SIM-010")
def test_a_crafted_tool_is_not_worn_by_its_own_crafting(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC1: crafting an axe leaves the new axe at full durability; no tool_broken."""
    state = world(make_world)
    crafter = state.villagers["b"]
    crafter.knowledge.add("make_axe")
    crafter.inventory.add(econ, "plank", 1)
    crafter.inventory.add(econ, "wood", 1)
    events = run(Engine(econ), state, [Craft("b", "make_axe", "w0")], 4)
    assert of(events, "work_done")[0]["created"] == {"axe": 1}
    assert of(events, "tool_broken") == []
    assert [tool.durability for tool in crafter.inventory.tools] == [3]


EXTRA_PACK = """
items:
  - id: mallet
    weight: 1.0
    durability: 2
    tags: [tool]
    modifiers:
      - {target: {kind: recipe, id: saw}, attribute: work_speed, op: mul, value: 2.0}
  - id: lens
    weight: 1.0
    durability: 2
    tags: [tool]
    modifiers:
      - {target: {kind: building, id: academy}, attribute: research_speed, op: mul, value: 3.0}
"""


@pytest.fixture
def tooled(econ: Registry, tmp_path: Path) -> Registry:
    root = tmp_path / "extra"
    root.mkdir()
    (root / "content.yaml").write_text(EXTRA_PACK, encoding="utf-8")
    from conftest import ECON_PACK

    base = tmp_path / "econ"
    base.mkdir()
    (base / "content.yaml").write_text(ECON_PACK, encoding="utf-8")
    return load_registry([base, root])


@pytest.mark.req("REQ-SIM-010")
def test_recipe_tools_speed_the_work_and_wear_out(tooled: Registry, make_world: MakeWorld) -> None:
    """AC1: a held tool targeting the recipe speeds it and loses one durability on completion."""
    state = world(make_world)
    crafter = state.villagers["a"]
    crafter.inventory.add(tooled, "wood", 2)
    crafter.inventory.add(tooled, "mallet", 1)
    engine = Engine(tooled)
    events = run(engine, state, [Craft("a", "saw", "w0")], 3)
    assert of(events, "work_started")[0]["ticks"] == 3
    assert len(of(events, "work_done")) == 1
    assert crafter.inventory.tools == [Tool("mallet", 1)]


@pytest.mark.req("REQ-SIM-010")
def test_recipe_speed_uses_skill_and_building_scoped_modifiers(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC1: skill and building-scoped modifiers apply to the recipe; speed 0 cannot work."""
    state = world(make_world)
    crafter = state.villagers["a"]
    crafter.inventory.add(econ, "wood", 2)
    crafter.skills["carpentry"] = 100.0  # +0.5 speed: 6 / 1.5 = 4 ticks
    events = Engine(econ).step(state, [Craft("a", "saw", "w0")])[1]
    assert of(events, "work_started")[0]["ticks"] == 4
    state = world(make_world)
    state.villagers["a"].inventory.add(econ, "wood", 2)
    state.modifiers = (
        Modifier(Target("recipe", "saw"), "work_speed", Op.MUL, 2.0, "t", Scope(building="w0")),
        Modifier(Target("recipe", "saw"), "work_speed", Op.MUL, 0.0, "t", Scope(building="w2")),
    )
    events = Engine(econ).step(state, [Craft("a", "saw", "w0")])[1]
    assert of(events, "work_started")[0]["ticks"] == 3


@pytest.mark.req("REQ-SIM-010")
def test_a_stopped_recipe_cannot_work(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: a recipe whose speed resolves to zero is rejected and keeps its inputs."""
    state = world(make_world)
    state.villagers["a"].inventory.add(econ, "wood", 2)
    state.modifiers = (Modifier(Target("recipe", "saw"), "work_speed", Op.MUL, 0.0, "t"),)
    events = Engine(econ).step(state, [Craft("a", "saw", "w0")])[1]
    assert reasons(events) == ["cannot_work"]
    assert state.villagers["a"].inventory.items == {"wood": 2}


@pytest.mark.req("REQ-SIM-010")
def test_recipe_carry_limit_counts_freed_inputs(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: outputs fit when the consumed inputs free enough weight, and not otherwise."""
    state = world(make_world)
    crafter = state.villagers["a"]
    crafter.inventory.add(econ, "wood", 15)  # exactly the 30 carry limit
    events = Engine(econ).step(state, [Craft("a", "saw", "w0")])[1]  # -4 freed, +3 made
    assert [event.kind for event in events] == ["work_started"]


@pytest.mark.req("REQ-SIM-011")
def test_research_tools_speed_the_work_and_wear_out(
    tooled: Registry, make_world: MakeWorld
) -> None:
    """AC1: a held tool targeting the research building speeds research and wears on completion."""
    state = world(make_world)
    scholar = state.villagers["c"]
    scholar.inventory.add(tooled, "plank", 1)
    scholar.inventory.add(tooled, "lens", 1)
    engine = Engine(tooled)
    events = run(engine, state, [Research("c", "lore", "s0")], 2)
    assert of(events, "work_started")[0]["ticks"] == 2
    assert len(of(events, "work_done")) == 1
    assert scholar.inventory.tools == [Tool("lens", 1)]


@pytest.mark.req("REQ-SIM-011")
def test_research_speed_respects_building_scope(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: a modifier scoped to another building does not speed research here."""
    state = world(make_world)
    state.villagers["c"].inventory.add(econ, "plank", 1)
    state.modifiers = (
        Modifier(
            Target("building", "academy"), "research_speed", Op.MUL, 5.0, "t", Scope(building="s0")
        ),
        Modifier(
            Target("building", "academy"), "research_speed", Op.MUL, 0.0, "t", Scope(building="s9")
        ),
    )
    events = Engine(econ).step(state, [Research("c", "lore", "s0")])[1]
    assert of(events, "work_started")[0]["ticks"] == 1


@pytest.mark.req("REQ-SIM-011")
def test_a_lost_race_returns_the_researchers_inputs(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: the loser of a village research race gets the reserved inputs back."""
    state = world(make_world)
    pack_tech = econ.technologies["commons"]
    assert not pack_tech.cost
    state.village_knowledge.add("commons")
    state.villagers["c"].activity = None
    # c started before commons was learned elsewhere: simulate with a reserved bundle
    from pericles.core.inventory import Inventory
    from pericles.core.state import Activity

    reserved = Inventory()
    reserved.add(econ, "plank", 1)
    state.villagers["c"].activity = Activity("research", "commons", "s0", 1.0, 0.9, 1.0, reserved)
    events = Engine(econ).step(state, [])[1]
    assert of(events, "work_interrupted")[0]["reason"] == "already_known"
    assert state.villagers["c"].inventory.items == {"plank": 1}
