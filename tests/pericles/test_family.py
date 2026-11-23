from collections.abc import Callable

import pytest

from pericles.core import lifecycle
from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import AcceptCouple, ProposeCouple, SetHome
from pericles.core.inventory import Inventory
from pericles.core.state import Deceased, Pregnancy, Proposal, Villager, WorldState

ROWS = ["........", "........", "........", "........"]
MakeWorld = Callable[..., WorldState]
DAYS = Calendar(seasons=(Season("year", 100),), day_minutes=4, sunrise_minute=0, sunset_minute=2)


def adult(vid: str, sex: str = "female", **fields: object) -> Villager:
    return Villager(vid, vid.upper(), Coord(0, 0), sex=sex, **fields)  # type: ignore[arg-type]


def house(
    state: WorldState,
    bid: str = "b0",
    kind: str = "lodge",
    owner: str | None = None,
    at: Coord | None = None,
) -> None:
    ownership = Ownership("personal", (owner,)) if owner else Ownership("communal")
    state.buildings[bid] = Building(bid, kind, at or Coord(5, 0), ownership, complete=True)


def rejected(events: list) -> list[str]:  # type: ignore[type-arg]
    return [e.data["reason"] for e in events if e.kind == "intent_rejected"]


def couple(state: WorldState, a: str, b: str, home: str = "b0") -> None:
    for x, y in ((a, b), (b, a)):
        state.villagers[x].partner = y
        state.villagers[x].home = home


# --- homes -------------------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-015")
def test_moving_into_a_home(life: Registry, make_world: MakeWorld) -> None:
    """AC2 (the couple's house): a villager can make a completed house they may use their home."""
    state = make_world(ROWS, [adult("a")])
    house(state, owner="a")
    _, events = Engine(life).step(state, [SetHome("a", "b0")])
    assert [e.data for e in events if e.kind == "moved_in"] == [{"actor": "a", "building": "b0"}]
    assert state.villagers["a"].home == "b0"


@pytest.mark.req("REQ-SIM-015")
def test_a_partner_may_move_into_the_other_partners_house(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: a personal house is usable by the owner's partner."""
    state = make_world(ROWS, [adult("a", partner="b"), adult("b", "male", partner="a")])
    house(state, owner="a")
    Engine(life).step(state, [SetHome("b", "b0")])
    assert state.villagers["b"].home == "b0"


@pytest.mark.req("REQ-SIM-015")
@pytest.mark.parametrize(
    ("setup", "building", "reason"),
    [
        (lambda s: None, "b9", "unknown_building"),
        (lambda s: setattr(s.buildings["b0"], "complete", False), "b0", "incomplete"),
        (lambda s: None, "st", "not_housing"),
        (
            lambda s: setattr(s.buildings["b0"], "ownership", Ownership("personal", ("q",))),
            "b0",
            "not_owner",
        ),
    ],
)
def test_bad_homes_are_rejected(
    life: Registry,
    make_world: MakeWorld,
    setup: Callable[[WorldState], object],
    building: str,
    reason: str,
) -> None:
    """AC2: only a completed house the villager may use can be a home."""
    state = make_world(ROWS, [adult("a"), adult("q")])
    house(state)
    state.buildings["st"] = Building(
        "st", "vault", Coord(0, 3), Ownership("communal"), complete=True
    )
    setup(state)
    _, events = Engine(life).step(state, [SetHome("a", building)])
    assert rejected(events) == [reason]
    assert state.villagers["a"].home is None


@pytest.mark.req("REQ-SIM-015")
def test_a_full_house_takes_no_one_and_pregnancies_count(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: a cabin houses 5; 4 residents plus one pregnancy leave no room."""
    people = [adult(f"r{i}", home="h") for i in range(4)] + [adult("a")]
    people[0].pregnancy = Pregnancy("r1", 999)
    state = make_world(ROWS, people)
    house(state, "h", "cabin")
    assert lifecycle.occupants(state, "h") == 5
    _, events = Engine(life).step(state, [SetHome("a", "h")])
    assert rejected(events) == ["house_full"]


# --- couples -------------------------------------------------------------------------------


@pytest.mark.req("REQ-SIM-015")
def test_a_couple_forms_only_by_proposal_and_acceptance(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: one villager proposes, the other accepts; only then are they a couple."""
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    engine = Engine(life, EngineConfig(couple_proposal_ttl_ticks=5))
    _, events = engine.step(state, [ProposeCouple("a", "b")])
    assert [e.data for e in events if e.kind == "couple_proposed"] == [
        {"actor": "a", "target": "b", "expires_tick": 5}
    ]
    assert not state.villagers["a"].partner
    _, events = engine.step(state, [AcceptCouple("b", "a")])
    assert [e.data for e in events if e.kind == "couple_formed"] == [{"villagers": ["a", "b"]}]
    assert (state.villagers["a"].partner, state.villagers["b"].partner) == ("b", "a")
    assert state.proposals == {}


@pytest.mark.req("REQ-SIM-015")
def test_accepting_needs_a_live_proposal_to_you(life: Registry, make_world: MakeWorld) -> None:
    """AC1: no consent without a proposal addressed to the acceptor."""
    state = make_world(ROWS, [adult("a"), adult("b", "male"), adult("c")])
    engine = Engine(life)
    _, events = engine.step(state, [AcceptCouple("b", "a")])
    assert rejected(events) == ["no_proposal"]
    state.proposals["a"] = Proposal("c", 99)
    _, events = engine.step(state, [AcceptCouple("b", "a")])
    assert rejected(events) == ["no_proposal"]


@pytest.mark.req("REQ-SIM-015")
def test_a_proposal_lapses_after_its_ttl(life: Registry, make_world: MakeWorld) -> None:
    """AC1: proposed on tick 0 with TTL 2: acceptable on ticks 0-1, gone after tick 1."""
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    engine = Engine(life, EngineConfig(couple_proposal_ttl_ticks=2))
    engine.step(state, [ProposeCouple("a", "b")])
    _, events = engine.step(state, [])
    assert [e.data for e in events if e.kind == "couple_proposal_expired"] == [
        {"actor": "a", "target": "b"}
    ]
    _, events = engine.step(state, [AcceptCouple("b", "a")])
    assert rejected(events) == ["no_proposal"]


@pytest.mark.req("REQ-SIM-015")
def test_acceptance_on_the_last_valid_tick_works(life: Registry, make_world: MakeWorld) -> None:
    """AC1: the TTL boundary is inclusive of tick T+n-1."""
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    engine = Engine(life, EngineConfig(couple_proposal_ttl_ticks=2))
    engine.step(state, [ProposeCouple("a", "b")])
    engine.step(state, [AcceptCouple("b", "a")])
    assert state.villagers["a"].partner == "b"


@pytest.mark.req("REQ-SIM-015")
@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        (ProposeCouple("a", "zz"), "unknown_target"),
        (ProposeCouple("a", "a"), "self"),
        (ProposeCouple("a", "kid"), "target_too_young"),
        (ProposeCouple("p", "b"), "already_partnered"),
        (ProposeCouple("a", "p"), "target_partnered"),
    ],
)
def test_bad_proposals_are_rejected(
    life: Registry, make_world: MakeWorld, intent: ProposeCouple, reason: str
) -> None:
    """AC1: only two unpartnered adults can be a couple."""
    state = make_world(
        ROWS,
        [
            adult("a"),
            adult("b", "male"),
            adult("kid", adult=False),
            adult("p", partner="q"),
            adult("q", partner="p"),
        ],
    )
    _, events = Engine(life).step(state, [intent])
    assert rejected(events) == [reason]
    assert state.proposals == {}


@pytest.mark.req("REQ-SIM-015")
def test_acceptance_fails_if_someone_partnered_meanwhile(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: two proposals to the same villager cannot both succeed."""
    state = make_world(ROWS, [adult("a"), adult("c"), adult("b", "male")])
    engine = Engine(life)
    engine.step(state, [ProposeCouple("a", "b")])
    engine.step(state, [ProposeCouple("c", "b")])
    engine.step(state, [AcceptCouple("b", "a")])
    _, events = engine.step(state, [AcceptCouple("b", "c")])
    assert rejected(events) == ["already_partnered"]
    state.proposals["c"] = Proposal("q", 99)
    state.villagers["q"] = adult("q")
    state.villagers["c"].partner = "zz"
    _, events = engine.step(state, [AcceptCouple("q", "c")])
    assert rejected(events) == ["target_partnered"]


# --- conception and births -------------------------------------------------------------------


def family(life: Registry, make_world: MakeWorld, **config: object) -> tuple[Engine, WorldState]:
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    house(state)
    couple(state, "a", "b")
    state.villagers["a"].inventory = Inventory({"berries": 20})  # 200 nutrition
    settings = {
        "calendar": DAYS,
        "conception_chance_per_day": 1.0,
        "gestation_days": 2,
        "birth_food_per_capita": 10.0,
        **config,
    }
    return Engine(life, EngineConfig(**settings)), state  # type: ignore[arg-type]


def run_days(engine: Engine, state: WorldState, days: int) -> list:  # type: ignore[type-arg]
    events = []
    for _ in range(days * 4):
        events += engine.step(state, [])[1]
    return events


@pytest.mark.req("REQ-SIM-015")
def test_a_couple_with_a_house_and_food_has_a_child_after_gestation(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: conception at the day boundary; the child is born gestation_days later."""
    engine, state = family(life, make_world)
    events = run_days(engine, state, 1)
    assert [e.data for e in events if e.kind == "conceived"] == [
        {"mother": "a", "father": "b", "due_tick": 11}
    ]
    events = run_days(engine, state, 2)
    born = [e for e in events if e.kind == "born"]
    assert len(born) == 1 and born[0].tick == 11
    child = state.villagers[born[0].data["child"]]
    assert child.parents == ("a", "b") and child.adult is False
    assert child.home == "b0" and child.pos == state.villagers["a"].pos
    assert child.born_tick == 11 and child.sex in ("female", "male")
    assert state.villagers["a"].pregnancy is None
    assert state.villagers["a"].last_birth_tick == 11


@pytest.mark.req("REQ-SIM-015")
@pytest.mark.parametrize(
    "spoil",
    [
        lambda s: setattr(s.villagers["a"], "inventory", Inventory({"berries": 1})),  # 10 < 20
        lambda s: setattr(s.villagers["b"], "home", None),
        lambda s: setattr(s.buildings["b0"], "complete", False),
        lambda s: setattr(s.villagers["b"], "sex", "female"),
        lambda s: setattr(s.villagers["b"], "adult", False),
        lambda s: setattr(s.villagers["a"], "last_birth_tick", 0),
    ],
)
def test_no_pregnancy_without_the_conditions(
    life: Registry, make_world: MakeWorld, spoil: Callable[[WorldState], object]
) -> None:
    """AC2: no house, too little food, no fertile pair, or too soon after a birth: no pregnancy."""
    engine, state = family(life, make_world, birth_interval_days=5)
    spoil(state)
    events = run_days(engine, state, 1)
    assert "conceived" not in [e.kind for e in events]


@pytest.mark.req("REQ-SIM-015")
def test_food_threshold_is_inclusive(life: Registry, make_world: MakeWorld) -> None:
    """AC2: a stock exactly at per-capita times population is enough (2 x 10 = 20 = 2 berries)."""
    engine, state = family(life, make_world)
    state.villagers["a"].inventory = Inventory()
    state.buildings["b0"].storage.add(life, "berries", 2)
    assert lifecycle.food_stock(engine.context, state) == 20.0
    events = run_days(engine, state, 1)
    assert "conceived" in [e.kind for e in events]


@pytest.mark.req("REQ-SIM-015")
def test_two_couples_cannot_overfill_a_house(life: Registry, make_world: MakeWorld) -> None:
    """AC2: a cabin of 5 with two couples has one free place; only one conception happens."""
    engine, state = family(life, make_world)
    state.villagers["c"] = adult("c")
    state.villagers["d"] = adult("d", "male")
    house(state, "h", "cabin", at=Coord(0, 2))
    couple(state, "a", "b", "h")
    couple(state, "c", "d", "h")
    state.villagers["c"].inventory = Inventory({"berries": 20})
    events = run_days(engine, state, 1)
    assert [e.data["mother"] for e in events if e.kind == "conceived"] == ["a"]
    events = run_days(engine, state, 4)
    assert lifecycle.occupants(state, "h") == 5
    assert [e.data["mother"] for e in events if e.kind == "conceived"] == []


@pytest.mark.req("REQ-SIM-015")
def test_conception_chance_uses_the_seeded_rng(life: Registry, make_world: MakeWorld) -> None:
    """AC2: chance 0 never conceives; a fractional chance repeats exactly under one seed."""
    engine, state = family(life, make_world, conception_chance_per_day=0.0)
    assert "conceived" not in [e.kind for e in run_days(engine, state, 5)]
    days = []
    for _ in range(2):
        engine, state = family(life, make_world, conception_chance_per_day=0.3)
        events = run_days(engine, state, 10)
        days.append([e.tick for e in events if e.kind == "conceived"])
    assert days[0] == days[1] and days[0]


@pytest.mark.req("REQ-SIM-015")
def test_child_ids_skip_used_ids_and_names_cycle(life: Registry, make_world: MakeWorld) -> None:
    """New villagers get fresh ids v<n> (never reused, even from the dead) and listed names."""
    engine, state = family(life, make_world, child_names=("Io", "Eos"))
    state.villagers["v0"] = adult("v0")
    state.dead["v1"] = Deceased("v1", "Old", None, 0, 0, "cold", (), None)
    state.villagers["a"].pregnancy = Pregnancy("b", state.tick)
    sink = EventSink(state.tick)
    lifecycle.births(engine.context, state, sink)
    assert "v2" in state.villagers and state.villagers["v2"].name == "Io"  # names[2 % 2]
    assert state.next_villager == 3


@pytest.mark.req("REQ-SIM-015")
def test_population_can_double_in_good_conditions(life: Registry, make_world: MakeWorld) -> None:
    """AC3: with fertile settings, four couples in lodges of 8 double the village in 8 days."""
    people = []
    for i in range(4):
        people += [adult(f"m{i}"), adult(f"f{i}", "male")]
    state = make_world(ROWS, people)
    for i, at in enumerate((Coord(5, 0), Coord(0, 2), Coord(2, 2), Coord(4, 2))):
        house(state, f"b{i}", at=at)
        couple(state, f"m{i}", f"f{i}", f"b{i}")
    state.buildings["b0"].storage.add(life, "berries", 50)
    config = EngineConfig(
        calendar=DAYS,
        conception_chance_per_day=1.0,
        gestation_days=2,
        birth_interval_days=1,
        birth_food_per_capita=10.0,
    )
    engine = Engine(life, config)
    run_days(engine, state, 8)
    assert len(state.villagers) >= 16


# --- boundaries and exact events (mutation survivors) -------------------------------------------


@pytest.mark.req("REQ-SIM-015")
@pytest.mark.parametrize(
    ("residents", "pregnant", "accepted"),
    [(4, False, True), (3, True, True), (4, True, False)],
)
def test_house_room_counts_the_newcomers_own_pregnancy(
    life: Registry, make_world: MakeWorld, residents: int, pregnant: bool, accepted: bool
) -> None:
    """AC2: a cabin of 5 admits a newcomer exactly up to capacity, counting an unborn child."""
    people = [adult(f"r{i}", home="h") for i in range(residents)] + [adult("a")]
    if pregnant:
        people[-1].pregnancy = Pregnancy("r0", 999)
    state = make_world(ROWS, people)
    house(state, "h", "cabin")
    _, events = Engine(life).step(state, [SetHome("a", "h")])
    assert (state.villagers["a"].home == "h") is accepted
    assert rejected(events) == ([] if accepted else ["house_full"])


@pytest.mark.req("REQ-SIM-015")
def test_a_partner_of_a_stranger_may_not_use_the_house(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: partnership with a non-owner gives no right to a personal house."""
    state = make_world(ROWS, [adult("a", partner="b"), adult("b", "male", partner="a"), adult("q")])
    house(state, owner="q")
    _, events = Engine(life).step(state, [SetHome("a", "b0")])
    assert rejected(events) == ["not_owner"]


@pytest.mark.req("REQ-SIM-015")
def test_acceptance_is_refused_at_the_expiry_tick(life: Registry, make_world: MakeWorld) -> None:
    """AC1: a proposal whose expires_tick equals the current tick can no longer be accepted."""
    state = make_world(ROWS, [adult("a"), adult("b", "male")])
    state.proposals["a"] = Proposal("b", state.tick)
    _, events = Engine(life).step(state, [AcceptCouple("b", "a")])
    assert rejected(events) == ["no_proposal"]


@pytest.mark.req("REQ-SIM-015")
def test_rest_after_a_birth_ends_exactly_one_interval_later(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: conception is allowed when exactly birth_interval_days have passed, not before."""
    engine, state = family(life, make_world, birth_interval_days=5)  # 20 ticks
    state.villagers["a"].last_birth_tick = -17  # conception roll on tick 3: exactly 20 ago
    assert "conceived" in [e.kind for e in run_days(engine, state, 1)]
    engine, state = family(life, make_world, birth_interval_days=5)
    state.villagers["a"].last_birth_tick = -16  # 19 ago
    assert "conceived" not in [e.kind for e in run_days(engine, state, 1)]


@pytest.mark.req("REQ-SIM-015")
def test_an_unrested_mother_does_not_block_later_mothers(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: each mother is judged on her own; skipping one does not end the roll."""
    engine, state = family(life, make_world, birth_interval_days=5)
    state.villagers["c"] = adult("c")
    state.villagers["d"] = adult("d", "male")
    house(state, "h", "cabin", at=Coord(0, 2))
    couple(state, "c", "d", "h")
    state.villagers["a"].last_birth_tick = 0
    events = run_days(engine, state, 1)
    assert [e.data["mother"] for e in events if e.kind == "conceived"] == ["c"]


@pytest.mark.req("REQ-SIM-015")
def test_a_birth_event_names_everyone_and_ids_step_by_one(
    life: Registry, make_world: MakeWorld
) -> None:
    """The born event carries child, mother, father and sex; the next free id is used."""
    engine, state = family(life, make_world)
    state.villagers["v0"] = adult("v0")
    state.villagers["a"].pregnancy = Pregnancy("b", state.tick)
    sink = EventSink(state.tick)
    lifecycle.births(engine.context, state, sink)
    (event,) = [e for e in sink.events if e.kind == "born"]
    assert event.data == {
        "child": "v1",
        "mother": "a",
        "father": "b",
        "sex": state.villagers["v1"].sex,
    }
    assert state.villagers["v1"].name == "v1"
    assert state.villagers["v1"].sex in engine.config.sexes
    assert state.villagers["v1"].id == "v1"


@pytest.mark.req("REQ-SIM-015")
@pytest.mark.parametrize(
    ("proposal_from", "intent", "reason"),
    [
        (None, ProposeCouple("kid", "a"), "too_young"),
        ("kid", AcceptCouple("a", "kid"), "target_too_young"),
        ("a", AcceptCouple("kid", "a"), "too_young"),
    ],
)
def test_children_cannot_form_couples(
    life: Registry,
    make_world: MakeWorld,
    proposal_from: str | None,
    intent: ProposeCouple | AcceptCouple,
    reason: str,
) -> None:
    """AC1: only two adults can be a couple, whoever proposes or accepts."""
    state = make_world(ROWS, [adult("a"), adult("kid", "male", adult=False)])
    if proposal_from is not None:
        target = "a" if proposal_from == "kid" else "kid"
        state.proposals[proposal_from] = Proposal(target, 99)
    _, events = Engine(life).step(state, [intent])
    assert rejected(events) == [reason]
    assert state.villagers["a"].partner is None
    assert state.villagers["kid"].partner is None
