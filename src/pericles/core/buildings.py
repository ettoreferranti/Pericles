"""Buildings and ownership (REQ-SIM-009, REQ-ECO-001, ADR-0014)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory

COMMUNAL = "communal"  # everyone owns it; it lists no owners
OWNERSHIP_KINDS = ("personal", "shared", COMMUNAL)


@dataclass(frozen=True)
class Ownership:
    kind: str
    owners: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.kind not in OWNERSHIP_KINDS:
            raise ValueError(f"unknown ownership kind {self.kind!r}")
        if self.kind == COMMUNAL and self.owners:
            raise ValueError("communal ownership has no owners")
        if self.kind == "personal" and len(self.owners) != 1:
            raise ValueError("personal ownership needs exactly one owner")
        if self.kind == "shared" and len(self.owners) < 2:
            raise ValueError("shared ownership needs at least two owners")
        if tuple(sorted(set(self.owners))) != self.owners:
            raise ValueError("owners must be sorted and unique")

    def owned_by(self, villager: str) -> bool:
        return self.kind == COMMUNAL or villager in self.owners

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "owners": list(self.owners)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Ownership:
        return cls(str(data["kind"]), tuple(str(owner) for owner in data["owners"]))


@dataclass
class Building:
    id: str
    kind: str
    origin: Coord
    ownership: Ownership
    delivered: dict[str, int] = field(default_factory=dict)
    work_done: float = 0.0
    complete: bool = False
    storage: Inventory = field(default_factory=Inventory)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "origin": list(self.origin),
            "ownership": self.ownership.to_dict(),
            "delivered": dict(sorted(self.delivered.items())),
            "work_done": self.work_done,
            "complete": self.complete,
            "storage": self.storage.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Building:
        return cls(
            str(data["id"]),
            str(data["kind"]),
            Coord(*data["origin"]),
            Ownership.from_dict(data["ownership"]),
            {str(item): int(qty) for item, qty in data["delivered"].items()},
            float(data["work_done"]),
            bool(data["complete"]),
            Inventory.from_dict(data["storage"]),
        )


def footprint(origin: Coord, size: tuple[int, int]) -> list[Coord]:
    width, height = size
    return [Coord(origin.x + dx, origin.y + dy) for dy in range(height) for dx in range(width)]


def building_tiles(building: Building, registry: Registry) -> list[Coord]:
    return footprint(building.origin, registry.buildings[building.kind].footprint)


def near(pos: Coord, tiles: Iterable[Coord]) -> bool:
    return any(pos.manhattan(tile) <= 1 for tile in tiles)


def near_footprint(pos: Coord, origin: Coord, size: tuple[int, int]) -> bool:
    """`near(pos, footprint(origin, size))` without listing the tiles."""
    width, height = size
    if width <= 0 or height <= 0:
        return False
    dx = max(origin.x - pos.x, 0, pos.x - (origin.x + width - 1))
    dy = max(origin.y - pos.y, 0, pos.y - (origin.y + height - 1))
    return dx + dy <= 1


def remaining_cost(building: Building, registry: Registry) -> dict[str, int]:
    cost = registry.buildings[building.kind].cost
    return {
        item: qty - building.delivered.get(item, 0)
        for item, qty in sorted(cost.items())
        if qty > building.delivered.get(item, 0)
    }


def housing_capacity(registry: Registry, building: Building) -> int:
    return registry.buildings[building.kind].housing if building.complete else 0


def storage_capacity(registry: Registry, building: Building) -> int:
    return registry.buildings[building.kind].storage if building.complete else 0
