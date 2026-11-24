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
from pericles.core.intents import Deliver, Deposit, MoveTo, Wait
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 6 + "T" * 6] * 12
CONFIG = AgentConfig()


def view_of(
    registry: Registry, state: WorldState, memory: dict[str, Memory] | None = None, **cfg: object
) -> View:
    ctx = Context.build(registry, default_config())
    config = AgentConfig(**cfg)  # type: ignore[arg-type]
    return View(
        ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), memory or {}
    )


SITE_AT, STORE_AT = Coord(1, 8), Coord(1, 1)


def site(state: WorldState, kind: str = "house", at: Coord = SITE_AT) -> Building:
    state.buildings["s1"] = Building("s1", kind, at, Ownership("communal"))
    return state.buildings["s1"]


def storehouse(state: WorldState, at: Coord = STORE_AT) -> Building:
    state.buildings["st"] = Building("st", "storehouse", at, Ownership("communal"), complete=True)
    return state.buildings["st"]


TREES = [Node(f"t{i}", "tree", Coord(7 + i, 2), 10) for i in range(3)]
BUSHES = [Node(f"b{i}", "berry_bush", Coord(2 + i, 5), 20) for i in range(2)]


def test_demand_measures_food_shortfall_and_needed_materials(
    registry: Registry, make_world: MakeWorld
) -> None:
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


def test_work_skips_full_hands_avoided_and_depleted_nodes(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a villager never heads for a node it cannot use or an output it cannot carry."""
    a = Villager("a", "A", Coord(6, 2), skills={"woodcutting": 60.0})
    trees = [
        Node("t0", "tree", Coord(7, 2), 0),
        Node("t1", "tree", Coord(8, 2), 10),
        Node("t2", "tree", Coord(11, 2), 10),
    ]
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
    assert ScriptedMind().decide(
        view_of(registry, state, food_reserve_per_capita=10.0), a
    ).intent == Wait("a")


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
    assert ScriptedMind().decide(view_of(registry, state), a).intent == Deliver(
        "a", "s1", "wood", need
    )


def test_deposit_unloads_surplus_but_keeps_food_tools_and_site_needs(
    registry: Registry, make_world: MakeWorld
) -> None:
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
    villagers = [
        Villager(f"v{i}", "V", Coord(5, 4 + i), skills={"woodcutting": 50.0, "masonry": 50.0})
        for i in range(3)
    ]
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
