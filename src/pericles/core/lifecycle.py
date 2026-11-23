"""Ages, death, inheritance, homes, couples, conception and births, and children's witnessing and
coming of age (REQ-SIM-016, REQ-SIM-017; ADR-0015 §5, §9, §10)."""

from __future__ import annotations

from collections.abc import Iterable

from pericles.core import work
from pericles.core.buildings import Building, Ownership, housing_capacity, storage_capacity
from pericles.core.context import Context, reject
from pericles.core.events import Event, EventSink
from pericles.core.intents import AcceptCouple, Intent, ProposeCouple, SetHome
from pericles.core.inventory import EPSILON, Inventory, transfer
from pericles.core.state import Deceased, Pregnancy, Proposal, Villager, WorldState

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


def occupants(state: WorldState, building_id: str) -> int:
    """Residents plus their unborn children (ADR-0015 §7)."""
    residents = [v for v in state.villagers.values() if v.home == building_id]
    return len(residents) + sum(1 for v in residents if v.pregnancy is not None)


def _may_live_in(villager: Villager, building: Building) -> bool:
    ownership = building.ownership
    return ownership.owned_by(villager.id) or (
        villager.partner is not None and ownership.owned_by(villager.partner)
    )


def set_home(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, SetHome)
    villager = state.villagers[intent.actor]
    building = state.buildings.get(intent.building)
    if building is None:
        return reject(sink, intent, "unknown_building")
    if not building.complete:
        return reject(sink, intent, "incomplete")
    capacity = housing_capacity(ctx.registry, building)
    if capacity == 0:
        return reject(sink, intent, "not_housing")
    if not _may_live_in(villager, building):
        return reject(sink, intent, "not_owner")
    if villager.home != building.id:
        incoming = 1 + (1 if villager.pregnancy is not None else 0)
        if occupants(state, building.id) + incoming > capacity:
            return reject(sink, intent, "house_full")
    villager.home = building.id
    sink.emit("moved_in", actor=villager.id, building=building.id)
    return None


def propose_couple(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, ProposeCouple)
    actor = state.villagers[intent.actor]
    target = state.villagers.get(intent.target)
    if not actor.adult:
        return reject(sink, intent, "too_young")
    if target is None:
        return reject(sink, intent, "unknown_target")
    if target.id == actor.id:
        return reject(sink, intent, "self")
    if not target.adult:
        return reject(sink, intent, "target_too_young")
    if actor.partner is not None:
        return reject(sink, intent, "already_partnered")
    if target.partner is not None:
        return reject(sink, intent, "target_partnered")
    expires = state.tick + ctx.config.couple_proposal_ttl_ticks
    state.proposals[actor.id] = Proposal(target.id, expires)
    sink.emit("couple_proposed", actor=actor.id, target=target.id, expires_tick=expires)
    return None


def accept_couple(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, AcceptCouple)
    actor = state.villagers[intent.actor]
    proposal = state.proposals.get(intent.proposer)
    if proposal is None or proposal.target != actor.id or state.tick >= proposal.expires_tick:
        return reject(sink, intent, "no_proposal")
    proposer = state.villagers[intent.proposer]
    if not actor.adult:
        return reject(sink, intent, "too_young")
    if not proposer.adult:
        return reject(sink, intent, "target_too_young")
    if actor.partner is not None:
        return reject(sink, intent, "already_partnered")
    if proposer.partner is not None:
        return reject(sink, intent, "target_partnered")
    actor.partner, proposer.partner = proposer.id, actor.id
    pair = {actor.id, proposer.id}
    state.proposals = {k: p for k, p in state.proposals.items() if k not in pair}
    sink.emit("couple_formed", villagers=sorted(pair))
    return None


def expire_proposals(state: WorldState, sink: EventSink) -> None:
    """Drop proposals that cannot be accepted on the next tick."""
    for proposer in sorted(state.proposals):
        proposal = state.proposals[proposer]
        if proposal.expires_tick <= state.tick + 1:
            del state.proposals[proposer]
            sink.emit("couple_proposal_expired", actor=proposer, target=proposal.target)


def food_stock(ctx: Context, state: WorldState) -> float:
    """Total nutrition held by villagers and in buildings' storage (ADR-0015 §7)."""
    items = ctx.registry.items
    containers = [v.inventory for v in state.villagers.values()]
    containers += [b.storage for b in state.buildings.values()]
    return sum(
        items[item].nutrition * qty for inv in containers for item, qty in inv.totals().items()
    )


def _fertile_pair(ctx: Context, state: WorldState, mother: Villager) -> Villager | None:
    config = ctx.config
    partner = state.villagers.get(mother.partner) if mother.partner is not None else None
    if (
        partner is None
        or not (mother.adult and partner.adult)
        or mother.sex != config.bearing_sex
        or partner.sex == config.bearing_sex
        or partner.sex is None
        or mother.pregnancy is not None
    ):
        return None
    return partner


def _has_room(ctx: Context, state: WorldState, mother: Villager, partner: Villager) -> bool:
    home = state.buildings.get(mother.home) if mother.home is not None else None
    return (
        home is not None
        and partner.home == home.id
        and occupants(state, home.id) < housing_capacity(ctx.registry, home)
    )


def _rested(ctx: Context, state: WorldState, mother: Villager) -> bool:
    if mother.last_birth_tick is None:
        return True
    interval = ctx.config.birth_interval_days * ctx.config.calendar.ticks_per_day
    return state.tick - mother.last_birth_tick >= interval


def conceive(ctx: Context, state: WorldState, sink: EventSink) -> None:
    """The daily conception roll (REQ-SIM-015 AC2). One draw per eligible mother, by id."""
    config = ctx.config
    if food_stock(ctx, state) < config.birth_food_per_capita * len(state.villagers):
        return
    gestation = config.gestation_days * config.calendar.ticks_per_day
    for vid in sorted(state.villagers):
        mother = state.villagers[vid]
        partner = _fertile_pair(ctx, state, mother)
        if partner is None or not _has_room(ctx, state, mother, partner):
            continue
        if not _rested(ctx, state, mother):
            continue
        if state.rng.random() < config.conception_chance_per_day:
            due = state.tick + gestation
            mother.pregnancy = Pregnancy(partner.id, due)
            sink.emit("conceived", mother=vid, father=partner.id, due_tick=due)


def _new_id(state: WorldState) -> tuple[str, int]:
    n = state.next_villager
    while f"v{n}" in state.villagers or f"v{n}" in state.dead:
        n += 1
    state.next_villager = n + 1
    return f"v{n}", n


def births(ctx: Context, state: WorldState, sink: EventSink) -> None:
    """Deliver every pregnancy due by this tick, mothers by id (REQ-SIM-015 AC2)."""
    config = ctx.config
    for vid in sorted(state.villagers):
        mother = state.villagers[vid]
        pregnancy = mother.pregnancy
        if pregnancy is None or pregnancy.due_tick > state.tick:
            continue
        child_id, n = _new_id(state)
        names = config.child_names
        sex = state.rng.choice(config.sexes)
        state.villagers[child_id] = Villager(
            child_id,
            names[n % len(names)] if names else child_id,
            mother.pos,
            sex=sex,
            born_tick=state.tick,
            adult=False,
            home=mother.home,
            parents=tuple(sorted((vid, pregnancy.father))),
        )
        mother.pregnancy = None
        mother.last_birth_tick = state.tick
        sink.emit("born", child=child_id, mother=vid, father=pregnancy.father, sex=sex)


NAMED_FIELDS = ("actor", "child", "father", "mother", "target", "villager")


def _named(event: Event) -> set[str]:
    names = {str(event.data[k]) for k in NAMED_FIELDS if event.data.get(k) is not None}
    names.update(str(v) for v in event.data.get("villagers", ()))
    return names


def _family(state: WorldState, child: Villager) -> set[str]:
    """The child, its parents and its siblings, living or dead."""
    parents = set(child.parents)
    people = [(v.id, v.parents) for v in state.villagers.values()]
    people += [(d.id, d.parents) for d in state.dead.values()]
    siblings = {vid for vid, theirs in people if parents & set(theirs)}
    return {child.id} | parents | siblings


def witness(ctx: Context, state: WorldState, events: Iterable[Event]) -> None:
    """Children record the tick's notable events (REQ-SIM-016 AC3; ADR-0015 §9)."""
    config = ctx.config
    events = list(events)
    limit = config.childhood_memory_limit
    for vid in sorted(state.villagers):
        child = state.villagers[vid]
        if child.adult:
            continue
        family = _family(state, child)
        for event in events:
            notable = event.kind in config.village_events or (
                event.kind in config.family_events and bool(_named(event) & family)
            )
            if notable:
                child.witnessed.append(
                    {"tick": event.tick, "kind": event.kind, "data": dict(event.data)}
                )
        del child.witnessed[: max(0, len(child.witnessed) - limit)]


def _model(ctx: Context, state: WorldState, child: Villager) -> str | None:
    config = ctx.config
    if config.model_rule == "fixed":
        return config.adult_model
    models = set()
    for parent in child.parents:
        alive = state.villagers.get(parent)
        model = alive.model if alive is not None else None
        if alive is None and parent in state.dead:
            model = state.dead[parent].model
        if model is not None:
            models.add(model)
    return state.rng.choice(sorted(models)) if models else config.adult_model


def come_of_age(ctx: Context, state: WorldState, sink: EventSink) -> None:
    """Children at adult age become adults, with a model and memories (REQ-SIM-016 AC2-AC3)."""
    for vid in sorted(state.villagers):
        child = state.villagers[vid]
        if child.adult or age_days(ctx, state, child) < ctx.config.adult_age_days:
            continue
        child.adult = True
        child.model = _model(ctx, state, child)
        child.memories = child.witnessed
        child.witnessed = []
        sink.emit("came_of_age", villager=vid, model=child.model)
