import pytest

from pericles.core.geometry import Coord

pytestmark = pytest.mark.req("REQ-SIM-004")


def test_neighbours4_order_is_up_right_down_left() -> None:
    """AC1 (support): neighbour order is fixed, which keeps A* deterministic."""
    assert Coord(5, 5).neighbours4() == (Coord(5, 4), Coord(6, 5), Coord(5, 6), Coord(4, 5))


def test_manhattan() -> None:
    assert Coord(1, 2).manhattan(Coord(4, -2)) == 7
    assert Coord(3, 3).manhattan(Coord(3, 3)) == 0
