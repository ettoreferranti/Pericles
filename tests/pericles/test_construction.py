from collections.abc import Callable, Sequence

import pytest

from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import (
    Construct,
    Deliver,
    Deposit,
    Intent,
    MoveTo,
    PlaceBuilding,
    Take,
)
from pericles.core.inventory import Tool
from pericles.core.modifiers import Modifier, Op, Target
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

MakeWorld = Callable[..., WorldState]
ROWS = ("......", "......", "..~...")
PERSONAL_A = Ownership("personal", ("a",))


def world(make_world: MakeWorld) -> WorldState:
    """Ana (1,0) and Bo (4,0) flank the hut plot (2,0)-(3,0); Cy (1,2) is far; a bush at (5,2)."""
    villagers = [
        Villager("a", "Ana", Coord(1, 0)),
        Villager("b", "Bo", Coord(4, 0)),
        Villager("c", "Cy", Coord(1, 2)),
    ]
    return make_world(ROWS, villagers, [Node("n0", "bush", Coord(5, 2), 4)])


def with_hut(
    state: WorldState, ownership: Ownership = PERSONAL_A, complete: bool = False
) -> Building:
    hut = Building("b0", "hut", Coord(2, 0), ownership, complete=complete)
    state.buildings["b0"] = hut
    state.next_building = 1
    return hut


def run(engine: Engine, state: WorldState, intents: Sequence[Intent], ticks: int) -> list[Event]:
    events = list(engine.step(state, intents)[1])
    for _ in range(ticks - 1):
        events += engine.step(state, [])[1]
    return events


def of(events: list[Event], kind: str) -> list[dict[str, object]]:
    return [dict(event.data) for event in events if event.kind == kind]


def reasons(events: list[Event]) -> list[object]:
    return [d["reason"] for d in of(events, "intent_rejected")]


# --- placement -----------------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.req("REQ-ECO-001")
def test_placing_a_site(econ: Registry, make_world: MakeWorld) -> None:
    """AC1 (SIM-009): a site on valid terrain with a free footprint is placed with its ownership."""
    state = world(make_world)
    events = Engine(econ).step(state, [PlaceBuilding("a", "hut", Coord(2, 0))])[1]
    assert of(events, "site_placed") == [
        {
            "actor": "a",
            "building": "b0",
            "kind": "hut",
            "origin": [2, 0],
            "ownership": {"kind": "personal", "owners": ["a"]},
        }
    ]
    assert state.buildings == {"b0": Building("b0", "hut", Coord(2, 0), PERSONAL_A)}
    assert state.next_building == 1


@pytest.mark.req("REQ-ECO-001")
@pytest.mark.parametrize(
    ("ownership", "co_owners", "expected"),
    [
        ("personal", (), Ownership("personal", ("a",))),
        ("shared", ("c",), Ownership("shared", ("a", "c"))),
        ("communal", (), Ownership("communal")),
    ],
)
def test_sites_carry_the_requested_ownership(
    econ: Registry,
    make_world: MakeWorld,
    ownership: str,
    co_owners: tuple[str, ...],
    expected: Ownership,
) -> None:
    """AC1: a building is owned personally, shared among named owners, or communally."""
    state = world(make_world)
    Engine(econ).step(state, [PlaceBuilding("a", "hut", Coord(2, 0), ownership, co_owners)])
    assert state.buildings["b0"].ownership == expected


def test_building_ids_count_up(econ: Registry, make_world: MakeWorld) -> None:
    state = world(make_world)
    engine = Engine(econ)
    engine.step(state, [PlaceBuilding("a", "wall", Coord(1, 1))])
    engine.step(state, [PlaceBuilding("a", "wall", Coord(0, 0))])
    assert sorted(state.buildings) == ["b0", "b1"]
    assert state.next_building == 2


def place(building: str, x: int, y: int, ownership: str = "personal", *co: str) -> PlaceBuilding:
    return PlaceBuilding("a", building, Coord(x, y), ownership, co)


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.parametrize(
    ("intent", "existing_hut", "reason"),
    [
        (place("castle", 2, 0), False, "unknown_building"),
        (place("vault", 2, 0), False, "locked"),
        (place("hut", 2, 0, "private"), False, "bad_ownership"),
        (place("hut", 2, 0, "shared"), False, "bad_ownership"),
        (place("hut", 2, 0, "personal", "c"), False, "bad_ownership"),
        (place("hut", 2, 0, "communal", "c"), False, "bad_ownership"),
        (place("hut", 2, 0, "shared", "zed"), False, "bad_ownership"),
        (place("hut", 5, 0), False, "out_of_bounds"),
        (place("hut", -1, 0), False, "out_of_bounds"),
        (place("wall", 0, 3), False, "out_of_bounds"),
        (place("hut", 1, 2), False, "bad_terrain"),
        (place("wall", 3, 0), True, "occupied"),
        (place("hut", 4, 2), False, "occupied"),
        (place("wall", 4, 0), False, "occupied"),
        (place("hut", 3, 1), False, "not_at_location"),
    ],
)
def test_invalid_placements_are_rejected(
    econ: Registry,
    make_world: MakeWorld,
    intent: PlaceBuilding,
    existing_hut: bool,
    reason: str,
) -> None:
    """AC1: placement needs a known, unlocked kind, valid ownership, terrain and a free footprint."""
    state = world(make_world)
    if existing_hut:
        with_hut(state)
    before = dict(state.buildings)
    events = Engine(econ).step(state, [intent])[1]
    assert reasons(events) == [reason]
    assert state.buildings == before


@pytest.mark.req("REQ-SIM-009")
def test_a_building_with_an_entrance_may_cover_a_villager(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC1: only footprints without an entrance must be free of villagers."""
    state = world(make_world)
    events = Engine(econ).step(state, [place("hut", 1, 0)])[1]
    assert [event.kind for event in events] == ["site_placed"]


@pytest.mark.req("REQ-SIM-011")
def test_a_known_technology_unlocks_a_building(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: a building unlocked by a technology can be placed once it is known."""
    state = world(make_world)
    state.villagers["a"].knowledge.add("vault")
    events = Engine(econ).step(state, [place("vault", 2, 0)])[1]
    assert [event.kind for event in events] == ["site_placed"]


# --- walls and walking ---------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-004")
def test_a_wall_is_not_walkable(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: a building without an entrance blocks paths as soon as its site is placed."""
    villagers = [Villager("a", "Ana", Coord(3, 0)), Villager("b", "Bo", Coord(0, 0))]
    state = make_world(["....."], villagers)
    engine = Engine(econ)
    engine.step(state, [PlaceBuilding("a", "wall", Coord(2, 0))])
    events = engine.step(state, [MoveTo("b", Coord(4, 0))])[1]
    assert of(events, "move_failed") == [{"actor": "b", "target": [4, 0], "reason": "no_path"}]


@pytest.mark.req("REQ-SIM-004")
def test_a_new_wall_cuts_a_path_in_progress(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: a villager whose next tile becomes a wall stops with `blocked`."""
    villagers = [Villager("a", "Ana", Coord(3, 0)), Villager("b", "Bo", Coord(0, 0))]
    state = make_world(["....."], villagers)
    engine = Engine(econ)
    engine.step(state, [MoveTo("b", Coord(4, 0))])
    assert state.villagers["b"].pos == Coord(1, 0)
    events = engine.step(state, [PlaceBuilding("a", "wall", Coord(2, 0))])[1]
    assert of(events, "move_failed") == [{"actor": "b", "target": [4, 0], "reason": "blocked"}]
    assert state.villagers["b"].pos == Coord(1, 0)


@pytest.mark.req("REQ-SIM-004")
def test_a_building_with_an_entrance_is_walkable(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: only buildings without an entrance block movement."""
    villagers = [Villager("a", "Ana", Coord(4, 0)), Villager("b", "Bo", Coord(0, 0))]
    state = make_world(["....."], villagers)
    engine = Engine(econ)
    engine.step(state, [PlaceBuilding("a", "hut", Coord(2, 0))])
    run(engine, state, [MoveTo("b", Coord(4, 0))], 4)
    assert state.villagers["b"].pos == Coord(4, 0)


# --- delivery and construction -------------------------------------------------------------


@pytest.mark.req("REQ-SIM-009")
def test_delivery_moves_materials_onto_the_site(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: delivered cost items are recorded on the site, from anyone near it."""
    state = world(make_world)
    hut = with_hut(state)
    state.villagers["a"].inventory.add(econ, "wood", 5)
    state.villagers["b"].inventory.add(econ, "wood", 1)
    engine = Engine(econ)
    events = engine.step(state, [Deliver("a", "b0", "wood", 3), Deliver("b", "b0", "wood", 1)])[1]
    assert sorted(of(events, "delivered"), key=lambda d: str(d["actor"])) == [
        {"actor": "a", "building": "b0", "item": "wood", "qty": 3},
        {"actor": "b", "building": "b0", "item": "wood", "qty": 1},
    ]
    assert hut.delivered == {"wood": 4}
    assert state.villagers["a"].inventory.items == {"wood": 2}
    assert reasons(engine.step(state, [Deliver("a", "b0", "wood", 1)])[1]) == ["not_needed"]


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.parametrize(
    ("intent", "complete", "reason"),
    [
        (Deliver("a", "b9", "wood", 1), False, "unknown_building"),
        (Deliver("a", "b0", "wood", 1), True, "already_complete"),
        (Deliver("c", "b0", "wood", 1), False, "not_at_location"),
        (Deliver("a", "b0", "wood", 0), False, "bad_quantity"),
        (Deliver("a", "b0", "wood", -1), False, "bad_quantity"),
        (Deliver("a", "b0", "berries", 1), False, "not_needed"),
        (Deliver("a", "b0", "dragon", 1), False, "not_needed"),
        (Deliver("a", "b0", "wood", 5), False, "not_needed"),
        (Deliver("a", "b0", "wood", 3), False, "missing_items"),
    ],
)
def test_invalid_deliveries_are_rejected(
    econ: Registry, make_world: MakeWorld, intent: Deliver, complete: bool, reason: str
) -> None:
    """AC2: only missing cost items, held and brought to the site, can be delivered."""
    state = world(make_world)
    with_hut(state, complete=complete)
    for vid in "ac":
        state.villagers[vid].inventory.add(econ, "wood", 2)
        state.villagers[vid].inventory.add(econ, "berries", 1)
    events = Engine(econ).step(state, [intent])[1]
    assert reasons(events) == [reason]
    assert state.buildings["b0"].delivered == {}


@pytest.mark.req("REQ-SIM-009")
def test_construction_completes_when_materials_and_work_are_done(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: two builders do the 20 units of build work in 10 ticks; the materials are consumed."""
    state = world(make_world)
    hut = with_hut(state)
    hut.delivered = {"wood": 4}
    engine = Engine(econ)
    run(engine, state, [Construct("a", "b0"), Construct("b", "b0")], 9)
    assert (hut.work_done, hut.complete) == (18.0, False)
    events = engine.step(state, [])[1]
    assert [event.kind for event in events] == ["building_completed", "work_done", "work_done"]
    assert dict(events[0].data) == {"building": "b0", "kind": "hut", "destroyed": {"wood": 4}}
    assert [(d["actor"], d["created"], d["destroyed"]) for d in of(events, "work_done")] == [
        ("a", {}, {}),
        ("b", {}, {}),
    ]
    assert (hut.complete, hut.work_done, hut.delivered) == (True, 20.0, {})
    assert state.villagers["a"].activity is None
    assert state.villagers["b"].activity is None


@pytest.mark.req("REQ-SIM-009")
def test_construction_cannot_start_before_every_material_arrives(
    econ: Registry, make_world: MakeWorld
) -> None:
    """AC2: build work needs every cost item delivered first."""
    state = world(make_world)
    with_hut(state).delivered = {"wood": 3}
    events = Engine(econ).step(state, [Construct("a", "b0")])[1]
    assert reasons(events) == ["missing_materials"]


@pytest.mark.req("REQ-SIM-009")
def test_interrupted_construction_keeps_its_progress(econ: Registry, make_world: MakeWorld) -> None:
    """AC2: build work done so far stays on the site and resumes from there."""
    state = world(make_world)
    hut = with_hut(state)
    hut.delivered = {"wood": 4}
    engine = Engine(econ)
    run(engine, state, [Construct("a", "b0")], 3)
    events = engine.step(state, [MoveTo("a", Coord(1, 1))])[1]
    assert of(events, "work_interrupted")[0]["cause"] == "actor"
    assert hut.work_done == 3.0
    engine.step(state, [MoveTo("a", Coord(1, 0))])
    events = engine.step(state, [Construct("a", "b0")])[1]
    assert of(events, "work_started")[0]["ticks"] == 17
    assert hut.work_done == 4.0


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.parametrize(
    ("intent", "complete", "reason"),
    [
        (Construct("a", "b9"), False, "unknown_building"),
        (Construct("a", "b0"), True, "already_complete"),
        (Construct("c", "b0"), False, "not_at_location"),
    ],
)
def test_invalid_construction_is_rejected(
    econ: Registry, make_world: MakeWorld, intent: Construct, complete: bool, reason: str
) -> None:
    """AC2: construction needs a known, unfinished site within reach."""
    state = world(make_world)
    with_hut(state, complete=complete).delivered = {"wood": 4}
    assert reasons(Engine(econ).step(state, [intent])[1]) == [reason]


@pytest.mark.req("REQ-SIM-009")
@pytest.mark.parametrize(("factor", "outcome"), [(4.0, 5), (0.0, "cannot_work")])
def test_build_speed_follows_modifiers(
    econ: Registry, make_world: MakeWorld, factor: float, outcome: object
) -> None:
    """AC2: build speed is `work_speed` on the building; a speed of 0 cannot start."""
    state = world(make_world)
    with_hut(state).delivered = {"wood": 4}
    state.modifiers = (Modifier(Target("building", "hut"), "work_speed", Op.MUL, factor, "test"),)
    events = Engine(econ).step(state, [Construct("a", "b0")])[1]
    if isinstance(outcome, int):
        assert of(events, "work_started")[0]["ticks"] == outcome
    else:
        assert reasons(events) == [outcome]


# --- stores and ownership ------------------------------------------------------------------


@pytest.mark.req("REQ-ECO-001")
@pytest.mark.parametrize(
    ("ownership", "taker", "unowned"),
    [
        (Ownership("personal", ("a",)), "a", False),
        (Ownership("personal", ("a",)), "b", True),
        (Ownership("shared", ("a", "b")), "b", False),
        (Ownership("shared", ("a", "b")), "c", True),
        (Ownership("communal"), "b", False),
    ],
)
def test_taking_from_a_store_reports_unowned_takes(
    econ: Registry, make_world: MakeWorld, ownership: Ownership, taker: str, unowned: bool
) -> None:
    """AC2: a take by someone who does not own the store also emits `take_unowned`."""
    state = world(make_world)
    state.villagers["c"].pos = Coord(2, 1)
    hut = with_hut(state, ownership, complete=True)
    hut.storage.add(econ, "wood", 3)
    events = Engine(econ).step(state, [Take(taker, "b0", "wood", 2)])[1]
    assert of(events, "item_taken") == [
        {"actor": taker, "building": "b0", "item": "wood", "qty": 2, "ownership": ownership.kind}
    ]
    expected = [
        {
            "actor": taker,
            "store": "b0",
            "item": "wood",
            "qty": 2,
            "owners": list(ownership.owners),
        }
    ]
    assert of(events, "take_unowned") == (expected if unowned else [])
    assert state.villagers[taker].inventory.items == {"wood": 2}
    assert hut.storage.items == {"wood": 1}


@pytest.mark.req("REQ-SIM-009")
def test_deposit_and_take_keep_tool_wear(econ: Registry, make_world: MakeWorld) -> None:
    """AC3: a completed building provides storage; stored tools keep their durability."""
    state = world(make_world)
    hut = with_hut(state, complete=True)
    state.villagers["a"].inventory.add_tools([Tool("axe", 1)])
    engine = Engine(econ)
    events = engine.step(state, [Deposit("a", "b0", "axe", 1)])[1]
    assert of(events, "item_deposited") == [
        {"actor": "a", "building": "b0", "item": "axe", "qty": 1}
    ]
    assert hut.storage.tools == [Tool("axe", 1)]
    engine.step(state, [Take("a", "b0", "axe", 1)])
    assert state.villagers["a"].inventory.tools == [Tool("axe", 1)]


def store_world(make_world: MakeWorld, econ: Registry) -> WorldState:
    state = world(make_world)
    with_hut(state, complete=True).storage.add(econ, "wood", 9)
    state.buildings["b1"] = Building("b1", "hut", Coord(4, 1), PERSONAL_A)
    state.buildings["b2"] = Building("b2", "workshop", Coord(0, 0), PERSONAL_A, complete=True)
    state.villagers["a"].inventory.add(econ, "wood", 2)
    state.villagers["b"].inventory.add(econ, "wood", 15)
    return state


@pytest.mark.req("REQ-SIM-013")
@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        (Deposit("a", "b9", "wood", 1), "unknown_building"),
        (Deposit("b", "b1", "wood", 1), "no_storage"),
        (Deposit("a", "b2", "wood", 1), "no_storage"),
        (Deposit("c", "b0", "wood", 1), "not_at_location"),
        (Deposit("a", "b0", "wood", 0), "bad_quantity"),
        (Deposit("a", "b0", "wood", 3), "missing_items"),
        (Deposit("a", "b0", "wood", 2), "store_full"),
        (Take("a", "b9", "wood", 1), "unknown_building"),
        (Take("a", "b2", "wood", 1), "no_storage"),
        (Take("c", "b0", "wood", 1), "not_at_location"),
        (Take("a", "b0", "wood", -2), "bad_quantity"),
        (Take("a", "b0", "wood", 10), "missing_items"),
        (Take("a", "b0", "dragon", 1), "missing_items"),
        (Take("b", "b0", "wood", 1), "carry_limit"),
    ],
)
def test_invalid_store_transfers_are_rejected(
    econ: Registry, make_world: MakeWorld, intent: Intent, reason: str
) -> None:
    """AC2: a take that would exceed the carry limit is rejected, like every invalid transfer."""
    state = store_world(make_world, econ)
    before = state.to_dict()
    events = Engine(econ).step(state, [intent])[1]
    assert reasons(events) == [reason]
    after = state.to_dict()
    assert after["villagers"] == before["villagers"]
    assert after["buildings"] == before["buildings"]


def test_a_store_fills_up_to_its_capacity(econ: Registry, make_world: MakeWorld) -> None:
    state = store_world(make_world, econ)
    events = Engine(econ).step(state, [Deposit("a", "b0", "wood", 1)])[1]
    assert [event.kind for event in events] == ["item_deposited"]
    assert state.buildings["b0"].storage.items == {"wood": 10}
