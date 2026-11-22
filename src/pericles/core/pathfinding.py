"""A* pathfinding over tile costs (REQ-SIM-004)."""

from __future__ import annotations

import heapq
from collections.abc import Callable, Sequence
from typing import Protocol

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap


class CostField(Protocol):
    width: int
    height: int
    min_cost: float

    def cost(self, c: Coord) -> float | None: ...


class TerrainCostField:
    def __init__(
        self,
        tilemap: TileMap,
        registry: Registry,
        blocked: Callable[[Coord], bool] | None = None,
    ) -> None:
        self.width = tilemap.width
        self.height = tilemap.height
        self._costs: list[float | None] = []
        for name in tilemap.terrain:
            terrain = registry.terrains[name]
            self._costs.append(terrain.move_cost if terrain.walkable else None)
        walkable = [c for c in self._costs if c is not None]
        self.min_cost = min(walkable) if walkable else 1.0
        self._blocked = blocked

    def cost(self, c: Coord) -> float | None:
        if not (0 <= c.x < self.width and 0 <= c.y < self.height):
            return None
        if self._blocked is not None and self._blocked(c):
            return None
        return self._costs[c.y * self.width + c.x]


def _in_bounds(field: CostField, c: Coord) -> bool:
    return 0 <= c.x < field.width and 0 <= c.y < field.height


def find_path(field: CostField, start: Coord, goal: Coord) -> list[Coord] | None:
    if not (_in_bounds(field, start) and _in_bounds(field, goal)):
        return None
    if start == goal:
        return [start]
    if field.cost(goal) is None:
        return None
    best: dict[Coord, float] = {start: 0.0}
    came_from: dict[Coord, Coord] = {}
    closed: set[Coord] = set()
    frontier: list[tuple[float, float, Coord]] = [(0.0, 0.0, start)]
    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current in closed:
            continue
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path[::-1]
        closed.add(current)
        for nb in current.neighbours4():
            if nb in closed:
                continue
            step = field.cost(nb)
            if step is None:
                continue
            cost = best[current] + step
            if cost < best.get(nb, float("inf")):
                best[nb] = cost
                came_from[nb] = current
                h = nb.manhattan(goal) * field.min_cost
                heapq.heappush(frontier, (cost + h, h, nb))
    return None


def path_cost(field: CostField, path: Sequence[Coord]) -> float:
    total = 0.0
    for c in path[1:]:
        step = field.cost(c)
        if step is None:
            raise ValueError(f"path enters impassable tile {c}")
        total += step
    return total
