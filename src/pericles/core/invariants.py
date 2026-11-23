"""Engine invariants: item conservation and state sanity (REQ-SIM-018, ADR-0014 §4)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from pericles.core.buildings import storage_capacity
from pericles.core.context import Context
from pericles.core.events import Event
from pericles.core.inventory import EPSILON, Inventory
from pericles.core.state import WorldState


class InvariantError(AssertionError):
    """The world broke a rule the engine guarantees."""


def item_totals(state: WorldState) -> Counter[str]:
    totals: Counter[str] = Counter()
    for villager in state.villagers.values():
        totals.update(villager.inventory.totals())
        if villager.activity is not None:
            totals.update(villager.activity.reserved.totals())
    for building in state.buildings.values():
        totals.update(building.delivered)
        totals.update(building.storage.totals())
    return totals


def ledger(events: Iterable[Event]) -> Counter[str]:
    """The net change in item totals that the events account for."""
    net: Counter[str] = Counter()
    for event in events:
        for item, qty in event.data.get("created", {}).items():
            net[item] += qty
        for item, qty in event.data.get("destroyed", {}).items():
            net[item] -= qty
    return net


def check_conservation(
    before: Counter[str], after: Counter[str], events: Iterable[Event]
) -> list[str]:
    net = ledger(events)
    problems = []
    for item in sorted(set(before) | set(after) | set(net)):
        expected = before[item] + net[item]
        if after[item] != expected:
            problems.append(f"item {item!r}: expected {expected}, found {after[item]}")
    return problems


def _check_inventory(owner: str, inventory: Inventory) -> list[str]:
    problems = [
        f"{owner} holds {qty} {item}" for item, qty in sorted(inventory.items.items()) if qty <= 0
    ]
    problems += [
        f"{owner} holds a {tool.item} with durability {tool.durability}"
        for tool in inventory.tools
        if tool.durability <= 0
    ]
    return problems


def check_state(ctx: Context, state: WorldState) -> list[str]:
    registry = ctx.registry
    limit = ctx.config.carry_limit
    problems: list[str] = []
    for vid in sorted(state.villagers):
        villager = state.villagers[vid]
        problems += _check_inventory(f"villager {vid}", villager.inventory)
        if villager.activity is not None:
            problems += _check_inventory(f"villager {vid} (reserved)", villager.activity.reserved)
        weight = villager.inventory.weight(registry)
        if weight > limit + EPSILON:
            problems.append(f"villager {vid} carries {weight:g}, over the limit {limit:g}")
    for nid in sorted(state.nodes):
        node = state.nodes[nid]
        maximum = registry.nodes[node.kind].stock
        if not 0 <= node.stock <= maximum:
            problems.append(f"node {nid} stock {node.stock} outside 0..{maximum}")
    for bid in sorted(state.buildings):
        building = state.buildings[bid]
        problems += _check_inventory(f"building {bid}", building.storage)
        cost = registry.buildings[building.kind].cost
        for item, qty in sorted(building.delivered.items()):
            if not 0 < qty <= cost.get(item, 0):
                problems.append(
                    f"building {bid} has {qty} {item} delivered, cost {cost.get(item, 0)}"
                )
        stored = sum(building.storage.totals().values())
        capacity = storage_capacity(registry, building)
        if stored > capacity:
            problems.append(f"building {bid} stores {stored}, over its capacity {capacity}")
    return problems


def check_tick(
    ctx: Context, before: Counter[str], state: WorldState, events: Iterable[Event]
) -> list[str]:
    return check_conservation(before, item_totals(state), events) + check_state(ctx, state)
