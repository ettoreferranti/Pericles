import pytest

from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import Modifier, Op, Scope, Target
from pericles.core.state import Villager, WorldState

pytestmark = pytest.mark.req("REQ-SIM-002")


def make_state(small_map: TileMap) -> WorldState:
    state = WorldState.new(
        42,
        small_map,
        [Villager("b", "Bo", Coord(12, 12)), Villager("a", "Ana", Coord(11, 12))],
    )
    state.villagers["a"].path = [Coord(12, 12)]
    state.villagers["a"].move_progress = 0.5
    state.modifiers = (
        Modifier(Target("action"), "work_speed", Op.MUL, 1.2, "test", Scope(until_tick=10)),
    )
    state.rng.random()
    return state


def test_round_trip_preserves_everything_including_rng(small_map: TileMap) -> None:
    """AC1 (support): a state can be saved and restored exactly."""
    state = make_state(small_map)
    clone = WorldState.from_dict(state.to_dict())
    assert clone.digest() == state.digest()
    assert clone.rng.random() == state.rng.random()
    assert clone.villagers["a"].path == [Coord(12, 12)]
    assert isinstance(clone.villagers["a"].pos, Coord)


def test_new_state_is_seeded_and_ordered(small_map: TileMap) -> None:
    a = WorldState.new(
        1, small_map, [Villager("b", "Bo", Coord(1, 1)), Villager("a", "A", Coord(2, 2))]
    )
    b = WorldState.new(
        1, small_map, [Villager("a", "A", Coord(2, 2)), Villager("b", "Bo", Coord(1, 1))]
    )
    c = WorldState.new(
        2, small_map, [Villager("a", "A", Coord(2, 2)), Villager("b", "Bo", Coord(1, 1))]
    )
    assert a.tick == 0 and a.modifiers == ()
    assert a.digest() == b.digest()
    assert a.digest() != c.digest()
    assert list(a.villagers) == ["a", "b"]


def test_duplicate_villager_ids_are_rejected(small_map: TileMap) -> None:
    with pytest.raises(ValueError, match="duplicate villager id 'a'"):
        WorldState.new(
            1, small_map, [Villager("a", "A", Coord(1, 1)), Villager("a", "B", Coord(2, 2))]
        )


def test_digest_changes_with_any_field(small_map: TileMap) -> None:
    base = make_state(small_map).digest()
    for mutate in (
        lambda s: setattr(s, "tick", 1),
        lambda s: setattr(s.villagers["b"], "pos", Coord(0, 0)),
        lambda s: setattr(s.villagers["a"], "move_progress", 0.75),
        lambda s: setattr(s, "modifiers", ()),
        lambda s: s.rng.random(),
    ):
        state = make_state(small_map)
        mutate(state)
        assert state.digest() != base
