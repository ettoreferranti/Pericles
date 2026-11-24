"""A* pathfinding over tile costs (REQ-SIM-004)."""

from __future__ import annotations

import heapq
import math
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
        self._keyed: list[float | None] | None = None

    def cost(self, c: Coord) -> float | None:
        if not (0 <= c.x < self.width and 0 <= c.y < self.height):
            return None
        if self._blocked is not None and self._blocked(c):
            return None
        return self._costs[c.y * self.width + c.x]

    def keyed_costs(self) -> list[float | None]:
        """`cost` of every tile, indexed `x * height + y` (as `find_path` keys tiles)."""
        if self._keyed is None:
            self._keyed = keyed_costs(self)
        return self._keyed


def keyed_costs(field: CostField) -> list[float | None]:
    """`field.cost` of every tile, indexed `x * height + y`."""
    return [field.cost(Coord(x, y)) for x in range(field.width) for y in range(field.height)]


class _AskedCosts(dict[int, float | None]):
    """`field.cost` by tile key, asked once per tile on first use."""

    def __init__(self, field: CostField) -> None:
        super().__init__()
        self.field = field

    def __missing__(self, key: int) -> float | None:
        x, y = divmod(key, self.field.height)
        value = self[key] = self.field.cost(Coord(x, y))
        return value


def _in_bounds(field: CostField, c: Coord) -> bool:
    return 0 <= c.x < field.width and 0 <= c.y < field.height


def find_path(field: CostField, start: Coord, goal: Coord) -> list[Coord] | None:
    """A* over 4-neighbours; ties break on (f, h, tile) with tiles ordered as `Coord` (x, y).

    Tiles are keyed `x * height + y`, which orders exactly as `Coord`; neighbours off the map
    are skipped (a cost field is impassable there). A `TerrainCostField` lists its costs once
    (`keyed_costs`); any other field is asked once per tile it reaches.
    """
    if not (_in_bounds(field, start) and _in_bounds(field, goal)):
        return None
    if start == goal:
        return [start]
    if field.cost(goal) is None:
        return None
    width, height, min_cost = field.width, field.height, field.min_cost
    gx, gy = goal
    target = gx * height + gy
    origin = start.x * height + start.y
    costs: list[float | None] | _AskedCosts = (
        field.keyed_costs() if isinstance(field, TerrainCostField) else _AskedCosts(field)
    )
    best: dict[int, float] = {origin: 0.0}
    came_from: dict[int, int] = {}
    closed: set[int] = set()
    frontier: list[tuple[float, float, int]] = [(0.0, 0.0, origin)]
    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current in closed:
            continue
        if current == target:
            keys = [current]
            while current in came_from:
                current = came_from[current]
                keys.append(current)
            return [Coord(k // height, k % height) for k in reversed(keys)]
        closed.add(current)
        x, y = divmod(current, height)
        here = best[current]
        for nx, ny in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)):
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            nb = nx * height + ny
            if nb in closed:
                continue
            step = costs[nb]
            if step is None:
                continue
            cost = here + step
            if cost < best.get(nb, math.inf):
                best[nb] = cost
                came_from[nb] = current
                h = (abs(nx - gx) + abs(ny - gy)) * min_cost
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
