"""Scripted-behaviour rules: each looks at the world and decides, or passes (ADR-0016 §3-§4)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence

from pericles.agents.view import Decision, View
from pericles.core.content.schema import ActionDef
from pericles.core.geometry import Coord
from pericles.core.intents import Eat, Sleep, StartAction, Take, Wait
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
    for building in view.stores(villager):
        for food in view.foods:
            held = building.storage.count(food)
            qty = min(held, portion(view, villager, food))
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
