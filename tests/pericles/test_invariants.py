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
from pericles.core.invariants import (
    InvariantError,
    check_conservation,
    check_state,
    item_totals,
    ledger,
)
from pericles.core.inventory import EPSILON, Inventory, Tool
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
@pytest.mark.req("REQ-SIM-013")
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
    """AC1 (REQ-SIM-018), REQ-SIM-013 AC1/AC2: negatives, overload and overflow are caught."""
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

REAL = ["a", "b", "c"]
HOTSPOTS = [Coord(1, 0), Coord(2, 1), Coord(3, 0), Coord(0, 1), Coord(4, 1), Coord(2, 3)]
SITES = ["b0", "b1", "w0", "s0", "h0"]
ITEMS = st.sampled_from(["wood", "berries", "plank", "seed", "hammer", "axe"])
QTY = st.integers(0, 5)
ACTIONS = st.sampled_from(
    [
        ("chop", "n0"),
        ("chop", "n0"),
        ("pick", "n1"),
        ("whittle", None),
        ("log", "n0"),
        ("nail", None),
        ("sow", None),
        ("tinker", "w0"),
        ("secret_art", None),
        ("pick", "n0"),
    ]
)


def intents_for(actor: str) -> st.SearchStrategy[Intent]:
    return st.one_of(
        ACTIONS.map(lambda pair: StartAction(actor, pair[0], pair[1])),
        st.builds(MoveTo, st.just(actor), st.sampled_from(HOTSPOTS)),
        st.builds(Wait, st.just(actor)),
        st.builds(
            PlaceBuilding,
            st.just(actor),
            st.sampled_from(["hut", "wall", "workshop", "vault"]),
            st.builds(Coord, st.integers(0, 5), st.integers(0, 3)),
            st.sampled_from(["personal", "shared", "communal"]),
            st.sampled_from([(), ("b",), ("c",)]),
        ),
        st.builds(Deliver, st.just(actor), st.sampled_from(SITES), ITEMS, QTY),
        st.builds(Construct, st.just(actor), st.sampled_from(SITES)),
        st.builds(Deposit, st.just(actor), st.sampled_from(SITES), ITEMS, QTY),
        st.builds(Take, st.just(actor), st.sampled_from(SITES), ITEMS, QTY),
        st.builds(Take, st.just(actor), st.just("h0"), st.just("wood"), st.integers(1, 5)),
        st.builds(Take, st.just(actor), st.just("h0"), st.just("wood"), st.integers(1, 5)),
        st.builds(Take, st.just(actor), st.just("h0"), st.just("wood"), st.integers(1, 5)),
        st.builds(Deposit, st.just(actor), st.just("h0"), ITEMS, st.integers(1, 3)),
        st.builds(
            Craft, st.just(actor), st.sampled_from(["saw", "press", "make_axe"]), st.just("w0")
        ),
        st.builds(Research, st.just(actor), st.sampled_from(["lore", "commons"]), st.just("s0")),
    )


NONE: st.SearchStrategy[Intent | None] = st.none()
BUSY_TICK = st.tuples(
    *[st.one_of(NONE, NONE, intents_for(actor)) for actor in REAL],
    st.one_of(NONE, NONE, NONE, intents_for("z")),  # an occasional unknown actor
).map(lambda picks: [intent for intent in picks if intent is not None])
# Work only completes on ticks nobody interrupts it, so most ticks are idle.
TICKS = st.one_of(st.just([]), st.just([]), st.just([]), st.just([]), BUSY_TICK)
PLAYS = st.tuples(st.booleans(), st.lists(TICKS, min_size=1, max_size=60))

# place, deliver the whole cost, then construct: randomised play continues from there
PREFIX: dict[int, list[Intent]] = {
    0: [PlaceBuilding("c", "hut", Coord(3, 3))],
    2: [Deliver("c", "b0", "wood", 4)],
    3: [Construct("c", "b0")],
}


def rich_village(make_world: MakeWorld, econ: Registry, *, build: bool) -> WorldState:
    """The village with stock for every recipe, and tools that break after a use or two."""
    state = village(make_world, econ)
    for villager in state.villagers.values():
        villager.inventory.add(econ, "wood", 4)
        villager.inventory.add(econ, "plank", 2)
        villager.inventory.add(econ, "berries", 2)
    state.villagers["a"].inventory.tools[0].durability = 1
    state.villagers["c"].inventory.tools.append(Tool("hammer", 1))
    state.villagers["b"].inventory.tools[0].durability = 1
    if build:
        state.villagers["c"].pos = Coord(2, 3)
    return state


def play(
    econ: Registry, make_world: MakeWorld, scenario: tuple[bool, list[list[Intent]]]
) -> Counter[str]:
    """Run one random play in debug mode and count the events it produced."""
    build, ticks = scenario
    engine = Engine(econ, EngineConfig(debug_invariants=True))
    state = rich_village(make_world, econ, build=build)
    seen: Counter[str] = Counter()
    schedule = ([PREFIX.get(i, []) for i in range(4)] if build else []) + ticks
    for intents in schedule:
        seen.update(event.kind for event in engine.step(state, intents)[1])
    for _ in range(30):  # let unfinished work complete
        seen.update(event.kind for event in engine.step(state, [])[1])
    assert check_state(engine.context, state) == []
    return seen


@pytest.mark.req("REQ-SIM-018")
@pytest.mark.req("REQ-SIM-013")
@settings(
    max_examples=200, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(PLAYS)
def test_random_play_keeps_every_invariant(
    econ: Registry, make_world: MakeWorld, scenario: tuple[bool, list[list[Intent]]]
) -> None:
    """AC2 (property): random play in debug mode conserves items and never breaks a state rule."""
    play(econ, make_world, scenario)


@pytest.mark.req("REQ-SIM-018")
def test_random_play_reaches_the_economy(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: a fixed-seed run of the same generator completes work, builds, crafts and researches."""
    seen: Counter[str] = Counter()

    @settings(derandomize=True, max_examples=60, deadline=None, database=None)
    @given(PLAYS)
    def run(scenario: tuple[bool, list[list[Intent]]]) -> None:
        seen.update(play(econ, make_world, scenario))

    run()
    for kind in ("work_done", "building_completed", "tool_broken", "item_taken"):
        assert seen[kind] > 0, (kind, seen)
    assert seen["technology_learned"] > 0, seen


def scripted(tick: int) -> list[Intent]:
    script: dict[int, list[Intent]] = {
        0: [StartAction("a", "chop", "n0"), Research("b", "commons", "s0"), Wait("c")],
        2: [PlaceBuilding("c", "hut", Coord(3, 3))],
        4: [Deliver("c", "b0", "wood", 4)],
        5: [Construct("c", "b0"), Craft("b", "saw", "w0")],
    }
    return script.get(tick, [])


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


# --- checker edge cases (mutation survivors) -----------------------------------------------


def _check(econ: Registry, state: WorldState, config: EngineConfig | None = None) -> list[str]:
    return check_state(Context.build(econ, config or EngineConfig()), state)


@pytest.mark.req("REQ-SIM-018")
def test_ledger_sums_repeated_events() -> None:
    """AC1: every created bundle counts, not only the last."""
    events = [
        Event(0, 0, "work_done", {"created": {"plank": 2}}),
        Event(0, 1, "work_done", {"created": {"plank": 3}}),
    ]
    assert ledger(events) == Counter({"plank": 5})


@pytest.mark.req("REQ-SIM-018")
def test_state_check_reports_every_problem_in_order(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: an inventory and a reserve both broken are both reported, villagers first."""
    state = village(make_world, econ)
    state.villagers["a"].inventory.items["wood"] = -1
    state.villagers["a"].activity = Activity(
        "action", "chop", "n0", 10.0, 0.0, 1.0, Inventory({"wood": 0})
    )
    state.buildings["h0"].storage.items["wood"] = -1
    assert _check(econ, state) == [
        "villager a holds -1 wood",
        "villager a (reserved) holds 0 wood",
        "building h0 holds -1 wood",
    ]


@pytest.mark.req("REQ-SIM-013")
def test_carry_limit_is_inclusive_within_epsilon(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: carried weight exactly at the limit is fine; anything beyond epsilon is not."""
    state = village(make_world, econ)
    weight = max(v.inventory.weight(econ) for v in state.villagers.values())
    assert _check(econ, state, EngineConfig(carry_limit=weight)) == []
    assert _check(econ, state, EngineConfig(carry_limit=weight - 10 * EPSILON)) != []
    edge = weight - EPSILON
    assert edge + EPSILON == weight  # the boundary case is exact in floating point
    assert _check(econ, state, EngineConfig(carry_limit=edge)) == []
    assert _check(econ, state, EngineConfig(carry_limit=weight - 2 * EPSILON)) != []


@pytest.mark.req("REQ-SIM-018")
def test_depleted_node_is_valid_and_a_full_one_too(econ: Registry, make_world: MakeWorld) -> None:
    """AC1: a node may be empty or full."""
    state = village(make_world, econ)
    state.nodes["n0"].stock = 0
    state.nodes["n1"].stock = 4
    assert _check(econ, state) == []


@pytest.mark.req("REQ-SIM-018")
def test_delivered_materials_must_be_positive_and_within_cost(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC1: delivered materials are positive, in the cost, and not above it."""
    state = village(make_world, econ)
    state.buildings["w1"] = Building("w1", "wall", Coord(0, 3), COMMUNAL, {"wood": 1})
    assert _check(econ, state) == []
    state.buildings["w1"].delivered = {"wood": 0}
    assert _check(econ, state) == ["building w1 has 0 wood delivered, cost 1"]
    state.buildings["w1"].delivered = {"plank": 1}
    assert _check(econ, state) == ["building w1 has 1 plank delivered, cost 0"]


@dataclass(frozen=True)
class Conjure2(Intent):
    kind: ClassVar[str] = "conjure2"


def conjure_more(state: WorldState, intent: Intent, sink: EventSink) -> None:
    state.villagers[intent.actor].inventory.items["seed"] = 5
    state.villagers[intent.actor].inventory.items["berries"] = 3


@pytest.mark.req("REQ-SIM-018")
def test_debug_mode_reports_all_problems_in_one_error(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: the error names every broken item, separated by semicolons."""
    engine = Engine(econ, EngineConfig(debug_invariants=True))
    engine.register(Conjure2, conjure_more)
    with pytest.raises(InvariantError) as info:
        engine.step(village(make_world, econ), [Conjure2("a")])
    assert str(info.value) == (
        "tick 0: item 'berries': expected 6, found 7; item 'seed': expected 3, found 7"
    )
