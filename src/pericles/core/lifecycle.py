"""Ages, death and inheritance (REQ-SIM-017; ADR-0015 §5, §10). Couples, births and coming of
age are added in later tasks."""

from __future__ import annotations

from pericles.core import work
from pericles.core.buildings import Building, Ownership, storage_capacity
from pericles.core.context import Context
from pericles.core.events import EventSink
from pericles.core.inventory import EPSILON, Inventory, transfer
from pericles.core.state import Deceased, Villager, WorldState

OLD_AGE = "old_age"


def age_days(ctx: Context, state: WorldState, villager: Villager) -> int:
    return (state.tick - villager.born_tick) // ctx.config.calendar.ticks_per_day


def heirs(state: WorldState, vid: str) -> list[str]:
    """The living partner, then living children oldest first (ADR-0015 §10)."""
    villager = state.villagers[vid]
    order: list[str] = []
    if villager.partner is not None and villager.partner in state.villagers:
        order.append(villager.partner)
    children = [v for v in state.villagers.values() if vid in v.parents]
    order += [c.id for c in sorted(children, key=lambda c: (c.born_tick, c.id))]
    return order


def _room(ctx: Context, inventory: Inventory, item: str, qty: int) -> int:
    """How many of `item` (up to qty) fit within the carry limit."""
    weight = ctx.registry.items[item].weight
    if weight <= 0:
        return qty
    free = ctx.config.carry_limit - inventory.weight(ctx.registry)
    return max(0, min(qty, int((free + EPSILON) / weight)))


def _communal_stores(state: WorldState) -> list[Building]:
    return [
        state.buildings[bid]
        for bid in sorted(state.buildings)
        if state.buildings[bid].ownership.kind == "communal"
    ]


def _distribute(ctx: Context, state: WorldState, dead: Villager, sink: EventSink) -> None:
    registry = ctx.registry
    estate = dead.inventory
    order = heirs(state, dead.id)
    stores = _communal_stores(state)
    for item, held in sorted(estate.totals().items()):
        left = held
        for heir in order:
            qty = _room(ctx, state.villagers[heir].inventory, item, left)
            if qty:
                transfer(registry, estate, state.villagers[heir].inventory, item, qty)
                sink.emit("inherited", **{"from": dead.id}, to=heir, item=item, qty=qty)
                left -= qty
        for building in stores:
            space = storage_capacity(registry, building) - sum(building.storage.totals().values())
            qty = max(0, min(left, space))
            if qty:
                transfer(registry, estate, building.storage, item, qty)
                sink.emit(
                    "estate_stored", **{"from": dead.id}, building=building.id, item=item, qty=qty
                )
                left -= qty
    remainder = dict(sorted(estate.totals().items()))
    if remainder:
        for item, qty in remainder.items():
            estate.remove(item, qty)
        sink.emit("estate_lost", **{"from": dead.id}, destroyed=remainder)


def _successor(ownership: Ownership, dead: str, heir: str | None) -> Ownership:
    if dead not in ownership.owners:
        return ownership
    owners = set(ownership.owners) - {dead}
    if heir is not None:
        owners.add(heir)
    if len(owners) == 0:
        return Ownership("communal")
    if len(owners) == 1:
        return Ownership("personal", tuple(owners))
    return Ownership("shared", tuple(sorted(owners)))


def _reassign(state: WorldState, dead: str, heir: str | None, sink: EventSink) -> None:
    for bid in sorted(state.buildings):
        building = state.buildings[bid]
        before = building.ownership
        after = _successor(before, dead, heir)
        if after != before:
            building.ownership = after
            sink.emit(
                "ownership_changed",
                building=bid,
                from_kind=before.kind,
                from_owners=list(before.owners),
                to_kind=after.kind,
                to_owners=list(after.owners),
            )


def die(ctx: Context, state: WorldState, vid: str, cause: str, sink: EventSink) -> None:
    """The one death path: work, pregnancy, record, estate, property, links (ADR-0015 §10)."""
    villager = state.villagers[vid]
    work.interrupt(ctx, villager, sink, cause="engine", reason="death")
    if villager.pregnancy is not None:
        sink.emit("pregnancy_lost", mother=vid, father=villager.pregnancy.father)
        villager.pregnancy = None
    sink.emit("died", villager=vid, cause=cause, age_days=age_days(ctx, state, villager))
    order = heirs(state, vid)
    _distribute(ctx, state, villager, sink)
    _reassign(state, vid, order[0] if order else None, sink)
    for other in state.villagers.values():
        if other.partner == vid:
            other.partner = None
    state.proposals = {k: p for k, p in state.proposals.items() if vid not in (k, p.target)}
    del state.villagers[vid]
    state.dead[vid] = Deceased(
        id=vid,
        name=villager.name,
        sex=villager.sex,
        born_tick=villager.born_tick,
        died_tick=state.tick,
        cause=cause,
        parents=villager.parents,
        model=villager.model,
    )


def old_age_deaths(ctx: Context, state: WorldState, sink: EventSink) -> None:
    """The daily old-age roll (REQ-SIM-017 AC2); one draw per villager past old age, by id.

    A chance above 1 always kills, since the draw is below 1, so no explicit cap is needed.
    """
    config = ctx.config
    for vid in sorted(state.villagers):
        past = age_days(ctx, state, state.villagers[vid]) - config.old_age_days
        if past < 0:
            continue
        chance = config.old_age_death_chance * config.old_age_death_growth**past  # may exceed 1
        if state.rng.random() < chance:
            die(ctx, state, vid, OLD_AGE, sink)
