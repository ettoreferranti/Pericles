import pytest

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import MapParams, TileMap, generate_map
from pericles.core.nodes import Node, place_nodes, regrow

pytestmark = pytest.mark.req("REQ-SIM-007")


def dicts(nodes: list[Node]) -> list[dict[str, object]]:
    return [node.to_dict() for node in nodes]


def test_placement_is_seeded(registry: Registry, map_params: MapParams) -> None:
    """AC1/AC2: node placement is deterministic per seed and varies across seeds."""
    tilemap = generate_map(3, map_params, registry)
    assert dicts(place_nodes(5, tilemap, registry)) == dicts(place_nodes(5, tilemap, registry))
    assert dicts(place_nodes(5, tilemap, registry)) != dicts(place_nodes(6, tilemap, registry))


def test_nodes_sit_on_their_terrains_one_per_tile(
    registry: Registry, map_params: MapParams
) -> None:
    """AC1/AC2: nodes start full, on a terrain their definition allows, at most one per tile."""
    tilemap = generate_map(3, map_params, registry)
    nodes = place_nodes(5, tilemap, registry)
    assert [node.id for node in nodes] == [f"n{i}" for i in range(len(nodes))]
    indexes = [node.pos.y * tilemap.width + node.pos.x for node in nodes]
    assert indexes == sorted(set(indexes))
    for node in nodes:
        definition = registry.nodes[node.kind]
        assert tilemap.terrain_at(node.pos) in definition.terrains
        assert (node.stock, node.regrow) == (definition.stock, 0.0)
    assert {node.kind for node in nodes} >= {"tree", "boulder", "berry_bush"}


def test_density_is_respected(registry: Registry, map_params: MapParams) -> None:
    """AC2: trees cover about their configured share (0.5) of forest tiles."""
    tilemap = generate_map(3, map_params, registry)
    forest = tilemap.counts()["forest"]
    trees = sum(1 for node in place_nodes(5, tilemap, registry) if node.kind == "tree")
    assert 0.4 <= trees / forest <= 0.6


def test_regrowth_accumulates_fractions_up_to_the_maximum(econ: Registry) -> None:
    """AC2: a node regrows at its configured rate up to its maximum."""
    tree = Node("n0", "tree", Coord(0, 0), stock=2)  # maximum 6, 1.5 per day
    days = []
    for _ in range(4):
        regrow([tree], econ)
        days.append((tree.stock, tree.regrow))
    assert days == [(3, 0.5), (5, 0.0), (6, 0.0), (6, 0.0)]


def test_regrowth_is_capped(econ: Registry) -> None:
    """AC2: regrowth never exceeds the maximum and drops the remainder."""
    tree = Node("n0", "tree", Coord(0, 0), stock=5, regrow=0.9)
    regrow([tree], econ)
    assert (tree.stock, tree.regrow) == (6, 0.0)


def test_reaching_the_maximum_drops_the_remainder(econ: Registry) -> None:
    """AC2: landing exactly on the maximum discards the fractional remainder."""
    tree = Node("n0", "tree", Coord(0, 0), stock=5)
    regrow([tree], econ)
    assert (tree.stock, tree.regrow) == (6, 0.0)


def test_overfull_stock_is_left_alone_and_full_nodes_do_not_stop_the_sweep(
    econ: Registry,
) -> None:
    """AC2: a node above its maximum is not reduced; later nodes still regrow."""
    over = Node("n0", "tree", Coord(0, 0), stock=8, regrow=0.7)
    low = Node("n1", "tree", Coord(1, 0), stock=1)
    regrow([over, low], econ)
    assert (over.stock, over.regrow) == (8, 0.0)
    assert (low.stock, low.regrow) == (2, 0.5)


def test_density_boundary_is_exclusive(econ: Registry, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: a roll equal to the density does not place a node."""

    class Fixed:
        def __init__(self, seed: str) -> None:
            pass

        def random(self) -> float:
            return 1.0

    monkeypatch.setattr("pericles.core.nodes.random.Random", Fixed)
    tilemap = TileMap(1, 1, ["forest"], [0.0])
    assert place_nodes(1, tilemap, econ) == []


def test_nodes_without_regrowth_stay_put(econ: Registry) -> None:
    """AC2: a node with rate 0 never regrows."""
    bush = Node("n1", "bush", Coord(0, 0), stock=1)
    regrow([bush], econ)
    assert (bush.stock, bush.regrow) == (1, 0.0)


def test_round_trip() -> None:
    node = Node("n3", "tree", Coord(4, 2), stock=1, regrow=0.25)
    assert node.to_dict() == {"id": "n3", "kind": "tree", "pos": [4, 2], "stock": 1, "regrow": 0.25}
    clone = Node.from_dict(node.to_dict())
    assert clone == node
    assert isinstance(clone.pos, Coord)
