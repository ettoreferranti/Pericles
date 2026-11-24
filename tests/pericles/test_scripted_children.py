from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.scripted import ChildMind, ScriptedMind, scripted_controller
from pericles.agents.view import Decision, Memory, NodeIndex, View
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


def decide(
    registry: Registry, state: WorldState, vid: str = "k", memory: dict[str, Memory] | None = None
) -> Decision:
    ctx = Context.build(registry, default_config())
    view = View(
        ctx, state, CONFIG, NodeIndex(state.nodes.values(), CONFIG.index_cell), memory or {}
    )
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
def test_a_child_forages_only_light_work_near_the_parent(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: light gathering, close to a parent; heavy work is never chosen."""
    near_bush = Node("b0", "berry_bush", Coord(3, 3), 20)
    tree = Node("t0", "tree", Coord(6, 2), 10)
    state = make_world(ROWS, family(Coord(3, 2), needs=dict(HUNGRY)), [near_bush, tree])
    assert decide(registry, state).intent == StartAction("k", "gather_berries", "b0")
    far = make_world(
        ROWS,
        family(Coord(5, 2), needs=dict(HUNGRY)),
        [Node("b1", "berry_bush", Coord(2, 9), 20), tree],
    )
    assert decide(registry, far).intent == Wait("k")


@pytest.mark.req("REQ-SIM-016")
def test_a_tired_child_sleeps(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: children sleep when tired, like adults."""
    state = make_world(ROWS, family(Coord(3, 2), needs={"fatigue": CONFIG.act_at["sleep"]}))
    assert decide(registry, state).intent == Sleep("k")


@pytest.mark.req("REQ-SIM-016", "REQ-AGT-008")
def test_a_family_runs_without_child_rejections(registry: Registry, make_world: MakeWorld) -> None:
    """SIM-016 AC1 / AGT-008 AC2: under the scripted controller a child does only what it may."""
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
