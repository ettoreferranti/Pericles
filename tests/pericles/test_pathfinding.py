from collections import Counter
from collections.abc import Sequence
from itertools import pairwise

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import Band, MapParams, TileMap, generate_map
from pericles.core.pathfinding import TerrainCostField, find_path, path_cost

pytestmark = pytest.mark.req("REQ-SIM-004")


class Grid:
    """A test cost field from rows of costs (None = wall)."""

    def __init__(self, rows: Sequence[Sequence[float | None]]):
        self.rows = rows
        self.height = len(rows)
        self.width = len(rows[0])
        costs = [c for row in rows for c in row if c is not None]
        self.min_cost = min(costs) if costs else 1.0

    def cost(self, c: Coord) -> float | None:
        if not (0 <= c.x < self.width and 0 <= c.y < self.height):
            return None
        return self.rows[c.y][c.x]


def dijkstra(field: Grid, start: Coord, goal: Coord) -> float | None:
    best = {start: 0.0}
    frontier = [start]
    while frontier:
        nxt = []
        for cur in frontier:
            for nb in cur.neighbours4():
                step = field.cost(nb)
                if step is None:
                    continue
                cand = best[cur] + step
                if cand < best.get(nb, float("inf")) - 1e-12:
                    best[nb] = cand
                    nxt.append(nb)
        frontier = nxt
    return best.get(goal)


def assert_valid(field: Grid, path: list[Coord], start: Coord, goal: Coord) -> None:
    assert path[0] == start and path[-1] == goal
    for a, b in pairwise(path):
        assert a.manhattan(b) == 1
        assert field.cost(b) is not None


def test_straight_line() -> None:
    field = Grid([[1, 1, 1, 1]])
    assert find_path(field, Coord(0, 0), Coord(3, 0)) == [
        Coord(0, 0),
        Coord(1, 0),
        Coord(2, 0),
        Coord(3, 0),
    ]


def test_prefers_cheaper_detour() -> None:
    """AC1: shortest *cost* path, not shortest step count."""
    field = Grid([[1, 9, 1], [1, 1, 1]])
    path = find_path(field, Coord(0, 0), Coord(2, 0))
    assert path is not None
    assert path_cost(field, path) == 4
    assert Coord(1, 0) not in path


def test_start_equals_goal() -> None:
    assert find_path(Grid([[1]]), Coord(0, 0), Coord(0, 0)) == [Coord(0, 0)]


def test_unreachable_goal_returns_none() -> None:
    """AC2: an unreachable target returns no path."""
    field = Grid([[1, None, 1], [1, None, 1]])
    assert find_path(field, Coord(0, 0), Coord(2, 0)) is None


@pytest.mark.parametrize("goal", [Coord(5, 0), Coord(-1, 0), Coord(1, 0)])
def test_out_of_bounds_or_impassable_goal(goal: Coord) -> None:
    assert find_path(Grid([[1, None, 1]]), Coord(0, 0), goal) is None


def test_out_of_bounds_start() -> None:
    assert find_path(Grid([[1, 1]]), Coord(-1, 0), Coord(1, 0)) is None


def test_path_cost() -> None:
    field = Grid([[5, 2, 3]])
    assert path_cost(field, [Coord(0, 0), Coord(1, 0), Coord(2, 0)]) == 5
    assert path_cost(field, [Coord(0, 0)]) == 0


@settings(max_examples=150, deadline=None)
@given(
    st.integers(1, 7).flatmap(
        lambda w: st.lists(
            st.lists(st.sampled_from([None, 0.5, 1.0, 2.0, 5.0]), min_size=w, max_size=w),
            min_size=1,
            max_size=7,
        )
    ),
    st.data(),
)
def test_matches_dijkstra_on_random_grids(
    rows: list[list[float | None]], data: st.DataObject
) -> None:
    """AC1/AC2: A* cost equals brute-force optimum; unreachable ⇔ None."""
    field = Grid(rows)
    start = Coord(
        data.draw(st.integers(0, field.width - 1)), data.draw(st.integers(0, field.height - 1))
    )
    goal = Coord(
        data.draw(st.integers(0, field.width - 1)), data.draw(st.integers(0, field.height - 1))
    )
    path = find_path(field, start, goal)
    if start == goal:
        assert path == [start]
        return
    expected = dijkstra(field, start, goal) if field.cost(goal) is not None else None
    if expected is None:
        assert path is None
    else:
        assert path is not None
        assert_valid(field, path, start, goal)
        assert path_cost(field, path) == pytest.approx(expected)


def test_deterministic_tie_breaking() -> None:
    field = Grid([[1, 1, 1], [1, 1, 1], [1, 1, 1]])
    paths = {tuple(find_path(field, Coord(0, 0), Coord(2, 2)) or []) for _ in range(5)}
    assert len(paths) == 1


def test_terrain_cost_field(registry: Registry) -> None:
    """AC3: water is not walkable; blocked tiles (later: buildings) are impassable."""
    tilemap = TileMap(3, 1, ["grass", "forest", "water"], [0.0, 0.0, 0.0])
    field = TerrainCostField(tilemap, registry)
    assert (field.width, field.height, field.min_cost) == (3, 1, 1.0)
    assert field.cost(Coord(0, 0)) == registry.terrains["grass"].move_cost
    assert field.cost(Coord(1, 0)) == registry.terrains["forest"].move_cost
    assert field.cost(Coord(2, 0)) is None
    assert field.cost(Coord(3, 0)) is None
    blocked = TerrainCostField(tilemap, registry, blocked=lambda c: c == Coord(1, 0))
    assert blocked.cost(Coord(1, 0)) is None
    assert blocked.cost(Coord(0, 0)) == 1.0


def test_terrain_field_without_walkable_tiles(registry: Registry) -> None:
    field = TerrainCostField(TileMap(1, 1, ["water"], [0.0]), registry)
    assert field.min_cost == 1.0


def test_unreachable_on_full_size_map(registry: Registry) -> None:
    """AC2: an island goal on a 128x128 map returns None without hanging."""
    params = MapParams(width=128, height=128, bands=(Band("grass", 1.0),), start_terrain="grass")
    tilemap = generate_map(0, params, registry)
    island = Coord(100, 100)
    walls = set(island.neighbours4())
    field = TerrainCostField(tilemap, registry, blocked=lambda c: c in walls)
    assert find_path(field, Coord(0, 0), island) is None


def test_exact_path_on_uniform_grid() -> None:
    """AC1: ties resolve deterministically (first-found path is kept)."""
    field = Grid([[1, 1, 1], [1, 1, 1], [1, 1, 1]])
    assert find_path(field, Coord(0, 0), Coord(2, 2)) == [
        Coord(0, 0),
        Coord(0, 1),
        Coord(0, 2),
        Coord(1, 2),
        Coord(2, 2),
    ]


def test_heuristic_scales_with_min_cost() -> None:
    """AC1: the heuristic must stay admissible when cheap tiles cost under 1."""
    field = Grid([[1, 1, 1, 1, 1], [0.5, 0.5, 0.5, 0.5, 0.5]])
    path = find_path(field, Coord(0, 0), Coord(4, 0))
    assert path is not None
    assert path_cost(field, path) == pytest.approx(3.5)


def test_min_cost_is_smallest_walkable_cost(registry: Registry) -> None:
    """AC3: min_cost is the cheapest walkable tile, ignoring water."""
    field = TerrainCostField(TileMap(2, 1, ["forest", "water"], [0.0, 0.0]), registry)
    assert field.min_cost == registry.terrains["forest"].move_cost


@pytest.mark.parametrize("start", [Coord(2, 0), Coord(0, 1)])
def test_start_on_far_edge_is_out_of_bounds(start: Coord) -> None:
    assert find_path(Grid([[1, 1]]), start, Coord(1, 0)) is None


def test_path_cost_rejects_impassable_tiles() -> None:
    with pytest.raises(ValueError, match="impassable"):
        path_cost(Grid([[1, None]]), [Coord(0, 0), Coord(1, 0)])


class CountingGrid(Grid):
    """A Grid that records every cost query, to observe search effort."""

    def __init__(self, rows: Sequence[Sequence[float | None]]):
        super().__init__(rows)
        self.queries: list[Coord] = []

    def cost(self, c: Coord) -> float | None:
        self.queries.append(c)
        return super().cost(c)


def test_search_is_goal_directed() -> None:
    """AC1: A* heads for the goal instead of flooding the open grid."""
    field = CountingGrid([[1.0] * 20 for _ in range(20)])
    path = find_path(field, Coord(0, 10), Coord(19, 10))
    assert path is not None and len(path) == 20
    assert len(field.queries) <= 65


def test_tiles_are_expanded_at_most_once() -> None:
    """AC1: a tile whose best cost is settled is never expanded again."""
    rows: list[list[float | None]] = [
        [2.0, 0.5, 5.0, None],
        [0.5, 0.5, 1.0, 5.0],
        [0.5, 9.0, 0.5, 2.0],
        [5.0, 5.0, 0.5, 0.5],
        [None, 0.5, 2.0, 0.5],
        [0.5, 1.0, 9.0, 9.0],
        [0.5, 0.5, 0.5, 1.0],
        [0.5, 9.0, 0.5, None],
    ]
    field = CountingGrid(rows)
    assert find_path(field, Coord(3, 0), Coord(2, 6)) is not None
    # each tile is queried once per expanded neighbour (at most 4), plus once for the goal check
    assert max(Counter(field.queries).values()) <= 4


def test_equal_cost_route_keeps_first_found() -> None:
    """AC1: a later route of equal cost never replaces the one already found."""
    field = Grid([[2, 1, 1, 1], [2, 1, 1, 2]])
    assert find_path(field, Coord(0, 0), Coord(3, 1)) == [
        Coord(0, 0),
        Coord(1, 0),
        Coord(1, 1),
        Coord(2, 1),
        Coord(3, 1),
    ]
