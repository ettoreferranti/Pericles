import pytest

from pericles.core.buildings import (
    Building,
    Ownership,
    building_tiles,
    footprint,
    housing_capacity,
    near,
    remaining_cost,
    storage_capacity,
)
from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord


@pytest.mark.req("REQ-ECO-001")
@pytest.mark.parametrize(
    ("kind", "owners"), [("personal", ("a",)), ("shared", ("a", "b")), ("communal", ())]
)
def test_valid_ownerships(kind: str, owners: tuple[str, ...]) -> None:
    """AC1: ownership is personal(owner), shared(owners) or communal."""
    ownership = Ownership(kind, owners)
    assert ownership.to_dict() == {"kind": kind, "owners": list(owners)}
    assert Ownership.from_dict(ownership.to_dict()) == ownership


@pytest.mark.req("REQ-ECO-001")
@pytest.mark.parametrize(
    ("kind", "owners", "message"),
    [
        ("private", ("a",), "unknown ownership kind 'private'"),
        ("communal", ("a",), "communal ownership has no owners"),
        ("personal", (), "personal ownership needs exactly one owner"),
        ("personal", ("a", "b"), "personal ownership needs exactly one owner"),
        ("shared", ("a",), "shared ownership needs at least two owners"),
        ("shared", ("b", "a"), "owners must be sorted and unique"),
        ("shared", ("a", "a"), "owners must be sorted and unique"),
    ],
)
def test_invalid_ownerships(kind: str, owners: tuple[str, ...], message: str) -> None:
    """AC1: malformed ownership is rejected."""
    with pytest.raises(ValueError, match=f"^{message}$"):
        Ownership(kind, owners)


@pytest.mark.req("REQ-ECO-001")
def test_owned_by() -> None:
    """AC1: owners of personal and shared property; everyone for communal property."""
    assert Ownership("personal", ("a",)).owned_by("a")
    assert not Ownership("personal", ("a",)).owned_by("b")
    shared = Ownership("shared", ("a", "c"))
    assert shared.owned_by("c")
    assert not shared.owned_by("b")
    assert Ownership("communal").owned_by("anyone")


@pytest.mark.req("REQ-SIM-009")
def test_footprint_and_nearness() -> None:
    """AC1: footprints are row-major rectangles; 'near' is Manhattan distance ≤ 1."""
    assert footprint(Coord(3, 4), (2, 1)) == [Coord(3, 4), Coord(4, 4)]
    assert footprint(Coord(0, 0), (2, 2)) == [Coord(0, 0), Coord(1, 0), Coord(0, 1), Coord(1, 1)]
    tiles = footprint(Coord(3, 4), (2, 1))
    assert near(Coord(5, 4), tiles)
    assert near(Coord(3, 3), tiles)
    assert near(Coord(4, 4), tiles)
    assert not near(Coord(5, 5), tiles)
    assert not near(Coord(1, 4), tiles)


@pytest.mark.req("REQ-SIM-009")
def test_building_tiles_and_remaining_cost(econ: Registry) -> None:
    """AC2: the remaining cost shrinks as materials are delivered."""
    hut = Building("b0", "hut", Coord(1, 1), Ownership("personal", ("a",)))
    assert building_tiles(hut, econ) == [Coord(1, 1), Coord(2, 1)]
    assert remaining_cost(hut, econ) == {"wood": 4}
    hut.delivered["wood"] = 3
    assert remaining_cost(hut, econ) == {"wood": 1}
    hut.delivered["wood"] = 4
    assert remaining_cost(hut, econ) == {}
    wall = Building("b1", "wall", Coord(0, 0), Ownership("communal"))
    assert remaining_cost(wall, econ) == {"wood": 1}


@pytest.mark.req("REQ-SIM-009")
def test_capacities_exist_only_when_complete(econ: Registry) -> None:
    """AC3: a completed building provides its declared housing and storage."""
    hut = Building("b0", "hut", Coord(1, 1), Ownership("personal", ("a",)))
    assert (housing_capacity(econ, hut), storage_capacity(econ, hut)) == (0, 0)
    hut.complete = True
    assert (housing_capacity(econ, hut), storage_capacity(econ, hut)) == (2, 10)


def test_complete_flag_round_trips(econ: Registry) -> None:
    done = Building("b0", "hut", Coord(1, 1), Ownership("communal"), complete=True)
    assert Building.from_dict(done.to_dict()).complete is True


def test_building_round_trip(econ: Registry) -> None:
    hut = Building(
        "b0", "hut", Coord(1, 1), Ownership("shared", ("a", "b")), {"wood": 2}, 3.5, False
    )
    hut.storage.add(econ, "wood", 1)
    data = hut.to_dict()
    assert data == {
        "id": "b0",
        "kind": "hut",
        "origin": [1, 1],
        "ownership": {"kind": "shared", "owners": ["a", "b"]},
        "delivered": {"wood": 2},
        "work_done": 3.5,
        "complete": False,
        "storage": {"items": {"wood": 1}, "tools": []},
    }
    clone = Building.from_dict(data)
    assert clone == hut
    assert isinstance(clone.origin, Coord)
