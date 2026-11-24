"""Needs, eating, sleeping, shelter and health (REQ-SIM-012, REQ-SIM-003 AC2; ADR-0015 §1-§4)."""

from __future__ import annotations

from collections.abc import Callable

from pericles.core.buildings import near_footprint
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
        and near_footprint(villager.pos, home.origin, ctx.registry.buildings[home.kind].footprint)
    )


def sleeping(villager: Villager) -> bool:
    return villager.activity is not None and villager.activity.kind == SLEEP


def update_needs(ctx: Context, state: WorldState, sink: EventSink) -> list[tuple[str, str]]:
    """Advance every villager's needs and health; return (villager, cause) for the dying.

    Per need and tick: sleep relieves a sleeper's sleep need (boosted at home), shelter
    relieves a villager at home, and otherwise the need grows at its modified rate.
    """
    config = ctx.config
    needs = [ctx.registry.needs[k] for k in sorted(ctx.registry.needs)]
    sleep_needs = [n.id for n in needs if n.relief == SLEEP]
    regen = per_tick(ctx, config.health_regen_per_hour)
    home_sleep = -config.sleep_relief_per_hour * config.home_sleep_multiplier
    away_sleep = -config.sleep_relief_per_hour
    shelter = -config.shelter_relief_per_hour
    tick_minutes = config.calendar.tick_minutes
    # (need, id, sleep relief?, shelter relief?, critical, damage per tick or None, cause)
    rows = [
        (
            n,
            n.id,
            n.relief == SLEEP,
            n.relief == "shelter",
            n.critical,
            per_tick(ctx, n.damage_per_hour) if n.damage_per_hour > 0 else None,
            n.death_cause,
        )
        for n in needs
    ]
    dying: list[tuple[str, str]] = []
    rate = rate_table(ctx, state)
    for vid in sorted(state.villagers):
        villager = state.villagers[vid]
        home = at_home(ctx, state, villager)
        asleep = sleeping(villager)
        levels = villager.needs
        damage = 0.0
        causes: list[str] = []
        for need, nid, by_sleep, by_shelter, critical, harm, cause in rows:
            if by_sleep and asleep:
                hourly = home_sleep if home else away_sleep
            elif by_shelter and home:
                hourly = shelter
            else:
                hourly = rate(villager, need)
            before = levels.get(nid, 0.0)
            level = before + hourly * tick_minutes / MINUTES_PER_HOUR
            level = level if level > 0.0 else 0.0  # max(0.0, level), without the call
            level = level if level < critical else critical  # min(critical, level)
            levels[nid] = level
            if level < critical:
                continue
            if before < critical:
                sink.emit("need_critical", actor=vid, need=nid)
            if harm is not None:
                assert cause is not None  # registry rule (ADR-0015 §2)
                damage += harm
                causes.append(cause)
        if causes:
            villager.damage += damage
        else:
            villager.damage = max(0.0, villager.damage - regen)
        if causes and villager.damage >= config.max_health:
            dying.append((vid, causes[0]))
        elif asleep and all(levels[n] <= 0 for n in sleep_needs):
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
