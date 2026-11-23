from collections.abc import Callable, Sequence
from pathlib import Path

import pytest
from conftest import ECON_PACK

from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry, load_registry
from pericles.core.context import Context, knows, reject
from pericles.core.engine import Engine
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo, StartAction
from pericles.core.inventory import Tool
from pericles.core.modifiers import Modifier, Op, Scope, Target
from pericles.core.nodes import Node
from pericles.core.state import Activity, Villager, WorldState
from pericles.core.work import EPSILON, start_work, used_tools

MakeWorld = Callable[..., WorldState]
Setup = Callable[[WorldState, Registry], None]
ROWS = ("..T.T", ".....")


def world(make_world: MakeWorld, **fields: object) -> WorldState:
    """Ana at (1,0); tree n0, bush n1 adjacent, tree n2 far; workshops b0 near, b1 site, b2 far."""
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
    ("carve", None, nothing, "skill_too_low"),
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
    """AC1 (SIM-008) / AC2 (SIM-010): traits and held tools divide the duration by the speed."""
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
    assert dict(events[0].data) == {"actor": "a", "at": [0, 0]}
    villager = state.villagers["a"]
    assert (villager.path, villager.move_progress, villager.pos) == ([], 0.0, Coord(0, 0))


@pytest.mark.req("REQ-SIM-014")
def test_practice_raises_the_skill_up_to_the_maximum(econ: Registry, make_world: MakeWorld) -> None:
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
    """AC2: the skill level adds skill_speed_per_level * level to matching actions only."""
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


EXTRA_PACK = """
items:
  - id: gloves
    weight: 0.5
    durability: 4
    tags: [tool]
    modifiers:
      - {target: {kind: action, tag: labour}, attribute: work_speed, op: add, value: 1.0}
  - id: spike
    weight: 0.5
    durability: 1
    tags: [tool]
    modifiers:
      - {target: {kind: action, id: forge}, attribute: work_speed, op: mul, value: 2.0}
actions:
  - {id: forge, duration_ticks: 2, outputs: {spike: 1}}
  - id: practise
    duration_ticks: 4
    outputs: {plank: 1}
    requires: {skill: carving, min_skill: 0.5}
  - {id: fell, duration_ticks: 10, inputs: {seed: 1}, outputs: {wood: 2}, location: {node: tree}}
"""


@pytest.fixture
def extra(tmp_path: Path) -> Registry:
    root = tmp_path / "extra"
    root.mkdir()
    (root / "content.yaml").write_text(EXTRA_PACK, encoding="utf-8")
    base = tmp_path / "base"
    base.mkdir()
    (base / "content.yaml").write_text(ECON_PACK, encoding="utf-8")
    return load_registry([base, root])


def test_used_tools_include_each_item_once_and_match_by_tag(extra: Registry) -> None:
    """Tools whose modifier targets the work by id or tag are used, one instance per item."""
    state_villager = Villager("a", "Ana", Coord(0, 0))
    state_villager.inventory.add_tools([Tool("axe", 3), Tool("axe", 2), Tool("gloves", 4)])
    ctx = Engine(extra).context
    chop = used_tools(ctx, state_villager, "action", "chop", ("labour",), [])
    assert chop == [Tool("axe", 2), Tool("gloves", 4)]
    assert used_tools(ctx, state_villager, "action", "whittle", ("craft",), []) == []


@pytest.mark.req("REQ-SIM-008")
def test_an_untrained_villager_is_below_a_fractional_minimum_skill(
    extra: Registry, make_world: MakeWorld
) -> None:
    """AC2: an untrained villager (level 0) is rejected by a fractional minimum skill."""
    state = world(make_world)
    events = Engine(extra).step(state, [StartAction("a", "practise")])[1]
    assert of(events, "intent_rejected")[0]["reason"] == "skill_too_low"


def test_the_inputs_freed_make_room_for_the_outputs(econ: Registry, make_world: MakeWorld) -> None:
    """A full inventory may start work whose inputs weigh at least as much as its outputs."""
    state = world(make_world)
    give(("hammer", 1), ("wood", 15))(state, econ)
    events = Engine(econ).step(state, [StartAction("a", "whittle")])[1]
    assert [event.kind for event in events] == ["work_started"]


def test_secondary_outputs_do_not_draw_on_the_node(extra: Registry, make_world: MakeWorld) -> None:
    """Only the yield item is limited by, and taken from, the node's stock."""
    state = world(make_world)
    state.nodes["n0"].stock = 1
    events = run(Engine(extra), state, [StartAction("a", "log", "n0")], 2)
    assert of(events, "work_done")[0]["created"] == {"plank": 10, "wood": 1}
    assert state.nodes["n0"].stock == 0


def test_a_depleted_node_interrupt_returns_the_inputs(
    extra: Registry, make_world: MakeWorld
) -> None:
    """An action that finds its node empty is interrupted and gets its reserved inputs back."""
    villagers = [Villager("a", "Ana", Coord(1, 0)), Villager("b", "Bo", Coord(3, 0))]
    state = make_world(ROWS, villagers, [Node("n0", "tree", Coord(2, 0), 1)])
    for villager in villagers:
        villager.inventory.add(extra, "seed", 1)
    run(Engine(extra), state, [StartAction("a", "fell", "n0"), StartAction("b", "fell", "n0")], 10)
    assert state.villagers["b"].inventory.items == {"seed": 1}
    assert state.villagers["a"].inventory.items == {"wood": 1}


def scoped(scope: Scope, target: Target | None = None) -> Setup:
    def setup(state: WorldState, registry: Registry) -> None:
        state.modifiers = (
            Modifier(target or Target("action", "tinker"), "work_speed", Op.ADD, 1.0, "t", scope),
        )

    return setup


@pytest.mark.parametrize(
    ("scope", "ticks"),
    [
        (Scope(building="b0"), 1),
        (Scope(building="b9"), 2),
        (Scope(villager="a"), 1),
        (Scope(villager="b"), 2),
        (Scope(until_tick=5), 1),
        (Scope(until_tick=0), 2),
    ],
)
def test_modifier_scopes_see_the_villager_building_and_tick(
    econ: Registry, make_world: MakeWorld, scope: Scope, ticks: int
) -> None:
    """Work speed resolves modifiers for this villager, this building and the current tick."""
    state = world(make_world)
    scoped(scope)(state, econ)
    events = Engine(econ).step(state, [StartAction("a", "tinker", "b0")])[1]
    assert of(events, "work_started")[0]["ticks"] == ticks


def test_start_work_counts_only_the_remaining_work(econ: Registry, make_world: MakeWorld) -> None:
    """Resuming with progress already done needs only the remainder (work - done) / speed."""
    state = world(make_world)
    sink = EventSink(0)
    intent = StartAction("a", "chop", "n0")
    start_work(
        Engine(econ).context,
        state.villagers["a"],
        intent,
        sink,
        kind="action",
        ident="chop",
        target="n0",
        work=10,
        speed=1.0,
        inputs={},
        done=3.0,
    )
    assert of(sink.events, "work_started")[0]["ticks"] == 7


def test_idle_villagers_do_not_block_working_ones(econ: Registry, make_world: MakeWorld) -> None:
    """Work progresses for every villager that has an activity, whoever precedes them."""
    villagers = [Villager("a", "Ana", Coord(0, 0)), Villager("b", "Bo", Coord(1, 0))]
    state = make_world(ROWS, villagers, [Node("n0", "tree", Coord(2, 0), 6)])
    engine = Engine(econ)
    engine.step(state, [StartAction("b", "chop", "n0")])
    activity = state.villagers["b"].activity
    assert activity is not None and activity.done == 1.0


def test_work_completes_within_epsilon_of_the_target(econ: Registry, make_world: MakeWorld) -> None:
    """A tick that brings the progress to within EPSILON of the work completes it."""
    state = world(make_world)
    state.villagers["a"].activity = Activity("action", "pick", "n1", 1.0, 0.0, 1.0 - EPSILON)
    events = Engine(econ).step(state, [])[1]
    assert [event.kind for event in events] == ["work_done"]


def test_context_locks_what_a_technology_unlocks(econ: Registry, make_world: MakeWorld) -> None:
    """Recipes and buildings that a technology unlocks need knowledge, personal or village-wide."""
    ctx = Context.build(econ, EngineConfig())
    assert ctx.locked == {"make_axe", "vault"}
    state = world(make_world)
    villager = state.villagers["a"]
    assert ctx.available(state, villager, "saw")
    assert not ctx.available(state, villager, "make_axe")
    villager.knowledge.add("make_axe")
    assert ctx.available(state, villager, "make_axe")
    assert not ctx.available(state, villager, "vault")
    state.village_knowledge.add("vault")
    assert ctx.available(state, villager, "vault")
    assert knows(state, villager, "vault") and not knows(state, villager, "saw")


def test_reject_names_the_intent_kind() -> None:
    """Rejections report the actor, the intent kind and the reason."""
    sink = EventSink(0)
    reject(sink, StartAction("a", "x"), "why")
    assert of(sink.events, "intent_rejected") == [
        {"actor": "a", "intent": "start_action", "reason": "why"}
    ]


@pytest.mark.req("REQ-SIM-010")
def test_a_tool_the_action_produces_is_not_worn_by_it(
    extra: Registry, make_world: MakeWorld
) -> None:
    """AC2: wear applies to tools used by the work, not to a tool it has just created."""
    state = world(make_world)
    events = run(Engine(extra), state, [StartAction("a", "forge")], 2)
    assert of(events, "work_done")[0]["created"] == {"spike": 1}
    assert of(events, "tool_broken") == []
    assert state.villagers["a"].inventory.tools == [Tool("spike", 1)]
