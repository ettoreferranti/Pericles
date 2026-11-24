from collections.abc import Callable

import pytest

from pericles.agents import rules
from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller
from pericles.agents.scripted import ScriptedMind
from pericles.agents.view import CONSTRUCT, Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership, footprint
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import AcceptCouple, Construct, PlaceBuilding, ProposeCouple, SetHome
from pericles.core.nodes import Node
from pericles.core.state import Proposal, Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 16] * 16


def view_of(
    registry: Registry, state: WorldState, memory: dict[str, Memory] | None = None, **cfg: object
) -> View:
    ctx = Context.build(registry, default_config())
    config = AgentConfig(**cfg)  # type: ignore[arg-type]
    return View(
        ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), memory or {}
    )


def supplied_site(state: WorldState, registry: Registry, at: Coord | None = None) -> Building:
    at = at or Coord(2, 2)
    building = Building(
        "s1", "house", at, Ownership("communal"), delivered=dict(registry.buildings["house"].cost)
    )
    state.buildings["s1"] = building
    return building


def house(state: WorldState, bid: str, at: Coord) -> Building:
    state.buildings[bid] = Building(bid, "house", at, Ownership("communal"), complete=True)
    return state.buildings[bid]


def test_build_a_supplied_site_within_the_builder_limit(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: once a site has its materials, villagers build it, up to max_builders at a time."""
    a = Villager("a", "A", Coord(3, 4), home="h0")
    state = make_world(ROWS, [a])
    house(state, "h0", Coord(10, 10))
    supplied_site(state, registry)
    decision = rules.build(view_of(registry, state, storage_per_capita=0.0), a)
    assert decision is not None
    assert (decision.intent, decision.target, decision.job) == (
        Construct("a", "s1"),
        "s1",
        CONSTRUCT,
    )
    busy = {f"o{i}": Memory(job=CONSTRUCT, target="s1") for i in range(3)}
    for vid in busy:
        state.villagers[vid] = Villager(vid, "O", Coord(0, 0), home="h0")
    assert (
        rules.build(view_of(registry, state, busy, storage_per_capita=0.0, max_builders=3), a)
        is None
    )


def test_the_homeless_place_one_communal_house_at_a_time(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: with too few beds, one villager claims and places a communal house."""
    a, b = Villager("a", "A", Coord(8, 8)), Villager("b", "B", Coord(8, 8))
    state = make_world(ROWS, [a, b])
    view = view_of(registry, state, storage_per_capita=0.0)
    decision = rules.build(view, a)
    assert decision is not None and decision.target == "place:house"
    origin = view.free_origin("house")
    assert origin is not None
    walk = view.go(a, footprint(origin, registry.buildings["house"].footprint))
    assert decision.intent == (walk or PlaceBuilding("a", "house", origin, ownership="communal"))
    claimed = {"b": Memory(target="place:house")}
    assert rules.build(view_of(registry, state, claimed, storage_per_capita=0.0), a) is None
    avoided = {"a": Memory(avoid={"place:house": 99})}
    assert rules.build(view_of(registry, state, avoided, storage_per_capita=0.0), a) is None
    house(state, "h0", Coord(1, 1))
    assert rules.build(view_of(registry, state, storage_per_capita=0.0), a) is None


def test_a_storehouse_when_storage_runs_short(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: once housed, the village builds communal storage for its population."""
    villagers = [Villager(f"v{i}", "V", Coord(8, 8), home="h0") for i in range(4)]
    state = make_world(ROWS, villagers)
    house(state, "h0", Coord(1, 1))
    decision = rules.build(view_of(registry, state, storage_per_capita=15.0), villagers[0])
    assert decision is not None and decision.target == "place:storehouse"
    assert rules.build(view_of(registry, state, storage_per_capita=5.0), villagers[0]) is None


def test_homes_go_to_the_homeless_and_reunite_partners(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: homeless villagers move in; partners living apart move together."""
    a = Villager("a", "A", Coord(0, 0), sex="female", partner="b")
    b = Villager("b", "B", Coord(0, 0), sex="male", partner="a", home="h1")
    c = Villager("c", "C", Coord(0, 0), home="h0")
    state = make_world(ROWS, [a, b, c])
    house(state, "h0", Coord(1, 1))
    house(state, "h1", Coord(9, 9))
    assert rules.home(view_of(registry, state), a).intent == SetHome("a", "h1")  # type: ignore[union-attr]
    a.home = "h0"
    assert rules.home(view_of(registry, state), a).intent == SetHome("a", "h1")  # type: ignore[union-attr]
    assert rules.home(view_of(registry, state), c) is None
    a.home = "h1"
    assert rules.home(view_of(registry, state), a) is None


def test_couples_accept_then_propose_to_compatible_adults(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: unpartnered adults accept proposals made to them, or propose to the nearest match."""
    a = Villager("a", "A", Coord(0, 0), sex="female")
    m1 = Villager("m1", "M", Coord(5, 0), sex="male")
    m2 = Villager("m2", "M", Coord(2, 0), sex="male")
    f2 = Villager("f2", "F", Coord(1, 0), sex="female")
    kid = Villager("k", "K", Coord(1, 1), sex="male", adult=False)
    state = make_world(ROWS, [a, m1, m2, f2, kid])
    assert rules.couple(view_of(registry, state), a).intent == ProposeCouple("a", "m2")  # type: ignore[union-attr]
    state.proposals["m1"] = Proposal("a", 50)
    assert rules.couple(view_of(registry, state), a).intent == AcceptCouple("a", "m1")  # type: ignore[union-attr]
    state.tick = 50
    assert rules.couple(view_of(registry, state), a).intent == ProposeCouple("a", "m2")  # type: ignore[union-attr]
    state.proposals = {"a": Proposal("m2", 99)}
    assert rules.couple(view_of(registry, state), a) is None
    assert rules.couple(view_of(registry, state), f2).intent == ProposeCouple("f2", "m1")  # type: ignore[union-attr]
    state.proposals = {}
    assert rules.couple(view_of(registry, state, couples=False), a) is None
    assert rules.couple(view_of(registry, state), kid) is None
    assert not rules.compatible(view_of(registry, state), a, f2)


def test_scripted_villagers_house_themselves_and_pair_up(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: homeless scripted villagers build a house, move in and form couples, all unaided."""
    rows = ["......" + "T" * 10] * 8 + ["." * 16] * 4 + ["RRRRRR" + "." * 10] * 4
    trees = [Node(f"t{i}", "tree", Coord(7 + i, 3), 10) for i in range(5)]
    rocks = [Node("r0", "boulder", Coord(2, 13), 30), Node("r1", "boulder", Coord(4, 13), 30)]
    bushes = [Node(f"b{i}", "berry_bush", Coord(9 + i, 10), 20) for i in range(3)]
    people = [
        Villager(
            vid, vid.upper(), Coord(6, 9), sex=sex, skills={"woodcutting": 30.0, "masonry": 30.0}
        )
        for vid, sex in [("a", "female"), ("b", "male"), ("c", "female"), ("d", "male")]
    ]
    state = make_world(rows, people, [*trees, *rocks, *bushes])
    engine = Engine(registry, default_config(debug_invariants=True))
    ctl = Controller(
        engine.context, AgentConfig(storage_per_capita=0.0), ScriptedMind(), ScriptedMind()
    )
    for _ in range(6000):
        state, events = engine.step(state, ctl.intents(state))
        ctl.observe(state, events)
        if all(v.home is not None for v in state.villagers.values()) and all(
            v.partner for v in state.villagers.values()
        ):
            break
    assert len(state.villagers) == 4
    assert any(b.complete and b.kind == "house" for b in state.buildings.values())
    assert all(v.home is not None for v in state.villagers.values())
    assert all(v.partner is not None for v in state.villagers.values())
