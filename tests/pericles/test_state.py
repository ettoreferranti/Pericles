from collections.abc import Callable

import pytest

from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import Modifier, Op, Scope, Target
from pericles.core.nodes import Node
from pericles.core.state import Activity, Deceased, Pregnancy, Proposal, Villager, WorldState

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


def rich_state(econ: Registry) -> WorldState:
    tilemap = TileMap(3, 1, ["grass", "forest", "grass"], [0.0] * 3)
    villager = Villager(
        "a",
        "Ana",
        Coord(0, 0),
        skills={"woodcutting": 2.5},
        knowledge={"lore", "commons"},
        traits=("strong",),
    )
    villager.inventory.add(econ, "wood", 2)
    villager.inventory.add(econ, "axe", 1)
    reserved = Inventory()
    reserved.add(econ, "seed", 1)
    villager.activity = Activity("action", "sow", None, 5.0, 2.0, 1.0, reserved)
    state = WorldState.new(7, tilemap, [villager], nodes=[Node("n0", "tree", Coord(1, 0), 4, 0.5)])
    state.buildings["b0"] = Building(
        "b0", "hut", Coord(2, 0), Ownership("personal", ("a",)), {"wood": 1}
    )
    state.village_knowledge = {"commons"}
    state.next_building = 1
    return state


def test_gameplay_state_round_trips(econ: Registry) -> None:
    """AC1: nodes, buildings, inventories, skills, knowledge and work survive a round trip."""
    state = rich_state(econ)
    clone = WorldState.from_dict(state.to_dict())
    assert clone.digest() == state.digest()
    assert clone.villagers == state.villagers
    assert clone.nodes == state.nodes
    assert clone.buildings == state.buildings
    assert (clone.village_knowledge, clone.next_building) == ({"commons"}, 1)


def test_villager_dict_is_canonical(econ: Registry) -> None:
    """AC1: sets and dicts serialise in sorted order."""
    data = rich_state(econ).to_dict()["villagers"][0]
    assert data["knowledge"] == ["commons", "lore"]
    assert data["skills"] == {"woodcutting": 2.5}
    assert data["traits"] == ["strong"]
    assert data["inventory"] == {"items": {"wood": 2}, "tools": [{"item": "axe", "durability": 3}]}
    assert data["activity"] == {
        "kind": "action",
        "ident": "sow",
        "target": None,
        "work": 5.0,
        "done": 2.0,
        "speed": 1.0,
        "reserved": {"items": {"seed": 1}, "tools": []},
    }


def _set_stock(s: WorldState) -> None:
    s.nodes["n0"].stock = 3


def _add_village_knowledge(s: WorldState) -> None:
    s.village_knowledge.add("x")


def _bump_building_counter(s: WorldState) -> None:
    s.next_building = 2


def _train(s: WorldState) -> None:
    s.villagers["a"].skills["woodcutting"] = 3.0


def _stop_work(s: WorldState) -> None:
    s.villagers["a"].activity = None


def _deliver_more(s: WorldState) -> None:
    s.buildings["b0"].delivered["wood"] = 2


@pytest.mark.parametrize(
    "mutate",
    [_set_stock, _add_village_knowledge, _bump_building_counter, _train, _stop_work, _deliver_more],
)
def test_digest_covers_gameplay_fields(econ: Registry, mutate: object) -> None:
    """AC1: every gameplay field is part of the state digest."""
    base = rich_state(econ).digest()
    state = rich_state(econ)
    mutate(state)  # type: ignore[operator]
    assert state.digest() != base


def test_duplicate_node_ids_are_rejected(small_map: TileMap) -> None:
    nodes = [Node("n0", "tree", Coord(0, 0), 1), Node("n0", "tree", Coord(1, 0), 1)]
    with pytest.raises(ValueError, match="duplicate node id 'n0'"):
        WorldState.new(1, small_map, nodes=nodes)


def test_new_world_has_empty_gameplay_fields(small_map: TileMap) -> None:
    state = WorldState.new(1, small_map)
    assert (state.nodes, state.buildings, state.village_knowledge, state.next_building) == (
        {},
        {},
        set(),
        0,
    )


def test_activity_target_round_trips() -> None:
    """AC1: a construction target survives a round trip; no target stays None."""
    with_target = Activity("build", "hut", "b0", 20.0, 1.0, 1.5)
    assert Activity.from_dict(with_target.to_dict()) == with_target
    assert Activity.from_dict(with_target.to_dict()).target == "b0"
    without = Activity("action", "sow", None, 5.0, 0.0, 1.0)
    assert Activity.from_dict(without.to_dict()).target is None


def full_villager() -> Villager:
    return Villager(
        "v1",
        "Ana",
        Coord(1, 2),
        inventory=Inventory({"berries": 2}),
        sex="female",
        born_tick=-500,
        adult=False,
        needs={"hunger": 12.5, "cold": 3.0},
        damage=4.0,
        home="b0",
        partner="v2",
        parents=("v7", "v8"),
        pregnancy=Pregnancy("v2", 900),
        last_birth_tick=100,
        model="llama",
        witnessed=[{"tick": 3, "kind": "born", "data": {"villager": "v1"}}],
        memories=[{"tick": 1, "kind": "died", "data": {"villager": "v9"}}],
    )


def test_life_fields_have_neutral_defaults() -> None:
    """A villager built without life fields is a healthy adult of unknown sex with no family."""
    villager = Villager("v1", "Ana", Coord(0, 0))
    assert villager.sex is None
    assert (villager.born_tick, villager.adult, villager.damage) == (0, True, 0.0)
    assert villager.needs == {} and villager.parents == () and villager.witnessed == []
    assert villager.home is None and villager.partner is None and villager.pregnancy is None
    assert villager.last_birth_tick is None and villager.model is None and villager.memories == []


def test_a_villager_with_life_fields_round_trips() -> None:
    """Snapshots keep every life field (REQ-EXP-003 AC3 resume needs the full state)."""
    villager = full_villager()
    data = villager.to_dict()
    assert list(data["needs"]) == ["cold", "hunger"]
    assert Villager.from_dict(data) == villager


def test_world_life_fields_round_trip() -> None:
    """The dead, open proposals and the id counter survive a snapshot."""
    tilemap = TileMap(2, 2, ["grass"] * 4, [0.0] * 4)
    state = WorldState.new(1, tilemap, [full_villager()])
    state.dead["v9"] = Deceased("v9", "Old", "male", -9000, 40, "old_age", ("v5",), "qwen")
    state.dead["v3"] = Deceased("v3", "Kid", None, 10, 20, "cold", (), None)
    state.proposals["v1"] = Proposal("v2", 70)
    state.next_villager = 12
    data = state.to_dict()
    assert [d["id"] for d in data["dead"]] == ["v3", "v9"]
    assert list(data["proposals"]) == ["v1"]
    restored = WorldState.from_dict(data)
    assert restored.dead == state.dead
    assert restored.proposals == state.proposals
    assert restored.next_villager == 12
    assert restored.digest() == state.digest()


@pytest.mark.parametrize(
    "change",
    [
        lambda v: setattr(v, "damage", 5.0),
        lambda v: v.needs.update(hunger=13.0),
        lambda v: setattr(v, "partner", None),
        lambda v: setattr(v, "adult", True),
        lambda v: setattr(v, "pregnancy", None),
        lambda v: setattr(v, "model", "qwen"),
        lambda v: v.witnessed.append({"tick": 4, "kind": "died", "data": {}}),
    ],
)
def test_life_fields_feed_the_digest(change: Callable[[Villager], object]) -> None:
    """Every life field is part of the canonical state."""
    tilemap = TileMap(2, 2, ["grass"] * 4, [0.0] * 4)
    before = WorldState.new(1, tilemap, [full_villager()])
    after = WorldState.new(1, tilemap, [full_villager()])
    change(after.villagers["v1"])
    assert after.digest() != before.digest()


def test_life_pack_loads(life: Registry) -> None:
    """The life test pack adds needs, a hardy trait, a lodge, a cabin and a light action."""
    assert sorted(life.needs) == ["cold", "fatigue", "hunger"]
    assert life.needs["hunger"].relief == "eat"
    assert life.buildings["lodge"].housing == 8
    assert "light" in life.actions["glean"].tags
