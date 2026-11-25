import math
from collections.abc import Callable

import pytest

from pericles.agents import rules
from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller
from pericles.agents.scripted import ScriptedMind
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

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 10] * 10
CONFIG = AgentConfig(storage_per_capita=0.0)  # these tests are not about storehouses
EAT_AT, SLEEP_AT, COLD_AT = CONFIG.act_at["eat"], CONFIG.act_at["sleep"], CONFIG.act_at["shelter"]


def housed(state: WorldState, *villagers: Villager) -> WorldState:
    """Give the villagers a communal house beside them, so the village builds nothing."""
    state.buildings["h0"] = Building(
        "h0", "house", Coord(0, 1), Ownership("communal"), complete=True
    )
    for villager in villagers:
        villager.home = "h0"
    return state


def decide(
    registry: Registry, state: WorldState, vid: str = "a", memory: dict[str, Memory] | None = None
) -> Decision:
    ctx = Context.build(registry, default_config())
    view = View(
        ctx, state, CONFIG, NodeIndex(state.nodes.values(), CONFIG.index_cell), memory or {}
    )
    return ScriptedMind().decide(view, state.villagers[vid])


def shelter_decision(
    registry: Registry, state: WorldState, vid: str = "a", memory: dict[str, Memory] | None = None
) -> Decision | None:
    """What the shelter rule alone says, so tests tell it apart from the wait fallback."""
    ctx = Context.build(registry, default_config())
    view = View(
        ctx, state, CONFIG, NodeIndex(state.nodes.values(), CONFIG.index_cell), memory or {}
    )
    return rules.shelter(view, state.villagers[vid])


def store(
    state: WorldState, at: Coord, items: dict[str, int], registry: Registry, bid: str = "s0"
) -> Building:
    building = Building(bid, "storehouse", at, Ownership("communal"), complete=True)
    for item, qty in items.items():
        building.storage.add(registry, item, qty)
    state.buildings[bid] = building
    return building


def test_a_hungry_villager_eats_its_own_food_first(
    registry: Registry, make_world: MakeWorld
) -> None:
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
    a = Villager(
        "a",
        "A",
        Coord(0, 0),
        needs={"hunger": EAT_AT - 1, "fatigue": SLEEP_AT - 1, "cold": COLD_AT - 1},
    )
    assert decide(registry, housed(make_world(ROWS, [a]), a)).intent == Wait("a")


def test_tired_villagers_sleep_at_home_if_they_can(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: sleep when tired; walk home first unless exhausted."""
    a = Villager("a", "A", Coord(0, 0), home="h0", needs={"fatigue": SLEEP_AT})
    state = make_world(ROWS, [a])
    state.buildings["h0"] = Building(
        "h0", "house", Coord(6, 6), Ownership("communal"), complete=True
    )
    decision = decide(registry, state)
    assert isinstance(decision.intent, MoveTo) and decision.target == "h0"
    a.needs["fatigue"] = CONFIG.urgent_at["sleep"]
    assert decide(registry, state).intent == Sleep("a")
    a.needs["fatigue"] = SLEEP_AT
    a.home = None
    assert decide(registry, state).intent == Sleep("a")


def test_cold_villagers_go_home_and_stay_until_warm(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: shelter at home when cold, staying until below warm_until."""
    a = Villager("a", "A", Coord(0, 0), home="h0", needs={"cold": COLD_AT})
    state = make_world(ROWS, [a])
    state.buildings["h0"] = Building(
        "h0", "house", Coord(6, 6), Ownership("communal"), complete=True
    )
    decision = decide(registry, state)
    assert isinstance(decision.intent, MoveTo) and decision.target == "h0"
    a.pos = Coord(5, 6)
    assert decide(registry, state).intent == Wait("a")
    a.needs["cold"] = CONFIG.warm_until + 1
    assert shelter_decision(registry, state) == Decision(Wait("a"))  # shelter, not the fallback
    a.needs["cold"] = CONFIG.warm_until
    assert shelter_decision(registry, state) is None  # warm: nothing else to do, but not for it
    a.home = None
    a.needs["cold"] = COLD_AT
    assert shelter_decision(registry, state) is None


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


def test_gathering_prefers_the_most_skilled_job(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: of the foods it can gather, a hungry villager takes the job it is best at."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": EAT_AT}, skills={"fishing": 80.0})
    nodes = [Node("n0", "berry_bush", Coord(2, 0), 5), Node("n1", "fish_shoal", Coord(0, 5), 5)]
    decision = decide(registry, make_world(ROWS, [a], nodes))
    assert (decision.target, decision.job) == ("n1", "catch_fish")
    b = Villager("a", "A", Coord(0, 0), needs={"hunger": EAT_AT}, skills={"foraging": 80.0})
    decision = decide(registry, make_world(ROWS, [b], nodes))
    assert (decision.target, decision.job) == ("n0", "gather_berries")


def test_children_only_take_light_work(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a hungry child takes only child-tagged jobs, however skilled it is elsewhere."""
    kid = Villager(
        "a", "A", Coord(0, 0), needs={"hunger": EAT_AT}, skills={"fishing": 90.0}, adult=False
    )
    nodes = [Node("n0", "berry_bush", Coord(2, 0), 5), Node("n1", "fish_shoal", Coord(0, 2), 5)]
    decision = decide(registry, make_world(ROWS, [kid], nodes))
    assert (decision.target, decision.job) == ("n0", "gather_berries")


def test_no_gathering_without_room_to_carry(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a villager whose hands are full of other goods does not walk to a node it cannot use."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": EAT_AT})
    a.inventory.add(registry, "wood", 15)
    state = housed(make_world(ROWS, [a], [Node("n0", "berry_bush", Coord(4, 0), 5)]), a)
    avoid_house = {
        "a": Memory(avoid={"h0": state.tick + 50})
    }  # keep the wood out of the house store
    assert decide(registry, state, memory=avoid_house).intent == Wait("a")


def test_an_avoided_or_empty_node_is_not_a_target(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: nodes that failed recently, or are exhausted, are passed over."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": EAT_AT})
    nodes = [Node("n0", "berry_bush", Coord(2, 0), 5), Node("n1", "berry_bush", Coord(0, 6), 0)]
    state = housed(make_world(ROWS, [a], nodes), a)
    avoid = {"a": Memory(avoid={"n0": state.tick + 50})}
    assert decide(registry, state, memory=avoid).intent == Wait("a")


def test_a_hungry_villager_takes_only_what_fits_from_a_store(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: fetching from a store takes at most what is there."""
    a = Villager("a", "A", Coord(5, 6), needs={"hunger": EAT_AT})
    state = make_world(ROWS, [a])
    store(state, Coord(6, 6), {"fish": 2}, registry)
    assert decide(registry, state).intent == Take("a", "s0", "fish", 2)


def test_a_warm_villager_at_home_does_not_stay(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: shelter passes for a villager already at home who is not cold."""
    a = Villager("a", "A", Coord(6, 6), home="h0", needs={"cold": CONFIG.warm_until})
    state = make_world(ROWS, [a])
    state.buildings["h0"] = Building(
        "h0", "house", Coord(6, 6), Ownership("communal"), complete=True
    )
    assert shelter_decision(registry, state) is None
    a.needs["cold"] = CONFIG.warm_until + 1
    assert shelter_decision(registry, state) == Decision(Wait("a"))
    a.needs["cold"] = CONFIG.warm_until
    a.needs["fatigue"] = SLEEP_AT
    assert decide(registry, state).intent == Sleep("a")
