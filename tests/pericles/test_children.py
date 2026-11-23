from collections.abc import Callable

import pytest

from pericles.core import lifecycle
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import AcceptCouple, Eat, PlaceBuilding, ProposeCouple, StartAction, Wait
from pericles.core.inventory import Inventory
from pericles.core.state import Deceased, Pregnancy, Proposal, Villager, WorldState

ROWS = ["......", "......", "......"]
MakeWorld = Callable[..., WorldState]
DAYS = Calendar(seasons=(Season("year", 100),), day_minutes=4, sunrise_minute=0, sunset_minute=2)


def villager(vid: str, **fields: object) -> Villager:
    return Villager(vid, vid.upper(), Coord(0, 0), **fields)  # type: ignore[arg-type]


def kid(**fields: object) -> Villager:
    return villager("k", adult=False, parents=("a", "b"), **fields)


def rejected(events: list[Event]) -> list[str]:
    return [e.data["reason"] for e in events if e.kind == "intent_rejected"]


@pytest.mark.req("REQ-SIM-016")
@pytest.mark.parametrize(
    "intent",
    [
        StartAction("k", "pick"),  # a labour action
        ProposeCouple("k", "a"),
        PlaceBuilding("k", "hut", Coord(2, 0)),
    ],
)
def test_children_cannot_do_adult_things(
    life: Registry, make_world: MakeWorld, intent: object
) -> None:
    """AC1 (engine part): children are limited to their intents and to light actions."""
    state = make_world(ROWS, [villager("a"), kid()])
    _, events = Engine(life).step(state, [intent])  # type: ignore[list-item]
    assert rejected(events) == ["too_young"]


@pytest.mark.req("REQ-SIM-016")
def test_children_eat_wait_and_try_light_work(life: Registry, make_world: MakeWorld) -> None:
    """AC1 (engine part): eating, waiting and light actions pass the child filter."""
    state = make_world(ROWS, [kid(inventory=Inventory({"berries": 1}), needs={"hunger": 50.0})])
    engine = Engine(life)
    _, events = engine.step(state, [Eat("k", "berries")])
    assert "ate" in [e.kind for e in events]
    _, events = engine.step(state, [Wait("k")])
    assert rejected(events) == []
    _, events = engine.step(state, [StartAction("k", "glean")])
    assert "too_young" not in rejected(events)  # rejected only for being away from a bush


@pytest.mark.req("REQ-SIM-016")
def test_an_adult_may_do_what_a_child_may_not(life: Registry, make_world: MakeWorld) -> None:
    """The filter is about age: the same labour intent from an adult is not `too_young`."""
    state = make_world(ROWS, [villager("a")])
    _, events = Engine(life).step(state, [StartAction("a", "pick")])
    assert "too_young" not in rejected(events)


@pytest.mark.req("REQ-SIM-016")
def test_a_child_comes_of_age_at_adult_age(life: Registry, make_world: MakeWorld) -> None:
    """AC2: at the first day boundary at or past adult_age_days the child becomes an adult."""
    config = EngineConfig(calendar=DAYS, adult_age_days=2, old_age_days=50, adult_model="base")
    state = make_world(ROWS, [villager("a", model="m1"), villager("b"), kid(born_tick=-5)])
    engine = Engine(life, config)
    for _ in range(3):  # ticks 0-2; at tick 3 (day boundary) the child is (3+5)//4 = 2 days old
        engine.step(state, [])
    assert state.villagers["k"].adult is False
    _, events = engine.step(state, [])
    assert [e.data for e in events if e.kind == "came_of_age"] == [{"villager": "k", "model": "m1"}]
    assert state.villagers["k"].adult is True
    assert state.villagers["k"].model == "m1"


@pytest.mark.req("REQ-SIM-016")
def test_inherit_picks_one_parents_model_with_the_seeded_rng(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: with two parent models the choice is a seeded draw; the same seed repeats it."""
    config = EngineConfig(calendar=DAYS, adult_age_days=1, old_age_days=50)
    picks = set()
    for seed in range(12):
        chosen = []
        for _ in range(2):
            state = make_world(
                ROWS,
                [villager("a", model="m1"), villager("b", model="m2"), kid(born_tick=-4)],
                seed=seed,
            )
            lifecycle.come_of_age(Engine(life, config).context, state, EventSink(0))
            chosen.append(state.villagers["k"].model)
        assert chosen[0] == chosen[1]
        picks.add(chosen[0])
    assert picks == {"m1", "m2"}


@pytest.mark.req("REQ-SIM-016")
def test_a_dead_parents_model_still_counts(life: Registry, make_world: MakeWorld) -> None:
    """AC2: a parent who died still passes on their model."""
    config = EngineConfig(calendar=DAYS, adult_age_days=1, old_age_days=50, adult_model="base")
    state = make_world(ROWS, [villager("b"), kid(born_tick=-4)])
    state.dead["a"] = Deceased("a", "A", None, -99, -1, "cold", (), "m1")
    lifecycle.come_of_age(Engine(life, config).context, state, EventSink(0))
    assert state.villagers["k"].model == "m1"


@pytest.mark.req("REQ-SIM-016")
@pytest.mark.parametrize(
    ("rule", "parent_model", "expected"),
    [("inherit", None, "base"), ("fixed", "m1", "base"), ("inherit", "m1", "m1")],
)
def test_the_model_rule_is_configurable(
    life: Registry,
    make_world: MakeWorld,
    rule: str,
    parent_model: str | None,
    expected: str,
) -> None:
    """AC2: `inherit` falls back to adult_model without parent models; `fixed` always uses it."""
    config = EngineConfig(
        calendar=DAYS, adult_age_days=1, old_age_days=50, model_rule=rule, adult_model="base"
    )
    state = make_world(ROWS, [villager("a", model=parent_model), kid(born_tick=-4)])
    lifecycle.come_of_age(Engine(life, config).context, state, EventSink(0))
    assert state.villagers["k"].model == expected


def event(kind: str, /, **data: object) -> Event:
    return Event(0, 0, kind, data)


@pytest.mark.req("REQ-SIM-016")
def test_children_witness_family_and_village_events(life: Registry, make_world: MakeWorld) -> None:
    """AC3: family events naming the child, a parent or a sibling, and every village event."""
    state = make_world(
        ROWS,
        [villager("a"), villager("x"), kid(), villager("s", adult=False, parents=("b", "z"))],
    )
    events = [
        event("died", villager="a", cause="cold", age_days=9),  # parent
        event("born", child="s", mother="b", father="z", sex="male"),  # sibling (and parent b)
        event("couple_formed", villagers=["x", "q"]),  # strangers
        event("died", villager="x", cause="raid", age_days=9),  # stranger
        event("building_completed", building="b0", kind="hut", destroyed={}),  # village
        event("ate", actor="k", item="berries", qty=1, nutrition=10.0, destroyed={}),  # not notable
    ]
    lifecycle.witness(Engine(life).context, state, events)
    assert [(r["kind"], r["data"].get("villager")) for r in state.villagers["k"].witnessed] == [
        ("died", "a"),
        ("born", None),
        ("building_completed", None),
    ]
    assert state.villagers["a"].witnessed == []  # adults do not collect childhood memories


@pytest.mark.req("REQ-SIM-016")
def test_witnessing_keeps_the_most_recent_records(life: Registry, make_world: MakeWorld) -> None:
    """AC3: at most childhood_memory_limit records are kept, newest last."""
    state = make_world(ROWS, [kid()])
    ctx = Engine(life, EngineConfig(childhood_memory_limit=2)).context
    lifecycle.witness(ctx, state, [event("building_completed", building=f"b{i}") for i in range(3)])
    assert [r["data"]["building"] for r in state.villagers["k"].witnessed] == ["b1", "b2"]
    ctx = Engine(life, EngineConfig(childhood_memory_limit=0)).context
    lifecycle.witness(ctx, state, [event("building_completed", building="b9")])
    assert state.villagers["k"].witnessed == []


@pytest.mark.req("REQ-SIM-016")
def test_a_newborn_witnesses_its_own_birth(life: Registry, make_world: MakeWorld) -> None:
    """AC3: witnessing runs after births in the tick, so a child remembers being born."""
    state = make_world(ROWS, [villager("a", partner="b"), villager("b", partner="a")])
    state.villagers["a"].pregnancy = Pregnancy("b", 0)
    _, events = Engine(life).step(state, [])
    child = next(e.data["child"] for e in events if e.kind == "born")
    assert [r["kind"] for r in state.villagers[child].witnessed] == ["born"]


@pytest.mark.req("REQ-SIM-016")
def test_coming_of_age_turns_witnessed_events_into_memories(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: the new adult's memories are seeded from what it witnessed."""
    config = EngineConfig(calendar=DAYS, adult_age_days=1, old_age_days=50, adult_model="base")
    records = [{"tick": 1, "kind": "died", "data": {"villager": "a"}}]
    state = make_world(ROWS, [kid(born_tick=-4, witnessed=list(records))])
    lifecycle.come_of_age(Engine(life, config).context, state, EventSink(0))
    assert state.villagers["k"].memories == records
    assert state.villagers["k"].witnessed == []


@pytest.mark.req("REQ-SIM-016")
def test_couple_handlers_also_refuse_children_directly(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: the couple handlers refuse a child on their own, behind the engine's filter."""
    state = make_world(ROWS, [villager("a"), kid()])
    state.proposals["a"] = Proposal("k", 99)
    ctx = Engine(life).context
    for handle, intent in [
        (lifecycle.propose_couple, ProposeCouple("k", "a")),
        (lifecycle.accept_couple, AcceptCouple("k", "a")),
    ]:
        sink = EventSink(0)
        handle(ctx, state, intent, sink)
        assert [(e.kind, e.data["reason"]) for e in sink.events] == [
            ("intent_rejected", "too_young")
        ]


@pytest.mark.req("REQ-SIM-016")
def test_witness_records_have_tick_kind_and_data(life: Registry, make_world: MakeWorld) -> None:
    """AC3: a witness record is {tick, kind, data}; `villagers` lists name family too."""
    state = make_world(ROWS, [kid()])
    lifecycle.witness(
        Engine(life).context,
        state,
        [Event(7, 0, "couple_formed", {"villagers": ["a", "q"]})],
    )
    assert state.villagers["k"].witnessed == [
        {"tick": 7, "kind": "couple_formed", "data": {"villagers": ["a", "q"]}}
    ]


@pytest.mark.req("REQ-SIM-016")
def test_a_dead_sibling_is_family(life: Registry, make_world: MakeWorld) -> None:
    """AC3: events naming a dead sibling are witnessed."""
    state = make_world(ROWS, [kid()])
    state.dead["s"] = Deceased("s", "S", None, -9, -1, "cold", ("a", "z"), None)
    lifecycle.witness(
        Engine(life).context, state, [event("died", villager="s", cause="x", age_days=1)]
    )
    assert len(state.villagers["k"].witnessed) == 1


@pytest.mark.req("REQ-SIM-016")
def test_an_adult_is_never_aged_again(life: Registry, make_world: MakeWorld) -> None:
    """AC2: an adult past adult age keeps its model and emits no came_of_age."""
    config = EngineConfig(calendar=DAYS, adult_age_days=1, old_age_days=99, adult_model="base")
    state = make_world(ROWS, [villager("a", model="m1", born_tick=-4)])
    sink = EventSink(0)
    lifecycle.come_of_age(Engine(life, config).context, state, sink)
    assert sink.events == []
    assert state.villagers["a"].model == "m1"


@pytest.mark.req("REQ-SIM-016")
def test_a_living_sibling_is_family(life: Registry, make_world: MakeWorld) -> None:
    """AC3: events naming a living sibling (sharing a parent) are witnessed."""
    state = make_world(ROWS, [kid(), villager("s", adult=False, parents=("b", "z"))])
    lifecycle.witness(
        Engine(life).context, state, [event("died", villager="s", cause="x", age_days=1)]
    )
    assert len(state.villagers["k"].witnessed) == 1
