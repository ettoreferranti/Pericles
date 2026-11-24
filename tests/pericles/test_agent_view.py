from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pericles.agents.config import AgentConfig
from pericles.agents.view import Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.intents import MoveTo
from pericles.core.nodes import Node
from pericles.core.state import Pregnancy, Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 12] * 12


def view_of(
    registry: Registry, state: WorldState, memory: dict[str, Memory] | None = None, **cfg: object
) -> View:
    config = AgentConfig(**cfg)  # type: ignore[arg-type]
    ctx = Context.build(registry, default_config())
    return View(
        ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), memory or {}
    )


def building(
    state: WorldState,
    bid: str,
    kind: str,
    at: Coord,
    *,
    complete: bool = True,
    owner: str | None = None,
) -> Building:
    ownership = Ownership("personal", (owner,)) if owner else Ownership("communal")
    state.buildings[bid] = Building(bid, kind, at, ownership, complete=complete)
    return state.buildings[bid]


@given(
    st.lists(st.tuples(st.integers(0, 40), st.integers(0, 40), st.integers(0, 3)), max_size=30),
    st.integers(0, 40),
    st.integers(0, 40),
    st.integers(0, 30),
    st.integers(1, 9),
)
def test_node_index_matches_brute_force(
    spots: list[tuple[int, int, int]], ox: int, oy: int, radius: int, cell: int
) -> None:
    """AC1: the grid index finds the same nearest node (distance, then id) as a full scan."""
    nodes = [Node(f"n{i:02d}", "tree", Coord(x, y), stock) for i, (x, y, stock) in enumerate(spots)]
    origin = Coord(ox, oy)
    expected = min(
        (
            (origin.manhattan(n.pos), n.id)
            for n in nodes
            if n.stock > 0 and origin.manhattan(n.pos) <= radius
        ),
        default=None,
    )
    found = NodeIndex(nodes, cell).nearest("tree", origin, radius, lambda n: n.stock > 0)
    assert (None if found is None else (origin.manhattan(found.pos), found.id)) == expected


def test_nearest_node_skips_depleted_avoided_and_far(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a mind is pointed at the nearest node it can actually use."""
    nodes = [
        Node("n0", "berry_bush", Coord(2, 0), 0),
        Node("n1", "berry_bush", Coord(3, 0), 5),
        Node("n2", "berry_bush", Coord(4, 0), 5),
        Node("n3", "berry_bush", Coord(11, 11), 5),
    ]
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a], nodes)
    memory = {"a": Memory(avoid={"n1": 10})}
    view = view_of(registry, state, memory, node_search_radius=6)
    node = view.nearest_node(a, "berry_bush")
    assert node is not None and node.id == "n2"
    state.tick = 10
    node = view_of(registry, state, memory, node_search_radius=6).nearest_node(a, "berry_bush")
    assert node is not None and node.id == "n1"
    far = view.nearest_node(a, "berry_bush", origin=Coord(11, 10), radius=1)
    assert far is not None and far.id == "n3"
    assert view.nearest_node(a, "boulder") is None


def test_level_takes_the_highest_need_with_that_relief(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: needs are found by their relief kind, not by content id."""
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": 40.0, "cold": 70.0})
    view = view_of(registry, make_world(ROWS, [a]))
    assert view.level(a, "eat") == 40.0
    assert view.level(a, "shelter") == 70.0
    assert view.level(a, "sleep") == 0.0


def test_go_targets_the_nearest_walkable_tile_next_to_the_goal(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: movement goals are reachable tiles beside water or a footprint."""
    rows = ["....", "..~~", "..~~", "...."]
    a = Villager("a", "A", Coord(0, 0))
    view = view_of(registry, make_world(rows, [a]))
    assert view.go(a, [Coord(3, 2)]) == MoveTo("a", Coord(3, 3))
    assert view.go(a, [Coord(1, 0)]) is None
    island = ["~~~", "~~~", "~~~", "..."]
    b = Villager("b", "B", Coord(0, 3))
    lost = view_of(registry, make_world(island, [b]))
    assert lost.go(b, [Coord(1, 0)]) == MoveTo("b", Coord(1, 0))


def test_food_items_rank_by_nutrition(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: food is any item with nutrition, best first."""
    view = view_of(registry, make_world(ROWS))
    assert view.foods
    assert list(view.foods) == sorted(view.foods, key=lambda i: (-registry.items[i].nutrition, i))
    assert all(registry.items[f].nutrition > 0 for f in view.foods)
    assert "wood" not in view.foods


def test_stores_are_complete_usable_and_by_distance(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a villager stores and takes only where it may, nearest first."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    building(state, "b0", "storehouse", Coord(8, 8))
    building(state, "b1", "storehouse", Coord(3, 0))
    building(state, "b2", "storehouse", Coord(1, 4), complete=False)
    building(state, "b3", "storehouse", Coord(0, 2), owner="z")
    building(state, "b4", "farm", Coord(5, 5))
    view = view_of(registry, state)
    assert [b.id for b in view.stores(a)] == ["b1", "b0"]
    assert view.room(state.buildings["b1"]) == registry.buildings["storehouse"].storage


def test_house_for_prefers_the_partner_home_and_respects_room(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: homes come from houses the villager may live in that have room."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", Coord(0, 0), sex="female", partner="b", pregnancy=Pregnancy("b", 99))
    b = Villager("b", "B", Coord(0, 0), sex="male", partner="a", home="h2")
    others = [Villager(f"o{i}", "O", Coord(0, 0), home="h1") for i in range(capacity - 1)]
    state = make_world(ROWS, [a, b, *others])
    building(state, "h1", "house", Coord(2, 2))
    building(state, "h2", "house", Coord(8, 8))
    view = view_of(registry, state)
    house = view.house_for(a)
    assert house is not None and house.id == "h2"
    b.home = None
    house = view_of(registry, state).house_for(a)
    assert house is not None and house.id == "h2"  # h1 has one bed left; a needs two
    for i in range(capacity):
        state.villagers[f"p{i}"] = Villager(f"p{i}", "P", Coord(0, 0), home="h2")
    assert view_of(registry, state).house_for(a) is None


def test_shortfalls_count_homeless_and_storage(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: the village plan counts homeless villagers against free housing, open sites included."""
    villagers = [Villager(f"v{i}", "V", Coord(0, 0)) for i in range(6)]
    state = make_world(ROWS, villagers)
    view = view_of(registry, state, storage_per_capita=10.0)
    assert view.housing_shortfall() == 6
    assert view.storage_shortfall() == 60.0
    building(state, "h1", "house", Coord(2, 2), complete=False)
    view = view_of(registry, state, storage_per_capita=10.0)
    assert view.housing_shortfall() == 6 - registry.buildings["house"].housing
    building(state, "s1", "storehouse", Coord(6, 6))
    assert view_of(registry, state, storage_per_capita=10.0).storage_shortfall() == 0.0


def test_free_origin_avoids_nodes_buildings_and_gap(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: placement looks outward from the village centre for a clear footprint."""
    rows = ["." * 9] * 9
    state = make_world(rows, nodes=[Node("n0", "berry_bush", Coord(4, 4), 5)])
    view = view_of(registry, state, site_search_radius=4, site_gap=1)
    origin = view.free_origin("house")
    assert origin is not None
    tiles = {Coord(origin.x + dx, origin.y + dy) for dx in range(2) for dy in range(2)}
    assert Coord(4, 4) not in tiles
    building(state, "b0", "house", origin)
    second = view_of(registry, state, site_search_radius=4, site_gap=1).free_origin("house")
    assert second is not None
    second_tiles = {Coord(second.x + dx, second.y + dy) for dx in range(2) for dy in range(2)}
    assert min(p.manhattan(q) for p in tiles for q in second_tiles) > 1
    tiny = make_world(["..", ".."])
    assert view_of(registry, tiny, site_search_radius=0).free_origin("storehouse") is None


def test_workers_builders_and_placing_read_memory(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: other villagers' jobs and claims spread the work."""
    a = Villager("a", "A", Coord(0, 0))
    b = Villager("b", "B", Coord(0, 0))
    state = make_world(ROWS, [a, b])
    memory = {
        "a": Memory(job="gather_berries"),
        "b": Memory(job="gather_berries", target="place:house"),
    }
    view = view_of(registry, state, memory)
    assert view.workers("berries", exclude="a") == 1
    assert view.workers("wood", exclude="a") == 0
    assert view.placing("house", exclude="a")
    assert not view.placing("house", exclude="b")
    memory["b"] = Memory(job="construct", target="s1")
    assert view_of(registry, state, memory).builders("s1", exclude="a") == 1


def test_guardian_is_the_first_living_parent(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a child follows a living parent."""
    mum = Villager("m", "M", Coord(0, 0))
    kid = Villager("k", "K", Coord(0, 0), adult=False, parents=("d", "m"))
    view = view_of(registry, make_world(ROWS, [mum, kid]))
    guardian = view.guardian(kid)
    assert guardian is not None and guardian.id == "m"
    orphan = Villager("o", "O", Coord(0, 0), adult=False, parents=("x", "y"))
    assert view.guardian(orphan) is None


def test_memory_round_trips() -> None:
    """AC1: controller memory serialises for snapshots."""
    memory = Memory(target="n1", job="fell_tree", idle_until=9, avoid={"n2": 30, "b0": 12})
    assert Memory.from_dict(memory.to_dict()) == memory
    assert list(memory.to_dict()["avoid"]) == ["b0", "n2"]


def test_homes_stock_and_sites(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: homes, food stock and open sites are read from the world."""
    a = Villager("a", "A", Coord(2, 2), home="h1")
    b = Villager("b", "B", Coord(9, 9), home="h2")
    state = make_world(ROWS, [a, b])
    building(state, "h1", "house", Coord(2, 3))
    building(state, "h2", "house", Coord(5, 5), complete=False)
    state.villagers["a"].inventory.add(registry, "berries", 4)
    state.buildings["h1"].storage.add(registry, "berries", 2)
    state.buildings["h2"].delivered["wood"] = 4
    view = view_of(registry, state, food_reserve_per_capita=7.0)
    home = view.home(a)
    assert home is not None and home.id == "h1"
    assert view.home(b) is None
    assert view.at_home(a) and not view.at_home(b)
    assert view.food_stock() == registry.items["berries"].nutrition * 6
    assert view.food_target() == 14.0
    assert [s.id for s in view.sites()] == ["h2"]
    assert dict(view.needed()) == {"wood": 6, "stone": 4}


def test_center_is_the_first_communal_store(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: the village centre is its earliest communal store, else the start."""
    state = make_world(ROWS)
    start = view_of(registry, state).center()
    building(state, "b2", "storehouse", Coord(7, 7))
    building(state, "b1", "storehouse", Coord(3, 3))
    building(state, "b0", "storehouse", Coord(1, 1), owner="z")
    assert view_of(registry, state).center() == Coord(3, 3)
    assert start == state.tilemap.start()


def test_go_with_no_tiles_is_already_there(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: an empty goal needs no move."""
    a = Villager("a", "A", Coord(0, 0))
    assert view_of(registry, make_world(ROWS, [a])).go(a, []) is None


def test_house_for_picks_nearest_then_id_and_skips_foreign_houses(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: the nearest usable house wins, ties go to the lower id, others' houses are skipped."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    building(state, "a_far", "house", Coord(8, 8))
    building(state, "z_near", "house", Coord(3, 0))
    building(state, "c_mine", "house", Coord(0, 5), owner="a")
    building(state, "d_theirs", "house", Coord(1, 0), owner="z")
    building(state, "e_site", "house", Coord(1, 1), complete=False)
    house = view_of(registry, state).house_for(a)
    assert house is not None and house.id == "z_near"
    building(state, "b_tie", "house", Coord(0, 3))
    house = view_of(registry, state).house_for(a)
    assert house is not None and house.id == "b_tie"
    del state.buildings["b_tie"]
    del state.buildings["z_near"]
    del state.buildings["a_far"]
    house = view_of(registry, state).house_for(a)
    assert house is not None and house.id == "c_mine"


def test_house_for_follows_a_partner_into_their_personal_house(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a villager may move into a house owned by their partner, and keeps their own bed."""
    a = Villager("a", "A", Coord(0, 0), partner="b", home="p")
    b = Villager("b", "B", Coord(0, 0), partner="a", home="p")
    state = make_world(ROWS, [a, b])
    building(state, "p", "house", Coord(5, 5), owner="b")
    capacity = registry.buildings["house"].housing
    for i in range(capacity):
        state.villagers[f"x{i}"] = Villager(f"x{i}", "X", Coord(0, 0), home="p")
    house = view_of(registry, state).house_for(a)
    assert house is not None and house.id == "p"
    assert view_of(registry, state).house_for(Villager("n", "N", Coord(0, 0))) is None


def test_housing_shortfall_counts_free_communal_beds_and_can_go_negative(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: occupied beds, personal houses and surplus beds all shift the shortfall."""
    capacity = registry.buildings["house"].housing
    a = Villager("a", "A", Coord(0, 0), home="c1")
    b = Villager("b", "B", Coord(0, 0), home="p1")
    c = Villager("c", "C", Coord(0, 0))
    state = make_world(ROWS, [a, b, c])
    building(state, "c1", "house", Coord(2, 2))
    building(state, "p1", "house", Coord(6, 6), owner="b")
    view = view_of(registry, state)
    assert view.housing_shortfall() == 1 - (capacity - 1)
    building(state, "c2", "house", Coord(8, 2), complete=False)
    building(state, "f1", "farm", Coord(2, 8))
    assert view_of(registry, state).housing_shortfall() == 1 - (capacity - 1) - capacity
    assert view_of(registry, state).housing_shortfall() < 0


def test_free_origin_breaks_ties_by_row_then_column(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: of equally near clear origins the topmost, then leftmost, is taken."""
    state = make_world(ROWS)
    centre = state.tilemap.start()
    state.nodes["n0"] = Node("n0", "berry_bush", centre, 5)
    view = view_of(registry, state, site_search_radius=3, site_gap=0)
    assert view.free_origin("house") == Coord(centre.x + 1, centre.y)
    assert view.free_origin("house") == Coord(centre.x + 1, centre.y)
