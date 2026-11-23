"""Inventories: stackable items, tool instances and carried weight (REQ-SIM-013, ADR-0014)."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pericles.core.content.registry import Registry

UNLIMITED = 10**9
EPSILON = 1e-9


class InventoryError(ValueError):
    """An operation would make a held quantity negative."""


@dataclass
class Tool:
    item: str
    durability: int

    def to_dict(self) -> dict[str, Any]:
        return {"item": self.item, "durability": self.durability}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Tool:
        return cls(str(data["item"]), int(data["durability"]))


@dataclass
class Inventory:
    items: dict[str, int] = field(default_factory=dict)
    tools: list[Tool] = field(default_factory=list)

    def count(self, item: str) -> int:
        return self.items.get(item, 0) + sum(1 for tool in self.tools if tool.item == item)

    def totals(self) -> Counter[str]:
        totals = Counter(self.items)
        totals.update(tool.item for tool in self.tools)
        return totals

    def add(self, registry: Registry, item: str, qty: int) -> None:
        if qty < 0:
            raise InventoryError(f"cannot add a negative quantity ({qty} {item})")
        durability = registry.items[item].durability
        if durability is None:
            if qty:
                self.items[item] = self.items.get(item, 0) + qty
        else:
            self.add_tools(Tool(item, durability) for _ in range(qty))

    def add_tools(self, tools: Iterable[Tool]) -> None:
        self.tools.extend(tools)
        self.tools.sort(key=lambda tool: (tool.item, tool.durability))

    def remove(self, item: str, qty: int) -> list[Tool]:
        """Remove `qty` units. Tools leave most-worn first and are returned."""
        if qty < 0:
            raise InventoryError(f"cannot remove a negative quantity ({qty} {item})")
        held = self.count(item)
        if held < qty:
            raise InventoryError(f"holds {held} {item}, cannot remove {qty}")
        if item in self.items:
            left = self.items[item] - qty
            if left:
                self.items[item] = left
            else:
                del self.items[item]
            return []
        removed = [tool for tool in self.tools if tool.item == item][:qty]
        for tool in removed:
            self.tools.remove(tool)
        return removed

    def has(self, bundle: Mapping[str, int]) -> bool:
        return all(self.count(item) >= qty for item, qty in bundle.items())

    def weight(self, registry: Registry) -> float:
        stacked = sum(registry.items[item].weight * qty for item, qty in self.items.items())
        return stacked + sum(registry.items[tool.item].weight for tool in self.tools)

    def to_dict(self) -> dict[str, Any]:
        return {
            "items": dict(sorted(self.items.items())),
            "tools": [tool.to_dict() for tool in self.tools],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Inventory:
        return cls(
            {str(item): int(qty) for item, qty in data["items"].items()},
            [Tool.from_dict(tool) for tool in data["tools"]],
        )


def transfer(registry: Registry, source: Inventory, target: Inventory, item: str, qty: int) -> None:
    tools = source.remove(item, qty)
    if tools:
        target.add_tools(tools)
    else:
        target.add(registry, item, qty)


def bundle_weight(registry: Registry, bundle: Mapping[str, int]) -> float:
    return sum(registry.items[item].weight * qty for item, qty in bundle.items())


def capacity_for(
    registry: Registry, inventory: Inventory, item: str, limit: float, freed: float = 0.0
) -> int:
    """How many more units of `item` fit under `limit` (after `freed` weight leaves)."""
    unit = registry.items[item].weight
    if unit == 0:
        return UNLIMITED
    free = limit - inventory.weight(registry) + freed
    return max(0, math.floor(free / unit + EPSILON))


def fits(
    registry: Registry,
    inventory: Inventory,
    bundle: Mapping[str, int],
    limit: float,
    freed: float = 0.0,
) -> bool:
    total = inventory.weight(registry) - freed + bundle_weight(registry, bundle)
    return total <= limit + EPSILON  # pragma: no mutate - boundary is within float noise
