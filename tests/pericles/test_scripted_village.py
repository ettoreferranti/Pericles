from collections.abc import Callable
from dataclasses import replace

import pytest

from pericles.agents import rules
from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller
from pericles.agents.scripted import ScriptedMind
from pericles.agents.view import CONSTRUCT, Memory, NodeIndex, View, beds_needed
from pericles.core.buildings import Building, Ownership, footprint
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import AcceptCouple, Construct, PlaceBuilding, ProposeCouple, SetHome
from pericles.core.nodes import Node
from pericles.core.state import Pregnancy, Proposal, Villager, WorldState
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
    # both stand by h1, so the pair's choice (summed distance) is h1 once a has a home too
    a = Villager("a", "A", Coord(9, 8), sex="female", partner="b")
    b = Villager("b", "B", Coord(9, 8), sex="male", partner="a", home="h1")
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


def test_a_single_homeless_villager_or_a_small_storage_gap_is_enough(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a shortfall of just one bed, or less than one unit of storage, still gets a building."""
    a = Villager("a", "A", Coord(8, 8))
    state = make_world(ROWS, [a])
    decision = rules.build(view_of(registry, state, storage_per_capita=0.0), a)
    assert decision is not None and decision.target == "place:house"
    a.home = "h0"
    house(state, "h0", Coord(1, 1))
    wanted = registry.buildings["house"].storage + 0.5  # leaves half a unit uncovered
    decision = rules.build(view_of(registry, state, storage_per_capita=wanted), a)
    assert decision is not None and decision.target == "place:storehouse"


def test_own_claim_and_own_work_do_not_count_against_the_builder(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a villager's own placing claim or construction does not block it from continuing."""
    a = Villager("a", "A", Coord(8, 8))
    state = make_world(ROWS, [a])
    own = {"a": Memory(target="place:house")}
    decision = rules.build(view_of(registry, state, own, storage_per_capita=0.0), a)
    assert decision is not None and decision.target == "place:house"
    b = Villager("b", "B", Coord(3, 4), home="h0")
    state = make_world(ROWS, [b])
    house(state, "h0", Coord(10, 10))
    supplied_site(state, registry)
    mine = {"b": Memory(job=CONSTRUCT, target="s1")}
    view = view_of(registry, state, mine, storage_per_capita=0.0, max_builders=1)
    decision = rules.build(view, b)
    assert decision is not None and decision.intent == Construct("b", "s1")


def test_build_skips_unsupplied_and_full_sites_for_a_later_one(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: an unsupplied or fully staffed site does not stop a villager from building another."""
    a = Villager("a", "A", Coord(3, 4), home="h0")
    state = make_world(ROWS, [a])
    house(state, "h0", Coord(10, 10))
    state.buildings["s0"] = Building("s0", "house", Coord(6, 6), Ownership("communal"))
    supplied_site(state, registry)
    decision = rules.build(view_of(registry, state, storage_per_capita=0.0), a)
    assert decision is not None and decision.target == "s1"
    state.buildings["s0"].delivered = dict(registry.buildings["house"].cost)
    busy = {f"o{i}": Memory(job=CONSTRUCT, target="s0") for i in range(3)}
    for vid in busy:
        state.villagers[vid] = Villager(vid, "O", Coord(0, 0), home="h0")
    view = view_of(registry, state, busy, storage_per_capita=0.0, max_builders=3)
    decision = rules.build(view, a)
    assert decision is not None and decision.target == "s1"


def test_builders_walk_to_sites_and_spots_before_working(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a distant villager walks to the site or the chosen spot; a near one acts."""
    a = Villager("a", "A", Coord(15, 15), home="h0")
    state = make_world(ROWS, [a])
    house(state, "h0", Coord(10, 10))
    site = supplied_site(state, registry)
    view = view_of(registry, state, storage_per_capita=0.0)
    decision = rules.build(view, a)
    assert decision is not None
    assert decision.intent == view.go(a, view.tiles(site)) and decision.intent is not None
    assert (decision.target, decision.job) == ("s1", CONSTRUCT)
    state = make_world(ROWS, [Villager("a", "A", Coord(15, 15))])
    a = state.villagers["a"]
    view = view_of(registry, state, storage_per_capita=0.0)
    origin = view.free_origin("house")
    assert origin is not None
    decision = rules.build(view, a)
    assert decision is not None and decision.target == "place:house" and decision.job is None
    walk = view.go(a, footprint(origin, registry.buildings["house"].footprint))
    assert walk is not None and decision.intent == walk
    a.pos = origin
    decision = rules.build(view_of(registry, state, storage_per_capita=0.0), a)
    assert decision is not None
    assert decision.intent == PlaceBuilding("a", "house", origin, ownership="communal")


def test_no_free_spot_means_nothing_to_place(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a wanted building with nowhere to stand is not placed."""
    a = Villager("a", "A", Coord(8, 8))
    state = make_world(ROWS, [a])
    start = state.tilemap.start()
    state.nodes["blocker"] = Node("blocker", "tree", start, 10)
    view = view_of(registry, state, storage_per_capita=0.0, site_search_radius=0)
    assert view.free_origin("house") is None
    assert rules.build(view, a) is None


def test_a_housed_villager_stays_put_and_homes_carry_their_target(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a housed villager keeps its home though another is nearer; moves name the house."""
    c = Villager("c", "C", Coord(8, 8), home="h0")
    state = make_world(ROWS, [c])
    house(state, "h0", Coord(1, 1))
    house(state, "h1", Coord(9, 9))
    assert rules.home(view_of(registry, state), c) is None
    c.home = None
    decision = rules.home(view_of(registry, state), c)
    assert decision is not None
    assert (decision.intent, decision.target) == (SetHome("c", "h1"), "h1")


def test_compatible_needs_two_known_sexes(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a pair is compatible only when both sexes are known and differ."""
    a = Villager("a", "A", Coord(0, 0), sex="female")
    m = Villager("m", "M", Coord(1, 0), sex="male")
    unknown = Villager("u", "U", Coord(1, 1), sex=None)
    view = view_of(registry, make_world(ROWS, [a, m, unknown]))
    assert rules.compatible(view, a, m)
    assert not rules.compatible(view, a, None)
    assert not rules.compatible(view, a, unknown)
    assert not rules.compatible(view, unknown, m)
    assert not rules.compatible(view, unknown, unknown)


def test_couple_decisions_name_their_target_and_respect_avoidance(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: accepting or proposing targets the partner; avoided villagers are passed over."""
    a = Villager("a", "A", Coord(0, 0), sex="female")
    m1 = Villager("m1", "M", Coord(5, 0), sex="male")
    m2 = Villager("m2", "M", Coord(2, 0), sex="male")
    state = make_world(ROWS, [a, m1, m2])
    decision = rules.couple(view_of(registry, state), a)
    assert decision is not None
    assert (decision.intent, decision.target) == (ProposeCouple("a", "m2"), "m2")
    avoid_m2 = {"a": Memory(avoid={"m2": 99})}
    decision = rules.couple(view_of(registry, state, avoid_m2), a)
    assert decision is not None and decision.intent == ProposeCouple("a", "m1")
    assert decision.target == "m1"
    state.proposals["m1"] = Proposal("a", 50)
    decision = rules.couple(view_of(registry, state), a)
    assert decision is not None
    assert (decision.intent, decision.target) == (AcceptCouple("a", "m1"), "m1")
    avoid_m1 = {"a": Memory(avoid={"m1": 99})}
    decision = rules.couple(view_of(registry, state, avoid_m1), a)
    assert decision is not None and decision.intent == ProposeCouple("a", "m2")


def test_a_pregnant_homeless_villager_needs_two_beds(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: one free bed is not enough for a homeless villager who is expecting."""
    a = Villager("a", "A", Coord(8, 8), sex="female", pregnancy=Pregnancy("b", 500))
    state = make_world(ROWS, [a])
    free_beds = registry.buildings["house"].housing
    for i in range(free_beds - 1):  # fill all but one bed of a communal house
        state.villagers[f"r{i}"] = Villager(f"r{i}", "R", Coord(0, 0), home="h0")
    house(state, "h0", Coord(1, 1))
    view = view_of(registry, state, storage_per_capita=0.0)
    assert view.housing_shortfall() == 1
    decision = rules.build(view, a)
    assert decision is not None and decision.target == "place:house"


def test_houses_come_before_storehouses(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: while housing is short or a house is unfinished, no storehouse is wanted."""
    a, b = Villager("a", "A", Coord(8, 8)), Villager("b", "B", Coord(8, 8))
    state = make_world(ROWS, [a, b])
    taken = {"b": Memory(target="place:house")}
    view = view_of(registry, state, taken, storage_per_capita=15.0)
    assert view.housing_shortfall() > 0 and view.storage_shortfall() > 0
    assert rules.wanted_building(view, a) is None
    avoided = {"a": Memory(avoid={"place:house": 99})}
    assert (
        rules.wanted_building(view_of(registry, state, avoided, storage_per_capita=15.0), a) is None
    )
    # housed, but a house is still going up: still no storehouse
    a.home, b.home = "h0", "h0"
    house(state, "h0", Coord(1, 1))
    state.buildings["s0"] = Building("s0", "house", Coord(12, 12), Ownership("communal"))
    view = view_of(registry, state, storage_per_capita=15.0)
    assert view.housing_shortfall() <= 0
    assert rules.wanted_building(view, a) is None
    del state.buildings["s0"]
    assert (
        rules.wanted_building(view_of(registry, state, storage_per_capita=15.0), a) == "storehouse"
    )


def test_beds_needed_counts_a_child_on_the_way() -> None:
    """AC1: a villager needs one bed, two when expecting."""
    assert beds_needed(Villager("a", "A", Coord(0, 0))) == 1
    assert beds_needed(Villager("a", "A", Coord(0, 0), pregnancy=Pregnancy("b", 9))) == 2


def test_a_one_bed_house_can_house_someone(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a house with a single bed is still a home."""
    hut = registry.buildings["house"].model_copy(update={"id": "hut", "housing": 1})
    small = replace(registry, buildings={**registry.buildings, "hut": hut})
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    state.buildings["hut"] = Building(
        "hut", "hut", Coord(3, 3), Ownership("communal"), complete=True
    )
    found = view_of(small, state).house_for(a)
    assert found is not None and found.id == "hut"


def test_a_storehouse_site_does_not_hold_back_another_storehouse(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: only unfinished houses delay storage; other open sites do not."""
    a = Villager("a", "A", Coord(8, 8), home="h0")
    state = make_world(ROWS, [a])
    house(state, "h0", Coord(1, 1))
    state.buildings["s0"] = Building("s0", "storehouse", Coord(12, 12), Ownership("communal"))
    view = view_of(registry, state, storage_per_capita=1000.0)
    assert rules.wanted_building(view, a) == "storehouse"


def test_couples_without_a_spare_bed_at_home_want_another_house(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a couple apart, or together in a full house, counts one bed short (room for a child)."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", Coord(8, 8), sex="female", adult=True, partner="b", home="h0")
    b = Villager("b", "B", Coord(8, 8), sex="male", adult=True, partner="a", home="h1")
    state = make_world(ROWS, [a, b])
    house(state, "h0", Coord(1, 1))
    house(state, "h1", Coord(10, 1))
    for hid in ("h0", "h1"):
        for i in range(capacity - 1):
            state.villagers[f"{hid}r{i}"] = Villager(f"{hid}r{i}", "R", Coord(0, 0), home=hid)
    view = view_of(registry, state, storage_per_capita=0.0)
    assert view.housing_shortfall() == 1  # living apart, every bed taken
    decision = rules.build(view, a)
    assert decision is not None and decision.target == "place:house"
    del state.villagers["h0r0"]
    b.home = "h0"
    state.villagers["h1r9"] = Villager("h1r9", "R", Coord(0, 0), home="h1")
    assert view_of(registry, state, storage_per_capita=0.0).housing_shortfall() == 1  # full
    del state.villagers["h0r1"]
    assert view_of(registry, state, storage_per_capita=0.0).housing_shortfall() == -1


def test_every_crowded_couple_counts_once(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: singles are skipped, and two crowded couples want two beds (one each)."""
    single = Villager("s", "S", Coord(0, 0), sex="female", home="h0")
    pairs = [
        Villager(f"{p}{q}", "P", Coord(0, 0), sex=sex, partner=f"{p}{other}", home=f"h{q}")
        for p in ("a", "b")
        for q, other, sex in ((1, 2, "female"), (2, 1, "male"))
    ]
    state = make_world(ROWS, [single, *pairs])
    for i, at in enumerate((Coord(1, 1), Coord(5, 1), Coord(9, 1))):
        house(state, f"h{i}", at)
    assert view_of(registry, state).crowded_couples() == 2


def test_a_couple_in_a_full_house_moves_together_to_the_nearest_roomy_house(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a couple sharing a house with no spare bed moves, both of them, into the nearest
    house with room for the two plus one (ties to the lower id); then it stays."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", Coord(8, 8), sex="female", partner="b", home="h0")
    b = Villager("b", "B", Coord(8, 8), sex="male", partner="a", home="h0")
    state = make_world(ROWS, [a, b])
    for hid, at in (("h0", Coord(1, 1)), ("h9", Coord(8, 11)), ("h5", Coord(11, 8))):
        house(state, hid, at)
    house(state, "h1", Coord(8, 6))  # nearer, but only room for two
    for i in range(capacity - 2):
        state.villagers[f"o{i}"] = Villager(f"o{i}", "O", Coord(0, 0), home="h0")
    for i in range(capacity - 2):
        state.villagers[f"q{i}"] = Villager(f"q{i}", "Q", Coord(0, 0), home="h1")
    for i in range(capacity - 3):  # h5 has exactly the three beds the family needs
        state.villagers[f"r{i}"] = Villager(f"r{i}", "R", Coord(0, 0), home="h5")
    view = view_of(registry, state, storage_per_capita=0.0)
    assert view.family_house(a) is not None
    decision = rules.home(view, a)
    assert decision is not None and decision.intent == SetHome("a", "h5")  # h5 < h9, same distance
    assert decision.target == "h5"
    a.home = "h5"
    decision = rules.home(view_of(registry, state, storage_per_capita=0.0), b)
    assert decision is not None and decision.intent == SetHome("b", "h5")
    b.home = "h5"
    view = view_of(registry, state, storage_per_capita=0.0)
    assert rules.home(view, a) is None and rules.home(view, b) is None


def test_a_couple_in_a_full_house_stays_when_no_house_has_room_for_three(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: with no house holding the couple plus a spare bed, nobody moves."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", Coord(8, 8), sex="female", partner="b", home="h0")
    b = Villager("b", "B", Coord(8, 8), sex="male", partner="a", home="h0")
    state = make_world(ROWS, [a, b])
    house(state, "h0", Coord(1, 1))
    house(state, "h1", Coord(8, 4))
    for i in range(capacity - 2):
        state.villagers[f"o{i}"] = Villager(f"o{i}", "O", Coord(0, 0), home="h0")
        state.villagers[f"q{i}"] = Villager(f"q{i}", "Q", Coord(0, 0), home="h1")
    view = view_of(registry, state, storage_per_capita=0.0)
    assert view.family_house(a) is None and rules.home(view, a) is None
    del state.villagers["o0"]  # a spare bed at home: no reason to move
    assert rules.home(view_of(registry, state, storage_per_capita=0.0), a) is None


def test_a_crowded_couple_may_move_into_either_partners_house_only(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: the family house is one the mover or its partner may live in, never a stranger's."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", Coord(8, 8), sex="female", partner="b", home="h0")
    b = Villager("b", "B", Coord(8, 8), sex="male", partner="a", home="h0")
    state = make_world(ROWS, [a, b])
    house(state, "h0", Coord(1, 1))
    for i in range(capacity - 2):
        state.villagers[f"o{i}"] = Villager(f"o{i}", "O", Coord(0, 0), home="h0")
    stranger = Building("x", "house", Coord(8, 6), Ownership("personal", ("z",)), complete=True)
    state.buildings["x"] = stranger
    for owner in ("a", "b"):
        state.buildings["p"] = Building(
            "p", "house", Coord(12, 12), Ownership("personal", (owner,)), complete=True
        )
        house_ = view_of(registry, state, storage_per_capita=0.0).family_house(a)
        assert house_ is not None and house_.id == "p", owner
    del state.buildings["p"]
    assert view_of(registry, state, storage_per_capita=0.0).family_house(a) is None


def full_shared_house(
    registry: Registry, make_world: MakeWorld, a_at: Coord, b_at: Coord
) -> tuple[WorldState, Villager, Villager]:
    """A couple apart in space but sharing h0, full; empty h5 and h9 equally far in sum."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", a_at, sex="female", partner="b", home="h0")
    b = Villager("b", "B", b_at, sex="male", partner="a", home="h0")
    state = make_world(ROWS, [a, b])
    for hid, at in (("h0", Coord(6, 6)), ("h5", Coord(12, 0)), ("h9", Coord(0, 12))):
        house(state, hid, at)
    for i in range(capacity - 2):
        state.villagers[f"o{i}"] = Villager(f"o{i}", "O", Coord(6, 9), home="h0")
    return state, a, b


def test_partners_standing_apart_choose_the_same_family_house(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: the couple's choice ranks by both partners' distances, so each picks the same house
    though each stands nearer a different one (h9 near a, h5 near b; equal sums, h5 by id)."""
    state, a, b = full_shared_house(registry, make_world, Coord(0, 15), Coord(15, 0))
    view = view_of(registry, state, storage_per_capita=0.0)
    for villager in (a, b):
        decision = rules.home(view, villager)
        assert decision is not None and decision.intent == SetHome(villager.id, "h5")


def test_a_move_in_flight_ends_with_the_partner_joining(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: after one partner moved to the family house, it stays; the other follows it,
    though the old house now has room for one."""
    state, a, b = full_shared_house(registry, make_world, Coord(0, 15), Coord(15, 0))
    a.home = "h5"
    view = view_of(registry, state, storage_per_capita=0.0)
    assert rules.home(view, a) is None
    decision = rules.home(view, b)
    assert decision is not None and decision.intent == SetHome("b", "h5")


def test_a_couple_apart_reunites_in_the_home_chosen_for_both(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: partners living apart move into whichever of their homes has room for both plus
    one, ranked by both distances then id; the one already there stays."""
    state, a, b = full_shared_house(registry, make_world, Coord(0, 15), Coord(15, 0))
    for vid in [v for v in state.villagers if v.startswith("o")]:
        del state.villagers[vid]
    a.home, b.home = "h9", "h5"  # both empty: equal sums, h5 by id
    view = view_of(registry, state, storage_per_capita=0.0)
    assert rules.home(view, b) is None
    decision = rules.home(view, a)
    assert decision is not None and decision.intent == SetHome("a", "h5")
    capacity = registry.buildings["house"].housing
    for i in range(capacity - 2):  # h5 now has room for the two, but not a third
        state.villagers[f"q{i}"] = Villager(f"q{i}", "Q", Coord(0, 0), home="h5")
    view = view_of(registry, state, storage_per_capita=0.0)
    assert rules.home(view, a) is None
    decision = rules.home(view, b)
    assert decision is not None and decision.intent == SetHome("b", "h9")
    assert decision.target == "h9"


def test_a_crowded_couple_settles_in_one_house_through_the_engine(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: run by the controller and engine, partners standing apart end in one house, and
    no villager is sent a SetHome after that."""
    state, _, _ = full_shared_house(registry, make_world, Coord(0, 15), Coord(15, 0))
    engine = Engine(registry, default_config(debug_invariants=True))
    ctl = Controller(
        engine.context, AgentConfig(storage_per_capita=0.0), ScriptedMind(), ScriptedMind()
    )
    settled_at: int | None = None
    late_moves = []
    for _ in range(120):
        intents = ctl.intents(state)
        if settled_at is not None:
            late_moves += [i for i in intents if isinstance(i, SetHome)]
        state, events = engine.step(state, intents)
        ctl.observe(state, events)
        homes = {state.villagers["a"].home, state.villagers["b"].home}
        if settled_at is None and len(homes) == 1 and homes != {"h0"}:
            settled_at = state.tick
    assert settled_at is not None
    assert state.villagers["a"].home == state.villagers["b"].home == "h5"
    assert late_moves == []


def test_a_couple_apart_with_no_roomy_home_uses_the_family_house_or_waits(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: apart, with neither home roomy enough, the pair goes to the family house; with
    none, nobody moves. A homeless or departed partner leaves the couple house undecided."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", Coord(8, 8), sex="female", partner="b", home="h0")
    b = Villager("b", "B", Coord(8, 8), sex="male", partner="a", home="h1")
    state = make_world(ROWS, [a, b])
    house(state, "h0", Coord(1, 1))
    house(state, "h1", Coord(12, 1))
    for hid in ("h0", "h1"):
        for i in range(capacity - 1):
            state.villagers[f"{hid}r{i}"] = Villager(f"{hid}r{i}", "R", Coord(0, 0), home=hid)
    view = view_of(registry, state, storage_per_capita=0.0)
    assert view.couple_house(a) is None and rules.home(view, a) is None
    house(state, "h7", Coord(12, 12))
    found = view_of(registry, state, storage_per_capita=0.0).couple_house(a)
    assert found is not None and found.id == "h7"
    b.home = None
    assert view_of(registry, state, storage_per_capita=0.0).couple_house(a) is None
    del state.villagers["b"]
    assert view_of(registry, state, storage_per_capita=0.0).couple_house(a) is None
