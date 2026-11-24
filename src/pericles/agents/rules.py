"""Scripted-behaviour rules: each looks at the world and decides, or passes (ADR-0016 §3-§4)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping, Sequence

from pericles.agents.view import CONSTRUCT, PLACE, Decision, View
from pericles.core.buildings import footprint, remaining_cost
from pericles.core.content.schema import ActionDef
from pericles.core.geometry import Coord
from pericles.core.intents import (
    AcceptCouple,
    Construct,
    Deliver,
    Deposit,
    Eat,
    Intent,
    PlaceBuilding,
    ProposeCouple,
    SetHome,
    Sleep,
    StartAction,
    Take,
    Wait,
)
from pericles.core.inventory import capacity_for
from pericles.core.state import Villager

EAT, SLEEP, SHELTER = "eat", "sleep", "shelter"
Rule = Callable[[View, Villager], Decision | None]


def jobs(view: View, villager: Villager, items: Iterable[str]) -> list[ActionDef]:
    """Node actions producing one of `items` that this villager can start now, by id."""
    wanted = set(items)
    config = view.ctx.config
    blocked = config.calendar.season_at(view.tick).blocked_tags
    child_tags = None if villager.adult else set(config.child_action_tags)
    found = []
    for action_id in sorted(view.ctx.registry.actions):
        action = view.ctx.registry.actions[action_id]
        requires = action.requires
        if action.location.node is None or action.location.building is not None:
            continue
        if not wanted & set(action.outputs) or action.inputs:
            continue
        if any(tag in blocked for tag in action.tags):
            continue
        if child_tags is not None and not child_tags & set(action.tags):
            continue
        if requires.tools or requires.knowledge or action.location.terrains:
            continue
        if (
            requires.skill is not None
            and villager.skills.get(requires.skill, 0.0) < requires.min_skill
        ):
            continue
        found.append(action)
    return found


def skill_score(view: View, villager: Villager, action: ActionDef) -> float:
    level = villager.skills.get(action.skill, 0.0) if action.skill is not None else 0.0
    return 1.0 + view.config.skill_weight * level / view.ctx.config.max_skill


def fits_output(view: View, villager: Villager, action: ActionDef) -> bool:
    limit = view.ctx.config.carry_limit
    registry = view.ctx.registry
    return any(
        capacity_for(registry, villager.inventory, item, limit) > 0 for item in action.outputs
    )


def first_reachable(
    view: View,
    villager: Villager,
    ranked: Sequence[ActionDef],
    origin: Coord | None = None,
    radius: int | None = None,
) -> Decision | None:
    """Go to, or start, the first ranked action with a usable node and room for its output."""
    for action in ranked:
        kind = action.location.node
        if kind is None or not fits_output(view, villager, action):
            continue
        node = view.nearest_node(villager, kind, origin, radius)
        if node is None:
            continue
        step = view.go(villager, [node.pos])
        intent = step if step is not None else StartAction(villager.id, action.id, node.id)
        return Decision(intent, target=node.id, job=action.id)
    return None


def gather(
    view: View,
    villager: Villager,
    items: Iterable[str],
    origin: Coord | None = None,
    radius: int | None = None,
) -> Decision | None:
    ranked = sorted(
        jobs(view, villager, items), key=lambda a: (-skill_score(view, villager, a), a.id)
    )
    return first_reachable(view, villager, ranked, origin, radius)


def portion(view: View, villager: Villager, food: str) -> int:
    """How much of `food` to fetch: enough for `food_carry` nutrition, within the carry limit."""
    registry = view.ctx.registry
    room = capacity_for(registry, villager.inventory, food, view.ctx.config.carry_limit)
    return min(room, math.ceil(view.config.food_carry / registry.items[food].nutrition))


def feed(view: View, villager: Villager) -> Decision | None:
    """Eat from the inventory, else fetch from the nearest store holding food."""
    items = view.ctx.registry.items
    level = view.level(villager, EAT)
    for food in view.foods:
        have = villager.inventory.count(food)
        if have:
            return Decision(
                Eat(villager.id, food, min(have, math.ceil(level / items[food].nutrition)))
            )
    portions = {food: portion(view, villager, food) for food in view.foods}
    for building in view.stores(villager):
        for food in view.foods:
            held = building.storage.count(food)
            qty = min(held, portions[food])
            if qty <= 0:
                continue
            step = view.go(villager, view.tiles(building))
            if step is not None:
                return Decision(step, target=building.id)
            return Decision(Take(villager.id, building.id, food, qty), target=building.id)
    return None


def eat(view: View, villager: Villager) -> Decision | None:
    if view.level(villager, EAT) < view.config.act_at[EAT]:
        return None
    return feed(view, villager) or gather(view, villager, view.foods)


def sleep(view: View, villager: Villager) -> Decision | None:
    level = view.level(villager, SLEEP)
    if level < view.config.act_at[SLEEP]:
        return None
    home = view.home(villager)
    if home is not None and level < view.config.urgent_at[SLEEP] and not view.at_home(villager):
        step = view.go(villager, view.tiles(home))
        if step is not None:
            return Decision(step, target=home.id)
    return Decision(Sleep(villager.id))


def shelter(view: View, villager: Villager) -> Decision | None:
    home = view.home(villager)
    if home is None:
        return None
    level = view.level(villager, SHELTER)
    if view.at_home(villager):
        return Decision(Wait(villager.id)) if level > view.config.warm_until else None
    if level < view.config.act_at[SHELTER]:
        return None
    step = view.go(villager, view.tiles(home))
    return Decision(step, target=home.id) if step is not None else Decision(Wait(villager.id))


def wait(view: View, villager: Villager) -> Decision:
    return Decision(Wait(villager.id))


def demand(view: View, villager: Villager, item: str) -> float:
    """How much the village wants `item`, 0..1 (ADR-0016 §4, amended).

    Food is wanted until the stores `villager` can fetch from hold the reserve; food in
    pockets does not count.
    """
    if view.ctx.registry.items[item].nutrition > 0:
        return view.food_demand(villager)
    return 1.0 if view.needed()[item] > 0 else 0.0


def utility(
    view: View, villager: Villager, action: ActionDef, demands: Mapping[str, float] | None = None
) -> float:
    """Best output demand, shared among its workers, times skill; `demands` may hold the
    villager's `demand` per item already."""

    def wants(item: str) -> float:
        return demands[item] if demands is not None else demand(view, villager, item)

    best = max(wants(item) / (1 + view.workers(item, villager.id)) for item in action.outputs)
    return best * skill_score(view, villager, action)


def work(view: View, villager: Villager) -> Decision | None:
    demands = {item: demand(view, villager, item) for item in sorted(view.ctx.registry.items)}
    wanted = [item for item, level in demands.items() if level > 0]
    scored = [(utility(view, villager, a, demands), a) for a in jobs(view, villager, wanted)]
    ranked = [a for score, a in sorted(scored, key=lambda p: (-p[0], p[1].id)) if score > 0]
    return first_reachable(view, villager, ranked)


def deliver(view: View, villager: Villager) -> Decision | None:
    registry = view.ctx.registry
    for building in view.sites():
        remaining = remaining_cost(building, registry)
        for item in sorted(remaining):
            have = villager.inventory.count(item)
            if not have:
                continue
            step = view.go(villager, view.tiles(building))
            if step is not None:
                return Decision(step, target=building.id)
            qty = min(have, remaining[item])
            return Decision(Deliver(villager.id, building.id, item, qty), target=building.id)
    return None


def surplus(view: View, villager: Villager) -> list[tuple[str, int]]:
    """Stackable items to store: all but a little food, never tools or what sites need."""
    registry = view.ctx.registry
    needed = view.needed()
    extra = []
    for item, qty in sorted(villager.inventory.items.items()):
        if needed[item] > 0:
            continue
        nutrition = registry.items[item].nutrition
        keep = math.floor(view.config.food_carry / nutrition) if nutrition > 0 else 0
        if qty > keep:
            extra.append((item, qty - keep))
    return extra


def deposit(view: View, villager: Villager) -> Decision | None:
    load = villager.inventory.weight(view.ctx.registry)
    if load < view.config.deposit_load * view.ctx.config.carry_limit:
        return None
    for item, qty in surplus(view, villager):
        for building in view.stores(villager):
            room = view.room(building)
            if room <= 0:
                continue
            step = view.go(villager, view.tiles(building))
            if step is not None:
                return Decision(step, target=building.id)
            return Decision(
                Deposit(villager.id, building.id, item, min(qty, room)), target=building.id
            )
    return None


COMMUNAL = "communal"


def wanted_building(view: View, villager: Villager) -> str | None:
    """The building kind the village lacks and nobody else is placing (ADR-0016 §4).

    Houses come first: while housing is short, or a house is still going up, no store is wanted.
    """
    config = view.config

    def claimable(kind: str) -> bool:
        return not view.placing(kind, villager.id) and not view.avoided(villager, PLACE + kind)

    if view.housing_shortfall() > 0:
        return config.house_building if claimable(config.house_building) else None
    if any(site.kind == config.house_building for site in view.sites()):
        return None
    if view.storage_shortfall() > 0 and claimable(config.store_building):
        return config.store_building
    return None


def build(view: View, villager: Villager) -> Decision | None:
    if not villager.adult:
        return None
    registry = view.ctx.registry
    for building in view.sites():
        if remaining_cost(building, registry):
            continue
        if view.builders(building.id, villager.id) >= view.config.max_builders:
            continue
        step = view.go(villager, view.tiles(building))
        intent: Intent = step if step is not None else Construct(villager.id, building.id)
        return Decision(intent, target=building.id, job=CONSTRUCT)
    kind = wanted_building(view, villager)
    origin = view.free_origin(kind) if kind is not None else None
    if kind is None or origin is None:
        return None
    step = view.go(villager, footprint(origin, registry.buildings[kind].footprint))
    intent = (
        step if step is not None else PlaceBuilding(villager.id, kind, origin, ownership=COMMUNAL)
    )
    return Decision(intent, target=PLACE + kind)


def home(view: View, villager: Villager) -> Decision | None:
    """Homeless villagers take a house with room; a housed couple moves to its couple house."""
    if view.home(villager) is not None:
        if villager.partner is None:
            return None
        house = view.couple_house(villager)
        if house is None or house.id == villager.home:
            return None
        return Decision(SetHome(villager.id, house.id), target=house.id)
    house = view.house_for(villager)
    if house is None or house.id == villager.home:
        return None
    return Decision(SetHome(villager.id, house.id), target=house.id)


def compatible(view: View, a: Villager, b: Villager | None) -> bool:
    """Exactly one of the pair has the bearing sex (ADR-0015 §6)."""
    if b is None or a.sex is None or b.sex is None:
        return False
    bearing = view.ctx.config.bearing_sex
    return (a.sex == bearing) != (b.sex == bearing)


def couple(view: View, villager: Villager) -> Decision | None:
    if not view.config.couples or not villager.adult or villager.partner is not None:
        return None
    state = view.state
    for proposer in sorted(state.proposals):
        proposal = state.proposals[proposer]
        if (
            proposal.target == villager.id
            and proposal.expires_tick > state.tick
            and not view.avoided(villager, proposer)
            and compatible(view, villager, state.villagers.get(proposer))
        ):
            return Decision(AcceptCouple(villager.id, proposer), target=proposer)
    if villager.id in state.proposals:
        return None
    targeted = {p.target for p in state.proposals.values()}
    free = [
        other
        for other in state.villagers.values()
        if other.id != villager.id
        and other.adult
        and other.partner is None
        and other.id not in state.proposals
        and other.id not in targeted
        and compatible(view, villager, other)
        and not view.avoided(villager, other.id)
    ]
    if not free:
        return None
    other = min(free, key=lambda o: (villager.pos.manhattan(o.pos), o.id))
    return Decision(ProposeCouple(villager.id, other.id), target=other.id)


def child_eat(view: View, villager: Villager) -> Decision | None:
    """Children eat what they hold or what a store holds, else forage near family for it."""
    if view.level(villager, EAT) < view.config.act_at[EAT]:
        return None
    return feed(view, villager) or forage(view, villager)


def follow(view: View, villager: Villager) -> Decision | None:
    parent = view.guardian(villager)
    if parent is None or view.avoided(villager, parent.id):
        return None
    if villager.pos.manhattan(parent.pos) <= view.config.child_follow_radius:
        return None
    step = view.go(villager, [parent.pos])
    return None if step is None else Decision(step, target=parent.id)


def forage(view: View, villager: Villager) -> Decision | None:
    parent = view.guardian(villager)
    origin = villager.pos if parent is None else parent.pos
    return gather(view, villager, view.foods, origin=origin, radius=view.config.child_follow_radius)
