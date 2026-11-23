from collections.abc import Callable

import pytest

from pericles.core import lifecycle
from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.invariants import check_state
from pericles.core.inventory import Inventory, Tool
from pericles.core.state import Activity, Pregnancy, Proposal, Villager, WorldState

ROWS = ["......", "......", "......"]
MakeWorld = Callable[..., WorldState]
SHORT_DAYS = Calendar(
    seasons=(Season("year", 10),), day_minutes=4, sunrise_minute=0, sunset_minute=2
)


def person(vid: str, **fields: object) -> Villager:
    return Villager(vid, vid.upper(), Coord(0, 0), **fields)  # type: ignore[arg-type]


def kill(
    life: Registry, state: WorldState, vid: str, cause: str = "raid", **config: object
) -> list[Event]:
    sink = EventSink(state.tick)
    Engine(life, EngineConfig(**config)).kill(state, vid, cause, sink)  # type: ignore[arg-type]
    return sink.events


def store(state: WorldState, bid: str, ownership: Ownership, kind: str = "lodge") -> Building:
    building = Building(bid, kind, Coord(3, 0), ownership, complete=True)
    state.buildings[bid] = building
    return building


@pytest.mark.req("REQ-SIM-017")
@pytest.mark.parametrize("cause", ["starvation", "cold", "old_age", "raid", "epidemic"])
def test_the_death_event_records_the_cause(
    life: Registry, make_world: MakeWorld, cause: str
) -> None:
    """AC1: every cause reaches the `died` event; the villager moves to the dead."""
    state = make_world(ROWS, [person("a", born_tick=-8640)])
    events = kill(life, state, "a", cause)
    died = next(e for e in events if e.kind == "died")
    assert died.data == {"villager": "a", "cause": cause, "age_days": 6}
    assert "a" not in state.villagers
    assert state.dead["a"].cause == cause
    assert state.dead["a"].died_tick == state.tick


@pytest.mark.req("REQ-SIM-017")
def test_starvation_kills_through_the_engine(life: Registry, make_world: MakeWorld) -> None:
    """AC1: a starving villager dies in the tick their health runs out, cause starvation."""
    state = make_world(ROWS, [person("a", needs={"hunger": 100.0}, damage=85.0)])
    engine = Engine(life)
    _, events = engine.step(state, [])
    assert "died" not in [e.kind for e in events]
    _, events = engine.step(state, [])
    assert [e.data["cause"] for e in events if e.kind == "died"] == ["starvation"]
    assert "a" not in state.villagers


@pytest.mark.req("REQ-SIM-017")
def test_old_age_death_follows_the_curve(life: Registry, make_world: MakeWorld) -> None:
    """AC2: past old age the daily chance is chance x growth^(days past).

    A chance of 1 or more always kills.
    """
    config = EngineConfig(
        calendar=SHORT_DAYS,
        adult_age_days=1,
        old_age_days=2,
        old_age_death_chance=0.25,
        old_age_death_growth=2.0,
    )
    ctx = Engine(life, config).context
    state = make_world(ROWS, [person("young", born_tick=0), person("old", born_tick=-16)])
    # "old" is 4 days old at tick 0: 2 days past old age, chance 0.25 x 2^2 = 1.0.
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert "old" not in state.villagers
    assert state.dead["old"].cause == "old_age"
    assert "young" in state.villagers


@pytest.mark.req("REQ-SIM-017")
def test_old_age_chance_is_drawn_from_the_seeded_rng(life: Registry, make_world: MakeWorld) -> None:
    """AC2: with chance 0 nobody dies; the same seed gives the same deaths."""
    config = EngineConfig(
        calendar=SHORT_DAYS, adult_age_days=1, old_age_days=1, old_age_death_chance=0.5
    )
    ctx = Engine(life, config).context
    survivors = []
    for _ in range(2):
        state = make_world(ROWS, [person(f"v{i}", born_tick=-8) for i in range(20)], seed=3)
        lifecycle.old_age_deaths(ctx, state, EventSink(0))
        survivors.append(sorted(state.villagers))
    assert survivors[0] == survivors[1]
    assert 0 < len(survivors[0]) < 20
    never = EngineConfig(
        calendar=SHORT_DAYS, adult_age_days=1, old_age_days=1, old_age_death_chance=0.0
    )
    state = make_world(ROWS, [person("v0", born_tick=-8)])
    lifecycle.old_age_deaths(Engine(life, never).context, state, EventSink(0))
    assert "v0" in state.villagers


@pytest.mark.req("REQ-SIM-017")
def test_old_age_deaths_happen_on_the_day_boundary(life: Registry, make_world: MakeWorld) -> None:
    """AC2: the engine rolls old-age deaths once per day, at the last tick of the day."""
    config = EngineConfig(
        calendar=SHORT_DAYS, adult_age_days=1, old_age_days=1, old_age_death_chance=1.0
    )
    state = make_world(ROWS, [person("old", born_tick=-8)])
    engine = Engine(life, config)
    for _ in range(3):
        engine.step(state, [])
    assert "old" in state.villagers
    _, events = engine.step(state, [])
    assert [e.data["cause"] for e in events if e.kind == "died"] == ["old_age"]


@pytest.mark.req("REQ-SIM-017")
def test_heirs_are_partner_then_children_oldest_first(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: the inheritance order is the partner, then children by birth."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b"),
            person("b", partner="a"),
            person("c2", parents=("a", "b"), born_tick=50),
            person("c1", parents=("a", "z"), born_tick=10),
            person("c0", parents=("a", "b"), born_tick=50),
            person("x"),
        ],
    )
    assert lifecycle.heirs(state, "a") == ["b", "c1", "c0", "c2"]
    assert lifecycle.heirs(state, "x") == []


@pytest.mark.req("REQ-SIM-017")
def test_the_estate_goes_to_heirs_within_their_carry_limit(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: each heir takes what they can carry; the rest goes on to the next heir."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b", inventory=Inventory({"wood": 4})),  # wood weighs 2
            person("b", partner="a", inventory=Inventory({"plank": 2})),  # planks weigh 1
            person("c", parents=("a", "b")),
        ],
    )
    events = kill(life, state, "a", carry_limit=7.0)
    assert [(e.data["to"], e.data["qty"]) for e in events if e.kind == "inherited"] == [
        ("b", 2),
        ("c", 2),
    ]
    assert state.villagers["b"].inventory.count("wood") == 2
    assert state.villagers["c"].inventory.count("wood") == 2
    assert state.villagers["b"].partner is None


@pytest.mark.req("REQ-SIM-017")
def test_room_tolerates_float_weights(life: Registry, make_world: MakeWorld) -> None:
    """AC3: ten seeds (0.1 each) fit a carry limit of 1.0 despite float error."""
    state = make_world(
        ROWS,
        [person("a", partner="b", inventory=Inventory({"seed": 10})), person("b", partner="a")],
    )
    kill(life, state, "a", carry_limit=1.0)
    assert state.villagers["b"].inventory.count("seed") == 10


@pytest.mark.req("REQ-SIM-017")
def test_what_heirs_cannot_carry_goes_to_communal_stores_then_is_lost(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: then communal, by store id and within capacity; the remainder is destroyed, recorded."""
    state = make_world(ROWS, [person("a", inventory=Inventory({"berries": 70}))])
    store(state, "b1", Ownership("communal"))
    store(state, "b0", Ownership("communal")).storage.add(life, "berries", 30)
    store(state, "b2", Ownership("personal", ("q",)))
    events = kill(life, state, "a", carry_limit=100.0)
    stored = [(e.data["building"], e.data["qty"]) for e in events if e.kind == "estate_stored"]
    assert stored == [("b0", 20), ("b1", 50)]
    assert "estate_lost" not in [e.kind for e in events]
    assert state.buildings["b2"].storage.count("berries") == 0


@pytest.mark.req("REQ-SIM-017")
def test_an_estate_too_big_for_everyone_is_destroyed_with_an_event(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: nothing vanishes silently; conservation holds through the death."""
    state = make_world(ROWS, [person("a", inventory=Inventory({"berries": 70}))])
    store(state, "b0", Ownership("communal"))
    events = kill(life, state, "a")
    assert [e.data for e in events if e.kind == "estate_lost"] == [
        {"from": "a", "destroyed": {"berries": 20}}
    ]
    assert check_state(Engine(life).context, state) == []


@pytest.mark.req("REQ-SIM-017")
def test_no_estate_lost_event_when_nothing_is_lost(life: Registry, make_world: MakeWorld) -> None:
    """AC3: `estate_lost` appears only when something is destroyed."""
    state = make_world(ROWS, [person("a")])
    assert "estate_lost" not in [e.kind for e in kill(life, state, "a")]


@pytest.mark.req("REQ-SIM-017")
def test_reserved_work_inputs_return_to_the_estate(life: Registry, make_world: MakeWorld) -> None:
    """AC3: dying mid-work interrupts it first, so reserved inputs are inherited, not lost."""
    state = make_world(ROWS, [person("a", partner="b"), person("b", partner="a")])
    villager = state.villagers["a"]
    villager.inventory = Inventory({"wood": 1})
    villager.activity = Activity(
        "recipe", "r", "b9", 10.0, 0.0, 1.0, reserved=Inventory({"plank": 2})
    )
    events = kill(life, state, "a")
    kinds = [e.kind for e in events]
    assert kinds.index("work_interrupted") < kinds.index("died") < kinds.index("inherited")
    interrupted = next(e for e in events if e.kind == "work_interrupted")
    assert (interrupted.data["cause"], interrupted.data["reason"]) == ("engine", "death")
    assert state.villagers["b"].inventory == Inventory({"plank": 2, "wood": 1})


@pytest.mark.req("REQ-SIM-017")
def test_a_sleeping_villager_dies_cleanly(life: Registry, make_world: MakeWorld) -> None:
    """AC3: death during sleep ends the sleep, then the usual death rules apply."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b", inventory=Inventory({"wood": 1})),
            person("b", partner="a"),
        ],
    )
    state.villagers["a"].activity = Activity("sleep", "sleep", None, 0.0, 0.0, 0.0)
    events = kill(life, state, "a")
    interrupted = next(e for e in events if e.kind == "work_interrupted")
    assert interrupted.data["work"] == "sleep"
    assert "a" not in state.villagers
    assert state.villagers["b"].inventory.count("wood") == 1
    assert check_state(Engine(life).context, state) == []


@pytest.mark.req("REQ-SIM-017")
def test_a_sleeping_villager_starves_through_the_engine(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: a villager asleep when their health runs out dies, and the engine carries on."""
    state = make_world(ROWS, [person("a", needs={"hunger": 100.0}, damage=99.9), person("b")])
    state.villagers["a"].activity = Activity("sleep", "sleep", None, 0.0, 0.0, 0.0)
    engine = Engine(life, EngineConfig(debug_invariants=True))
    _, events = engine.step(state, [])
    assert [e.data["cause"] for e in events if e.kind == "died"] == ["starvation"]
    engine.step(state, [])
    assert sorted(state.villagers) == ["b"]


@pytest.mark.req("REQ-SIM-017")
def test_tools_keep_their_durability_through_inheritance(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: an heir receives the very tool instances, worn state intact."""
    state = make_world(
        ROWS,
        [
            person(
                "a",
                partner="b",
                inventory=Inventory(tools=[Tool("axe", 1), Tool("axe", 3), Tool("hammer", 2)]),
            ),
            person("b", partner="a"),
        ],
    )
    kill(life, state, "a", carry_limit=100.0)
    assert state.villagers["b"].inventory.tools == [
        Tool("axe", 1),
        Tool("axe", 3),
        Tool("hammer", 2),
    ]
    assert check_state(Engine(life).context, state) == []


@pytest.mark.req("REQ-SIM-017")
def test_tools_stored_in_a_communal_building_keep_their_durability(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: tools with no heir go to a communal store, durability intact."""
    state = make_world(ROWS, [person("a", inventory=Inventory(tools=[Tool("axe", 1)]))])
    building = store(state, "b0", Ownership("communal"))
    kill(life, state, "a")
    assert building.storage.tools == [Tool("axe", 1)]


@pytest.mark.req("REQ-SIM-017")
@pytest.mark.parametrize(
    ("before", "heir_list", "after"),
    [
        (Ownership("personal", ("a",)), ["b"], Ownership("personal", ("b",))),
        (Ownership("personal", ("a",)), [], Ownership("communal")),
        (Ownership("shared", ("a", "q")), ["b"], Ownership("shared", ("b", "q"))),
        (Ownership("shared", ("a", "b")), ["b"], Ownership("personal", ("b",))),
        (Ownership("shared", ("a", "q")), [], Ownership("personal", ("q",))),
        (Ownership("communal"), ["b"], Ownership("communal")),
        (Ownership("personal", ("q",)), ["b"], Ownership("personal", ("q",))),
    ],
)
def test_property_passes_by_the_inheritance_rule(
    life: Registry,
    make_world: MakeWorld,
    before: Ownership,
    heir_list: list[str],
    after: Ownership,
) -> None:
    """AC3: buildings pass to the first heir, or become communal; no owner is ever dead."""
    people = [person("a"), person("q")]
    if heir_list:
        people[0] = person("a", partner="b")
        people.append(person("b", partner="a"))
    state = make_world(ROWS, people)
    store(state, "b0", before)
    events = kill(life, state, "a")
    assert state.buildings["b0"].ownership == after
    changed = [e.data for e in events if e.kind == "ownership_changed"]
    assert len(changed) == (0 if before == after else 1)


@pytest.mark.req("REQ-SIM-017")
def test_death_ends_a_pregnancy_and_open_proposals(life: Registry, make_world: MakeWorld) -> None:
    """AC3: a dying mother loses the pregnancy; proposals to or from the dead are dropped."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b", pregnancy=Pregnancy("b", 99)),
            person("b", partner="a"),
            person("c"),
            person("d"),
        ],
    )
    state.proposals = {"c": Proposal("a", 50), "a": Proposal("d", 50), "d": Proposal("c", 50)}
    events = kill(life, state, "a")
    assert [e.data for e in events if e.kind == "pregnancy_lost"] == [
        {"mother": "a", "father": "b"}
    ]
    assert state.proposals == {"d": Proposal("c", 50)}


@pytest.mark.req("REQ-SIM-017")
def test_two_deaths_in_one_tick_both_resolve(life: Registry, make_world: MakeWorld) -> None:
    """AC3: when both partners starve on the same tick, the second's estate goes to their child."""
    state = make_world(
        ROWS,
        [
            person(
                "a",
                partner="b",
                needs={"hunger": 100.0},
                damage=95.0,
                inventory=Inventory({"wood": 1}),
            ),
            person("b", partner="a", needs={"hunger": 100.0}, damage=95.0),
            person("c", parents=("a", "b")),
        ],
    )
    _, events = Engine(life, EngineConfig(debug_invariants=True)).step(state, [])
    assert [e.data["villager"] for e in events if e.kind == "died"] == ["a", "b"]
    assert state.villagers["c"].inventory.count("wood") == 1
    assert sorted(state.dead) == ["a", "b"]


def test_age_days_counts_whole_days(life: Registry, make_world: MakeWorld) -> None:
    """Age is whole days since birth (ADR-0015 §5)."""
    ctx = Engine(life, EngineConfig(calendar=SHORT_DAYS)).context
    state = make_world(ROWS, [person("a", born_tick=-9)])
    assert lifecycle.age_days(ctx, state, state.villagers["a"]) == 2


class FixedRng:
    """Stands in for the world's rng; every draw returns the same value."""

    def __init__(self, value: float) -> None:
        self.value = value

    def random(self) -> float:
        return self.value


def old_age_config(**fields: object) -> EngineConfig:
    base: dict[str, object] = {"calendar": SHORT_DAYS, "adult_age_days": 1, "old_age_days": 2}
    return EngineConfig(**(base | fields))  # type: ignore[arg-type]


@pytest.mark.req("REQ-SIM-017")
def test_old_age_chance_multiplies_by_growth_per_day_past(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: two days past old age the chance is 0.1 x 1.5^2 = 0.225, not 0.1 x 1.5 x 2."""
    ctx = Engine(life, old_age_config(old_age_death_chance=0.1, old_age_death_growth=1.5)).context
    state = make_world(ROWS, [person("a", born_tick=-16)])
    state.rng = FixedRng(0.25)  # type: ignore[assignment]
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert "a" in state.villagers
    state.rng = FixedRng(0.2)  # type: ignore[assignment]
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert "a" not in state.villagers


@pytest.mark.req("REQ-SIM-017")
def test_old_age_starts_on_the_old_age_day_and_a_draw_equal_to_the_chance_survives(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: exactly at old age the chance is the base chance; the draw must be below it."""
    ctx = Engine(life, old_age_config(old_age_death_chance=0.5, old_age_death_growth=1.0)).context
    state = make_world(ROWS, [person("a", born_tick=-8)])  # 2 days old: 0 days past
    state.rng = FixedRng(0.5)  # type: ignore[assignment]
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert "a" in state.villagers
    state.rng = FixedRng(0.25)  # type: ignore[assignment]
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert "a" not in state.villagers


@pytest.mark.req("REQ-SIM-017")
def test_the_old_age_roll_skips_the_young_and_still_reaches_later_villagers(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: a young villager earlier in id order does not stop the roll for an old one."""
    ctx = Engine(life, old_age_config(old_age_death_chance=1.0)).context
    state = make_world(ROWS, [person("a", born_tick=0), person("b", born_tick=-16)])
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert sorted(state.villagers) == ["a"]


@pytest.mark.req("REQ-SIM-017")
def test_the_death_record_keeps_lineage_and_model(life: Registry, make_world: MakeWorld) -> None:
    """AC1: the dead are remembered with name, sex, birth, parents and model."""
    state = make_world(
        ROWS,
        [person("a", sex="f", born_tick=-5, parents=("p", "q"), model="m1")],
    )
    kill(life, state, "a", "cold")
    record = state.dead["a"]
    assert (record.id, record.name, record.sex, record.born_tick) == ("a", "A", "f", -5)
    assert (record.parents, record.model, record.cause) == (("p", "q"), "m1", "cold")


@pytest.mark.req("REQ-SIM-017")
def test_a_dangling_partner_is_not_an_heir(life: Registry, make_world: MakeWorld) -> None:
    """AC3: a partner id that is not a living villager is skipped."""
    state = make_world(ROWS, [person("a", partner="gone")])
    assert lifecycle.heirs(state, "a") == []


@pytest.mark.req("REQ-SIM-017")
def test_inheritance_and_storage_events_carry_their_full_data(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: `inherited` and `estate_stored` name source, destination, item and quantity."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b", inventory=Inventory({"berries": 12})),
            person("b", partner="a"),
        ],
    )
    store(state, "b0", Ownership("communal"))
    events = kill(life, state, "a", carry_limit=3.0)
    assert [e.data for e in events if e.kind == "inherited"] == [
        {"from": "a", "to": "b", "item": "berries", "qty": 6}
    ]
    assert [e.data for e in events if e.kind == "estate_stored"] == [
        {"from": "a", "building": "b0", "item": "berries", "qty": 6}
    ]


@pytest.mark.req("REQ-SIM-017")
def test_ownership_changed_event_carries_full_data(life: Registry, make_world: MakeWorld) -> None:
    """AC3: the event names the building and both the old and new ownership."""
    state = make_world(ROWS, [person("a", partner="b"), person("b", partner="a"), person("q")])
    store(state, "b0", Ownership("shared", ("a", "q")))
    events = kill(life, state, "a")
    assert [e.data for e in events if e.kind == "ownership_changed"] == [
        {
            "building": "b0",
            "from_kind": "shared",
            "from_owners": ["a", "q"],
            "to_kind": "shared",
            "to_owners": ["b", "q"],
        }
    ]


@pytest.mark.req("REQ-SIM-017")
def test_weightless_items_ignore_the_carry_limit_and_light_ones_do_not(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: tokens weigh nothing so all pass; seeds (0.1) are limited to what fits."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b", inventory=Inventory({"token": 5, "seed": 10})),
            person("b", partner="a"),
        ],
    )
    events = kill(life, state, "a", carry_limit=0.5)
    inherited = {e.data["item"]: e.data["qty"] for e in events if e.kind == "inherited"}
    assert inherited == {"seed": 5, "token": 5}
    assert [e.data["destroyed"] for e in events if e.kind == "estate_lost"] == [{"seed": 5}]


@pytest.mark.req("REQ-SIM-017")
def test_only_complete_communal_stores_with_room_take_the_estate(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: private, unfinished and full stores are skipped; later stores take the overflow."""
    state = make_world(ROWS, [person("a", inventory=Inventory({"berries": 100}))])
    store(state, "b0", Ownership("communal")).storage.add(life, "berries", 50)  # full
    store(state, "b1", Ownership("personal", ("q",)))
    unfinished = store(state, "b2", Ownership("communal"))
    unfinished.complete = False
    store(state, "b3", Ownership("communal"))
    store(state, "b4", Ownership("communal"))
    events = kill(life, state, "a", carry_limit=100.0)
    stored = [(e.data["building"], e.data["qty"]) for e in events if e.kind == "estate_stored"]
    assert stored == [("b3", 50), ("b4", 50)]
    assert state.buildings["b0"].storage.count("berries") == 50
    assert state.buildings["b1"].storage.count("berries") == 0
    assert "estate_lost" not in [e.kind for e in events]


@pytest.mark.req("REQ-SIM-017")
def test_a_dying_pregnant_villager_is_left_without_a_pregnancy(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: the pregnancy is cleared, not just reported."""
    state = make_world(ROWS, [person("a", pregnancy=Pregnancy("b", 99)), person("b")])
    villager = state.villagers["a"]
    kill(life, state, "a")
    assert villager.pregnancy is None


@pytest.mark.req("REQ-SIM-017")
def test_only_the_dead_villagers_partner_is_unpaired(life: Registry, make_world: MakeWorld) -> None:
    """AC3: others' partner links are untouched; the dead's partner is freed."""
    state = make_world(
        ROWS,
        [
            person("a", partner="b"),
            person("b", partner="a"),
            person("c", partner="d"),
            person("d", partner="c"),
            person("e"),
        ],
    )
    kill(life, state, "a")
    partners = {vid: v.partner for vid, v in state.villagers.items()}
    assert partners == {"b": None, "c": "d", "d": "c", "e": None}


@pytest.mark.req("REQ-SIM-017")
def test_a_stored_estate_is_not_stored_again_in_the_next_store(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: what the first store takes is no longer left for the second."""
    state = make_world(ROWS, [person("a", inventory=Inventory({"berries": 30}))])
    store(state, "b0", Ownership("communal"))
    second = store(state, "b1", Ownership("communal"))
    events = kill(life, state, "a", carry_limit=100.0)
    assert [(e.data["building"], e.data["qty"]) for e in events if e.kind == "estate_stored"] == [
        ("b0", 30)
    ]
    assert second.storage.count("berries") == 0


@pytest.mark.req("REQ-SIM-017")
def test_chance_zero_draws_nothing_however_old(life: Registry, make_world: MakeWorld) -> None:
    """AC2: with chance 0 nobody dies, nothing overflows and the rng is untouched."""
    config = EngineConfig(
        calendar=SHORT_DAYS,
        adult_age_days=1,
        old_age_days=1,
        old_age_death_chance=0.0,
        old_age_death_growth=2.0,
    )
    ctx = Engine(life, config).context
    state = make_world(ROWS, [person("old", born_tick=-4 * 100000)])
    before = state.rng.getstate()
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert "old" in state.villagers
    assert state.rng.getstate() == before


@pytest.mark.req("REQ-SIM-017")
def test_a_huge_chance_power_means_certain_death(life: Registry, make_world: MakeWorld) -> None:
    """AC2: growth^(days past) too large for a float still kills, without crashing."""
    config = EngineConfig(
        calendar=SHORT_DAYS,
        adult_age_days=1,
        old_age_days=1,
        old_age_death_chance=0.001,
        old_age_death_growth=2.0,
    )
    ctx = Engine(life, config).context
    state = make_world(ROWS, [person("old", born_tick=-4 * 5000)])
    lifecycle.old_age_deaths(ctx, state, EventSink(0))
    assert state.dead["old"].cause == "old_age"
