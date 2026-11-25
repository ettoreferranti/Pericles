import dataclasses
from collections.abc import Callable

import pytest

from pericles.core import life as life_rules
from pericles.core.buildings import Building, Ownership
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import Eat, Sleep, Wait
from pericles.core.inventory import Inventory
from pericles.core.modifiers import Modifier, Op, Scope, Target
from pericles.core.state import Activity, Villager, WorldState

ROWS = ["......", "......", "......"]
MakeWorld = Callable[..., WorldState]


ORIGIN = Coord(0, 0)


def ana(pos: Coord = ORIGIN, **fields: object) -> Villager:
    return Villager("a", "Ana", pos, **fields)  # type: ignore[arg-type]


def lodge(state: WorldState, owner: str = "a") -> Building:
    building = Building("b0", "lodge", Coord(2, 0), Ownership("personal", (owner,)), complete=True)
    state.buildings["b0"] = building
    return building


def kinds(events: list) -> list[str]:  # type: ignore[type-arg]
    return [e.kind for e in events]


@pytest.mark.req("REQ-SIM-012")
def test_needs_rise_by_their_rate_every_tick(life: Registry, make_world: MakeWorld) -> None:
    """AC1: hunger, fatigue and cold rise per tick at their rates (1 per tick in the life pack)."""
    state = make_world(ROWS, [ana()])
    engine = Engine(life)
    for _ in range(3):
        engine.step(state, [])
    assert state.villagers["a"].needs == {"cold": 3.0, "fatigue": 3.0, "hunger": 3.0}


@pytest.mark.req("REQ-SIM-012")
def test_need_rates_are_modified_by_traits_and_world_modifiers(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: rates are the modified rates: a hardy trait halves cold; a world modifier adds."""
    state = make_world(ROWS, [ana(traits=("hardy",))])
    state.modifiers = (Modifier(Target("need", "hunger"), "rate", Op.ADD, 60.0, "test"),)
    Engine(life).step(state, [])
    assert state.villagers["a"].needs["cold"] == 0.5
    assert state.villagers["a"].needs["hunger"] == 2.0


@pytest.mark.req("REQ-SIM-012")
def test_a_modifier_naming_one_villager_changes_only_its_rate(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: a villager-scoped modifier applies to that villager only, whoever is asked first."""
    personal = Modifier(Target("need", "hunger"), "rate", Op.ADD, 60.0, "test", Scope("b"))
    for first, second in (("a", "b"), ("b", "a")):
        state = make_world(ROWS, [ana(), Villager("b", "Bo", Coord(1, 0))])
        state.modifiers = (personal,)
        ctx = Engine(life).context
        rate = life_rules.rate_table(ctx, state)
        hunger = life.needs["hunger"]
        rates = {vid: rate(state.villagers[vid], hunger) for vid in (first, second)}
        assert rates == {"a": 60.0, "b": 120.0}


@pytest.mark.req("REQ-SIM-012")
def test_trait_modifiers_are_prepared_once_with_their_source(life: Registry) -> None:
    """AC1: each trait's modifiers are built once, credited to the trait (as `explain` shows)."""
    ctx = Engine(life).context
    hardy = ctx.traits["hardy"]
    assert hardy and all(m.source == "trait:hardy" for m in hardy)
    assert set(ctx.traits) == set(life.traits)


@pytest.mark.req("REQ-SIM-003")
def test_winter_multiplies_need_rates(life: Registry, make_world: MakeWorld) -> None:
    """AC2: in winter the food and warmth need rates are multiplied by the winter modifiers."""
    winter_mods = (
        Modifier(Target("need", "hunger"), "rate", Op.MUL, 1.5, "season:winter"),
        Modifier(Target("need", "cold"), "rate", Op.MUL, 4.0, "season:winter"),
    )
    calendar = Calendar(
        seasons=(Season("summer", 1), Season("winter", 1, modifiers=winter_mods)),
        day_minutes=2,
        sunrise_minute=0,
        sunset_minute=1,
    )
    state = make_world(ROWS, [ana()])
    engine = Engine(life, EngineConfig(calendar=calendar))
    engine.step(state, [])
    engine.step(state, [])  # day 0 (summer): +1, +1
    assert state.villagers["a"].needs["cold"] == 2.0
    engine.step(state, [])  # day 1 (winter): cold +4, hunger +1.5
    assert state.villagers["a"].needs["cold"] == 6.0
    assert state.villagers["a"].needs["hunger"] == 3.5
    assert state.villagers["a"].needs["fatigue"] == 3.0


@pytest.mark.req("REQ-SIM-012")
def test_needs_stop_at_critical_and_report_it_once(life: Registry, make_world: MakeWorld) -> None:
    """AC1: a need never passes its critical value; reaching it is an event, once."""
    state = make_world(ROWS, [ana(needs={"fatigue": 99.5})])
    engine = Engine(life)
    _, events = engine.step(state, [])
    assert state.villagers["a"].needs["fatigue"] == 100.0
    assert [e.data for e in events if e.kind == "need_critical"] == [
        {"actor": "a", "need": "fatigue"}
    ]
    _, events = engine.step(state, [])
    assert "need_critical" not in kinds(events)
    assert state.villagers["a"].needs["fatigue"] == 100.0


@pytest.mark.req("REQ-SIM-012")
def test_a_critical_damaging_need_costs_health(life: Registry, make_world: MakeWorld) -> None:
    """AC2: hunger at 100 loses health at the starvation rate (10 per tick in the life pack)."""
    state = make_world(ROWS, [ana(needs={"hunger": 100.0})])
    ctx = Engine(life).context
    assert life_rules.update_needs(ctx, state, _sink()) == []
    assert state.villagers["a"].damage == 10.0
    for _ in range(8):
        life_rules.update_needs(ctx, state, _sink())
    assert state.villagers["a"].damage == 90.0
    assert life_rules.update_needs(ctx, state, _sink()) == [("a", "starvation")]


@pytest.mark.req("REQ-SIM-012")
def test_cold_kills_with_cause_cold(life: Registry, make_world: MakeWorld) -> None:
    """AC2: cold works the same way, with cause `cold` (5 damage per tick)."""
    state = make_world(ROWS, [ana(needs={"cold": 100.0}, damage=95.0)])
    ctx = Engine(life).context
    assert life_rules.update_needs(ctx, state, _sink()) == [("a", "cold")]


@pytest.mark.req("REQ-SIM-012")
def test_with_two_lethal_needs_the_first_in_id_order_is_the_cause(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: damage adds up; the cause is the first damaging critical need by id (cold < hunger)."""
    state = make_world(ROWS, [ana(needs={"cold": 100.0, "hunger": 100.0}, damage=86.0)])
    ctx = Engine(life).context
    assert life_rules.update_needs(ctx, state, _sink()) == [("a", "cold")]
    assert state.villagers["a"].damage == 101.0


@pytest.mark.req("REQ-SIM-012")
def test_health_recovers_when_no_need_is_critical(life: Registry, make_world: MakeWorld) -> None:
    """AC2: without a critical need, damage heals at the regeneration rate, never below 0."""
    state = make_world(ROWS, [ana(damage=0.5, needs={"fatigue": 100.0})])
    ctx = Engine(life, EngineConfig(health_regen_per_hour=60.0)).context
    life_rules.update_needs(ctx, state, _sink())
    assert state.villagers["a"].damage == 0.0  # fatigue does no damage, so it heals


@pytest.mark.req("REQ-SIM-012")
def test_eating_reduces_hunger_by_nutrition(life: Registry, make_world: MakeWorld) -> None:
    """AC3: eating consumes food and lowers hunger by nutrition times quantity, never below 0."""
    state = make_world(ROWS, [ana(needs={"hunger": 25.0}, inventory=Inventory({"berries": 3}))])
    _, events = Engine(life).step(state, [Eat("a", "berries", 2)])
    villager = state.villagers["a"]
    assert villager.inventory.count("berries") == 1
    assert villager.needs["hunger"] == 6.0  # 25 - 20, then +1 for the tick
    ate = next(e for e in events if e.kind == "ate")
    assert ate.data == {
        "actor": "a",
        "item": "berries",
        "qty": 2,
        "nutrition": 20.0,
        "destroyed": {"berries": 2},
    }
    Engine(life).step(state, [Eat("a", "berries")])
    assert villager.needs["hunger"] == 1.0  # floored at 0, then +1


@pytest.mark.req("REQ-SIM-012")
@pytest.mark.parametrize(
    ("intent", "reason"),
    [
        (Eat("a", "stone"), "unknown_item"),
        (Eat("a", "wood"), "not_food"),
        (Eat("a", "berries", 0), "bad_quantity"),
        (Eat("a", "berries", 5), "missing_items"),
    ],
)
def test_bad_eat_intents_are_rejected(
    life: Registry, make_world: MakeWorld, intent: Eat, reason: str
) -> None:
    """AC3: only food the villager holds can be eaten; nothing is consumed otherwise."""
    state = make_world(ROWS, [ana(inventory=Inventory({"berries": 1, "wood": 1}))])
    _, events = Engine(life).step(state, [intent])
    assert [e.data["reason"] for e in events if e.kind == "intent_rejected"] == [reason]
    assert state.villagers["a"].inventory == Inventory({"berries": 1, "wood": 1})


@pytest.mark.req("REQ-SIM-012")
def test_sleeping_outdoors_restores_energy(life: Registry, make_world: MakeWorld) -> None:
    """AC3: while asleep fatigue falls by the sleep relief rate (1 per tick) instead of rising."""
    state = make_world(ROWS, [ana(needs={"fatigue": 10.0})])
    engine = Engine(life, EngineConfig(sleep_relief_per_hour=60.0))
    _, events = engine.step(state, [Sleep("a")])
    assert [e.data for e in events if e.kind == "fell_asleep"] == [{"actor": "a", "at_home": False}]
    assert state.villagers["a"].needs["fatigue"] == 9.0
    assert state.villagers["a"].activity is not None
    assert state.villagers["a"].activity.kind == "sleep"


@pytest.mark.req("REQ-SIM-012")
def test_sleeping_at_home_is_faster(life: Registry, make_world: MakeWorld) -> None:
    """AC3: sleeping in a house restores energy faster than sleeping outdoors."""
    state = make_world(ROWS, [ana(needs={"fatigue": 10.0}, home="b0", pos=Coord(1, 0))])
    lodge(state)
    engine = Engine(life, EngineConfig(sleep_relief_per_hour=60.0, home_sleep_multiplier=3.0))
    _, events = engine.step(state, [Sleep("a")])
    assert [e.data for e in events if e.kind == "fell_asleep"] == [{"actor": "a", "at_home": True}]
    assert state.villagers["a"].needs["fatigue"] == 7.0


@pytest.mark.req("REQ-SIM-012")
def test_sleep_ends_when_rested(life: Registry, make_world: MakeWorld) -> None:
    """AC3: a sleeper wakes by themselves once every sleep need is at 0."""
    state = make_world(ROWS, [ana(needs={"fatigue": 1.5})])
    engine = Engine(life, EngineConfig(sleep_relief_per_hour=60.0))
    engine.step(state, [Sleep("a")])
    _, events = engine.step(state, [])
    assert state.villagers["a"].needs["fatigue"] == 0.0
    assert "woke" in kinds(events)
    assert state.villagers["a"].activity is None
    engine.step(state, [])
    assert state.villagers["a"].needs["fatigue"] == 1.0  # awake again, so it rises


@pytest.mark.req("REQ-SIM-012")
def test_any_intent_wakes_a_sleeper(life: Registry, make_world: MakeWorld) -> None:
    """AC3: sleep is an activity, so the usual interruption rule ends it (ADR-0014 §3)."""
    state = make_world(ROWS, [ana(needs={"fatigue": 50.0})])
    engine = Engine(life)
    engine.step(state, [Sleep("a")])
    _, events = engine.step(state, [Wait("a")])
    interrupted = next(e for e in events if e.kind == "work_interrupted")
    assert interrupted.data["work"] == "sleep"
    assert state.villagers["a"].activity is None


@pytest.mark.req("REQ-SIM-012")
def test_sleeping_stops_movement(life: Registry, make_world: MakeWorld) -> None:
    """AC3: a villager who lies down stops walking."""
    state = make_world(ROWS, [ana(path=[Coord(1, 0), Coord(2, 0)])])
    _, events = Engine(life).step(state, [Sleep("a")])
    assert "stopped" in kinds(events)
    assert state.villagers["a"].path == []
    assert state.villagers["a"].pos == Coord(0, 0)


@pytest.mark.req("REQ-SIM-012")
def test_shelter_at_home_lowers_cold(life: Registry, make_world: MakeWorld) -> None:
    """AC1: at home, cold falls by the shelter rate instead of rising; away, it rises."""
    state = make_world(ROWS, [ana(needs={"cold": 10.0}, home="b0", pos=Coord(1, 0))])
    lodge(state)
    engine = Engine(life, EngineConfig(shelter_relief_per_hour=120.0))
    engine.step(state, [])
    assert state.villagers["a"].needs["cold"] == 8.0
    state.villagers["a"].pos = Coord(5, 2)
    engine.step(state, [])
    assert state.villagers["a"].needs["cold"] == 9.0


@pytest.mark.req("REQ-SIM-012")
def test_an_unfinished_or_missing_home_gives_no_shelter(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: only a completed home shelters."""
    state = make_world(ROWS, [ana(needs={"cold": 10.0}, home="b0", pos=Coord(1, 0))])
    lodge(state).complete = False
    ctx = Engine(life).context
    assert not life_rules.at_home(ctx, state, state.villagers["a"])
    state.villagers["a"].home = "b9"
    assert not life_rules.at_home(ctx, state, state.villagers["a"])


@pytest.mark.req("REQ-SIM-012")
@pytest.mark.parametrize(("complete", "kind"), [(True, "lodge"), (True, "cabin"), (False, "lodge")])
def test_needs_shelter_exactly_where_at_home_is_true(
    life: Registry, make_world: MakeWorld, complete: bool, kind: str
) -> None:
    """AC1: on every tile of the map, cold falls by the shelter rate exactly when `at_home`
    holds (next to or on a completed home, 2x2 or 1x1), and rises everywhere else."""
    state = make_world(ROWS, [ana(needs={"cold": 10.0}, home="b0")])
    house = lodge(state)
    house.complete, house.kind = complete, kind
    engine = Engine(life, EngineConfig(shelter_relief_per_hour=120.0))
    villager = state.villagers["a"]
    sheltered = []
    for x in range(len(ROWS[0])):
        for y in range(len(ROWS)):
            villager.pos, villager.needs["cold"] = Coord(x, y), 10.0
            home = life_rules.at_home(engine.context, state, villager)
            life_rules.update_needs(engine.context, state, _sink())
            assert (villager.needs["cold"] < 10.0) == home, (x, y)
            sheltered.append(home)
    assert any(sheltered) == complete


def test_per_tick_scales_by_tick_minutes(life: Registry) -> None:
    """Rates are per hour; a 5-minute tick takes a twelfth of the hourly rate."""
    calendar = Calendar(seasons=(Season("year", 1),), tick_minutes=5)
    ctx = Engine(life, EngineConfig(calendar=calendar)).context
    assert life_rules.per_tick(ctx, 60.0) == 5.0


@pytest.mark.req("REQ-SIM-012")
def test_a_villager_loaded_at_max_damage_without_a_critical_need_heals(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: death needs a critical damaging need; otherwise damage heals, even from the maximum."""
    state = make_world(ROWS, [ana(damage=100.0)])
    ctx = Engine(life, EngineConfig(health_regen_per_hour=60.0)).context
    assert life_rules.update_needs(ctx, state, _sink()) == []
    assert state.villagers["a"].damage == 99.0


def _hunger_modifier(scope: Scope) -> Modifier:
    return Modifier(Target("need", "hunger"), "rate", Op.ADD, 60.0, "test", scope)


@pytest.mark.req("REQ-SIM-012")
def test_a_villager_scoped_modifier_only_changes_that_villager(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: a modifier scoped to one villager leaves the others' need rates alone."""
    other = Villager("b", "Ben", Coord(1, 0))
    state = make_world(ROWS, [ana(), other])
    state.modifiers = (_hunger_modifier(Scope(villager="b")),)
    Engine(life).step(state, [])
    assert state.villagers["a"].needs["hunger"] == 1.0
    assert state.villagers["b"].needs["hunger"] == 2.0


@pytest.mark.req("REQ-SIM-012")
def test_an_expiring_modifier_stops_changing_need_rates(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC1: a modifier lasting until tick 1 acts on tick 0 only."""
    state = make_world(ROWS, [ana()])
    state.modifiers = (_hunger_modifier(Scope(until_tick=1)),)
    engine = Engine(life)
    engine.step(state, [])
    assert state.villagers["a"].needs["hunger"] == 2.0
    engine.step(state, [])
    assert state.villagers["a"].needs["hunger"] == 3.0


@pytest.mark.req("REQ-SIM-012")
def test_a_slightly_damaging_critical_need_still_costs_health(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC2: any positive damage rate hurts, however small (0.6 per hour here)."""
    hunger = life.needs["hunger"].model_copy(update={"damage_per_hour": 0.6})
    registry = dataclasses.replace(life, needs={**life.needs, "hunger": hunger})
    state = make_world(ROWS, [ana(needs={"hunger": 100.0})])
    life_rules.update_needs(Engine(registry).context, state, _sink())
    assert state.villagers["a"].damage == pytest.approx(0.01)


def _with_nutrition(registry: Registry, nutrition: float) -> Registry:
    berries = registry.items["berries"].model_copy(update={"nutrition": nutrition})
    return dataclasses.replace(registry, items={**registry.items, "berries": berries})


@pytest.mark.req("REQ-SIM-012")
@pytest.mark.parametrize("nutrition", [0.5, 1.0])
def test_any_positive_nutrition_is_food_and_eating_with_no_hunger_yet_stays_at_zero(
    life: Registry, make_world: MakeWorld, nutrition: float
) -> None:
    """AC3: nutrition above 0 makes food; no recorded hunger ends at 0."""
    state = make_world(ROWS, [ana(inventory=Inventory({"berries": 1}))])
    _, events = Engine(_with_nutrition(life, nutrition)).step(state, [Eat("a", "berries")])
    assert [e.data["nutrition"] for e in events if e.kind == "ate"] == [nutrition]
    assert state.villagers["a"].needs["hunger"] == 1.0  # 0 after eating, then +1 for the tick


@pytest.mark.req("REQ-SIM-012")
def test_lying_down_stops_a_walk_and_clears_progress(life: Registry, make_world: MakeWorld) -> None:
    """AC3: sleeping mid-walk reports where the villager stopped and drops partial progress."""
    state = make_world(ROWS, [ana(path=[Coord(1, 0)], move_progress=0.5)])
    _, events = Engine(life).step(state, [Sleep("a")])
    stopped = next(e for e in events if e.kind == "stopped")
    assert stopped.data == {"actor": "a", "at": [0, 0]}
    assert state.villagers["a"].move_progress == 0.0


@pytest.mark.req("REQ-SIM-012")
def test_the_sleep_activity_records_the_home_only_when_at_home(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: sleep is a zero-work activity targeting the home when sleeping there, else nothing."""
    state = make_world(ROWS, [ana(needs={"fatigue": 50.0}, home="b0", pos=Coord(5, 2))])
    lodge(state)
    engine = Engine(life)
    _, events = engine.step(state, [Sleep("a")])
    assert [e.data["at_home"] for e in events if e.kind == "fell_asleep"] == [False]
    assert state.villagers["a"].activity == Activity("sleep", "sleep", None, 0.0, 0.0, 0.0)
    state.villagers["a"].activity = None
    state.villagers["a"].pos = Coord(1, 0)
    engine.step(state, [Sleep("a")])
    assert state.villagers["a"].activity == Activity("sleep", "sleep", "b0", 0.0, 0.0, 0.0)


@pytest.mark.req("REQ-SIM-012")
def test_waking_names_the_villager(life: Registry, make_world: MakeWorld) -> None:
    """AC3: the woke event carries the actor."""
    state = make_world(ROWS, [ana(needs={"fatigue": 0.5})])
    engine = Engine(life, EngineConfig(sleep_relief_per_hour=60.0))
    _, events = engine.step(state, [Sleep("a")])  # 0.5 - 1 floors at 0: awake again at once
    assert [e.data for e in events if e.kind == "woke"] == [{"actor": "a"}]


@pytest.mark.req("REQ-SIM-012")
def test_a_sleeper_does_not_stop_others_work_progressing(
    life: Registry, make_world: MakeWorld
) -> None:
    """AC3: sleep makes no work progress, and the villagers after the sleeper still progress."""
    worker = Villager(
        "b", "Ben", Coord(1, 0), activity=Activity("action", "glean", None, 5.0, 0.0, 1.0)
    )
    state = make_world(ROWS, [ana(needs={"fatigue": 50.0}), worker])
    Engine(life).step(state, [Sleep("a")])
    assert state.villagers["a"].activity == Activity("sleep", "sleep", None, 0.0, 0.0, 0.0)
    assert state.villagers["b"].activity is not None
    assert state.villagers["b"].activity.done == 1.0


def _sink() -> EventSink:
    return EventSink(0)
