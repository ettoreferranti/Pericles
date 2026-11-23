"""Resource nodes: placement and regrowth (REQ-SIM-007, ADR-0014)."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap


@dataclass
class Node:
    id: str
    kind: str
    pos: Coord
    stock: int
    regrow: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "pos": list(self.pos),
            "stock": self.stock,
            "regrow": self.regrow,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Node:
        return cls(
            str(data["id"]),
            str(data["kind"]),
            Coord(*data["pos"]),
            int(data["stock"]),
            float(data["regrow"]),
        )


def place_nodes(seed: int, tilemap: TileMap, registry: Registry) -> list[Node]:
    """Scatter full nodes over matching terrain, row-major, at most one per tile."""
    rng = random.Random(f"pericles-nodes-{seed}")
    kinds = sorted(registry.nodes)
    nodes: list[Node] = []
    for index, terrain in enumerate(tilemap.terrain):
        for kind in kinds:
            definition = registry.nodes[kind]
            if terrain in definition.terrains and rng.random() < definition.density:
                y, x = divmod(index, tilemap.width)
                nodes.append(Node(f"n{len(nodes)}", kind, Coord(x, y), definition.stock))
                break
    return nodes


def regrow(nodes: Iterable[Node], registry: Registry) -> None:
    """Apply one in-game day of regrowth; reaching the maximum drops the remainder."""
    for node in nodes:
        definition = registry.nodes[node.kind]
        node.regrow += definition.regrowth_per_day
        whole = int(node.regrow)
        if node.stock + whole >= definition.stock:
            node.stock = max(node.stock, definition.stock)
            node.regrow = 0.0
        else:
            node.stock += whole
            node.regrow -= whole
