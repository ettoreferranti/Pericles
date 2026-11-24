"""Needs, eating, sleeping, shelter and health (REQ-SIM-012, REQ-SIM-003 AC2; ADR-0015 §1-§4)."""

from __future__ import annotations

from collections.abc import Callable

from pericles.core.buildings import building_tiles, near
from pericles.core.content.schema import NeedDef
from pericles.core.context import Context, reject
from pericles.core.events import EventSink
from pericles.core.intents import Eat, Intent, Sleep
from pericles.core.modifiers import resolve
from pericles.core.state import Activity, Villager, WorldState

MINUTES_PER_HOUR = 60
SLEEP = "sleep"


def per_tick(ctx: Context, per_hour: float) -> float:
    return per_hour * ctx.config.calendar.tick_minutes / MINUTES_PER_HOUR


RateTable = Callable[[Villager, NeedDef], float]


def rate_table(ctx: Context, state: WorldState) -> RateTable:
    """Need rates for this tick; cached by (need, traits) when no modifier names a villager.

    Modifiers apply in the order world, season, traits, as `resolve` keeps list order.
    """
    season = ctx.config.calendar.season_at(state.tick)
    shared = (*state.modifiers, *season.modifiers)
    personal = any(m.scope.villager is not None for m in shared)
    cache: dict[tuple[str, tuple[str, ...]], float] = {}

    def rate(villager: Villager, need: NeedDef) -> float:
        key = (need.id, villager.traits)
        if not personal and key in cache:
            return cache[key]
        modifiers = list(shared)
        for trait in villager.traits:
            modifiers.extend(ctx.traits[trait])
        value = resolve(
            modifiers,
            kind="need",
            ident=need.id,
            attribute="rate",
            base=need.rate_per_hour,
            tick=state.tick,
            villager=villager.id,
        ).value
        if not personal:
            cache[key] = value
        return value

    return rate


def need_rate(ctx: Context, state: WorldState, villager: Villager, need: NeedDef) -> float:
    """The need's per-hour rate after world, season and trait modifiers."""
    return rate_table(ctx, state)(villager, need)


def at_home(ctx: Context, state: WorldState, villager: Villager) -> bool:
    if villager.home is None:
        return False
    home = state.buildings.get(villager.home)
    return (
        home is not None
        and home.complete
        and near(villager.pos, building_tiles(home, ctx.registry))
    )


def sleeping(villager: Villager) -> bool:
    return villager.activity is not None and villager.activity.kind == SLEEP


def _hourly_change(
    ctx: Context, rate: RateTable, villager: Villager, need: NeedDef, home: bool
) -> float:
    config = ctx.config
    if need.relief == "sleep" and sleeping(villager):
        boost = config.home_sleep_multiplier if home else 1.0
        return -config.sleep_relief_per_hour * boost
    if need.relief == "shelter" and home:
        return -config.shelter_relief_per_hour
    return rate(villager, need)


def update_needs(ctx: Context, state: WorldState, sink: EventSink) -> list[tuple[str, str]]:
    """Advance every villager's needs and health; return (villager, cause) for the dying."""
    config = ctx.config
    needs = [ctx.registry.needs[k] for k in sorted(ctx.registry.needs)]
    dying: list[tuple[str, str]] = []
    rate = rate_table(ctx, state)
    for vid in sorted(state.villagers):
        villager = state.villagers[vid]
        home = at_home(ctx, state, villager)
        damage = 0.0
        causes: list[str] = []
        for need in needs:
            before = villager.needs.get(need.id, 0.0)
            change = per_tick(ctx, _hourly_change(ctx, rate, villager, need, home))
            level = min(need.critical, max(0.0, before + change))
            villager.needs[need.id] = level
            if level < need.critical:
                continue
            if before < need.critical:
                sink.emit("need_critical", actor=vid, need=need.id)
            if need.damage_per_hour > 0:
                assert need.death_cause is not None  # registry rule (ADR-0015 §2)
                damage += per_tick(ctx, need.damage_per_hour)
                causes.append(need.death_cause)
        if causes:
            villager.damage += damage
        else:
            regen = per_tick(ctx, config.health_regen_per_hour)
            villager.damage = max(0.0, villager.damage - regen)
        if causes and villager.damage >= config.max_health:
            dying.append((vid, causes[0]))
        elif sleeping(villager) and all(
            villager.needs[n.id] <= 0 for n in needs if n.relief == SLEEP
        ):
            villager.activity = None
            sink.emit("woke", actor=vid)
    return dying


def eat(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Eat)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    item = registry.items.get(intent.item)
    if item is None:
        return reject(sink, intent, "unknown_item")
    if item.nutrition <= 0:
        return reject(sink, intent, "not_food")
    if intent.qty <= 0:
        return reject(sink, intent, "bad_quantity")
    if villager.inventory.count(item.id) < intent.qty:
        return reject(sink, intent, "missing_items")
    villager.inventory.remove(item.id, intent.qty)
    relief = item.nutrition * intent.qty
    for need_id in sorted(registry.needs):
        if registry.needs[need_id].relief == "eat":
            villager.needs[need_id] = max(0.0, villager.needs.get(need_id, 0.0) - relief)
    sink.emit(
        "ate",
        actor=villager.id,
        item=item.id,
        qty=intent.qty,
        nutrition=relief,
        destroyed={item.id: intent.qty},
    )
    return None


def sleep(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Sleep)
    villager = state.villagers[intent.actor]
    if villager.path:
        villager.path = []
        villager.move_progress = 0.0
        sink.emit("stopped", actor=villager.id, at=list(villager.pos))
    home = villager.home if at_home(ctx, state, villager) else None
    villager.activity = Activity(SLEEP, SLEEP, home, 0.0, 0.0, 0.0)
    sink.emit("fell_asleep", actor=villager.id, at_home=home is not None)
