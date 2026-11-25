from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller
from pericles.agents.scripted import scripted_controller
from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

MakeWorld = Callable[..., WorldState]
ROWS = [
    "....TTTT....",
    "....TTTT.~~.",
    "...........~",
    "RR..........",
    "RR....~~....",
    "......~~....",
] * 2
# A short calendar: 60-minute ticks make a day 24 ticks, so a few ticks-days carry the whole life
# cycle (conception, birth, coming of age) inside the run, and the split falls mid-day after
# several day rollovers.
PER_DAY = 24
ADULT_DAYS = 4
DAYS = 8
TICKS, SPLIT = DAYS * PER_DAY, 5 * PER_DAY + 12
HOUSE_AT = Coord(5, 2)
# Water rings the house's footprint and the map centre, so some sites, homes, spots and
# villagers are cut off from the rest.
RINGED = [
    "............",
    "....~~~~....",
    "....~..~....",
    "....~..~.TT.",
    "....~~~~.TT.",
    ".....~~~~...",
    "RR...~..~...",
    "RR...~..~...",
    ".....~~~~...",
    "..TT........",
    "..TT....~~..",
    "............",
]
MAPS = st.sampled_from(["plain", "ringed"])


def life_config() -> EngineConfig:
    return default_config(
        debug_invariants=True,
        calendar=Calendar(
            seasons=(Season("dry", 3), Season("wet", 2)),
            tick_minutes=60,
            sunrise_minute=360,
            sunset_minute=1200,
        ),
        adult_age_days=ADULT_DAYS,
        gestation_days=2,
        birth_interval_days=1,
        conception_chance_per_day=0.8,
        birth_food_per_capita=1.0,
    )


@dataclass(frozen=True)
class Person:
    sex: str
    age_days: int
    offset: int  # extra ticks into the current day of age
    berries: int
    wood: int
    stone: int
    x: int
    y: int


person = st.builds(
    Person,
    st.sampled_from(["female", "male"]),
    st.sampled_from([0, 1, ADULT_DAYS - 1, ADULT_DAYS, ADULT_DAYS + 3, 10]),
    st.integers(0, PER_DAY - 1),
    st.sampled_from([0, 3, 12, 40]),
    st.sampled_from([0, 0, 3, 5]),
    st.sampled_from([0, 0, 2, 3]),
    st.integers(0, 11),
    st.integers(0, 11),
)
spot = st.tuples(
    st.sampled_from(["berry_bush", "tree", "boulder"]), st.integers(0, 11), st.integers(0, 11)
)
HOUSES = st.sampled_from(["none", "site", "complete"])


def build_village(
    registry: Registry,
    make_world: MakeWorld,
    people: list[Person],
    spots: list[tuple[str, int, int]],
    house: str,
    pair_up: bool,
    rows: list[str] = ROWS,
) -> WorldState:
    villagers = []
    for i, p in enumerate(people):
        born = -(p.age_days * PER_DAY + p.offset)
        adult = p.age_days >= ADULT_DAYS
        v = Villager(f"v{i}", f"V{i}", Coord(p.x, p.y), sex=p.sex, born_tick=born, adult=adult)
        for item, qty in (("berries", p.berries), ("wood", p.wood), ("stone", p.stone)):
            v.inventory.add(registry, item, qty)
        villagers.append(v)
    adults = [v for v in villagers if v.adult]
    parents = [v.id for v in adults][:2]
    for v in villagers:
        if not v.adult and parents:
            v.parents = tuple(sorted(parents))
    buildings = []
    if house != "none":
        cost = dict(registry.buildings["house"].cost)
        built = house == "complete"
        buildings.append(
            Building(
                "h0",
                "house",
                HOUSE_AT,
                Ownership("communal"),
                complete=built,
                delivered={} if built else cost,
            )
        )
    women = [v for v in adults if v.sex == "female"]
    men = [v for v in adults if v.sex == "male"]
    if pair_up and women and men:
        women[0].partner, men[0].partner = men[0].id, women[0].id
        if house == "complete":
            women[0].home = men[0].home = "h0"
    nodes = [Node(f"n{i}", kind, Coord(x, y), 10) for i, (kind, x, y) in enumerate(spots)]
    state = make_world(rows, villagers, nodes)
    for b in buildings:
        state.buildings[b.id] = b
    return state


def run(
    registry: Registry,
    state: WorldState,
    ticks: int,
    split: int | None,
    log: Any = None,
) -> tuple[
    WorldState,
    Controller,
    list[list[dict[str, object]]],
    tuple[dict[str, object], dict[str, object]] | None,
]:
    config = life_config()
    engine = Engine(registry, config)
    controller = scripted_controller(engine.context, AgentConfig())
    saved = None
    per_tick: list[list[dict[str, object]]] = []
    for tick in range(ticks):
        if tick == split:
            saved = (state.to_dict(), controller.to_dict())
        state, events = engine.step(state, controller.intents(state))
        if log is not None:
            log.record(controller.memory, state.tick, events)
        controller.observe(state, events)
        per_tick.append([e.to_dict() for e in events])
    return state, controller, per_tick, saved


@pytest.mark.req("REQ-AGT-008", "REQ-EXP-003")
def test_the_short_life_cycle_configuration_reaches_births_and_coming_of_age(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AGT-008 AC1 / EXP-003 AC3: the fuzz configuration really reaches day rollovers,
    conception, birth and coming of age (so the property test checks resume across them)."""
    people = [
        Person("female", 10, 0, 40, 0, 0, 5, 4),
        Person("male", 10, 0, 40, 0, 0, 6, 4),
        Person("female", ADULT_DAYS - 1, 3, 20, 0, 0, 5, 5),
    ]
    state = build_village(registry, make_world, people, [("berry_bush", 4, 4)], "complete", True)
    state, _, per_tick, _ = run(registry, state, TICKS, None)
    kinds = {e["kind"] for tick in per_tick for e in tick}
    assert {"conceived", "born", "came_of_age"} <= kinds
    assert state.tick // PER_DAY >= DAYS
    assert SPLIT % PER_DAY != 0 and SPLIT > PER_DAY


@pytest.mark.req("REQ-AGT-008", "REQ-EXP-003")
@settings(
    max_examples=100, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    st.lists(person, min_size=1, max_size=6),
    st.lists(spot, max_size=12),
    HOUSES,
    st.booleans(),
    MAPS,
)
def test_scripted_villages_keep_invariants_and_resume_exactly(
    registry: Registry,
    make_world: MakeWorld,
    failure_log: Callable[[], Any],
    people: list[Person],
    spots: list[tuple[str, int, int]],
    house: str,
    pair_up: bool,
    terrain: str,
) -> None:
    """AGT-008 AC1 / EXP-003 AC3: any small scripted village across several short days (with
    births and coming of age) keeps the engine's invariants (debug_invariants checks item
    conservation), never retries a target it failed to reach or use within avoid_ticks (some
    maps wall places off with water), and restoring world + agent memory mid-day reproduces
    the rest of the run."""
    rows = RINGED if terrain == "ringed" else ROWS
    state = build_village(registry, make_world, people, spots, house, pair_up, rows)
    log = failure_log()
    state, controller, per_tick, saved = run(registry, state, TICKS, SPLIT, log)
    assert saved is not None
    assert log.repeats(AgentConfig().avoid_ticks) == []
    tail = [e for tick in per_tick[SPLIT:] for e in tick]
    config = life_config()
    again = WorldState.from_dict(saved[0])
    other = scripted_controller(Engine(registry, config).context, AgentConfig())
    other.load(saved[1])
    engine2 = Engine(registry, config)
    replay: list[dict[str, object]] = []
    for _ in range(SPLIT, TICKS):
        again, events = engine2.step(again, other.intents(again))
        other.observe(again, events)
        replay.extend(e.to_dict() for e in events)
    assert replay == tail
    assert again.to_dict() == state.to_dict()
    assert other.to_dict() == controller.to_dict()
