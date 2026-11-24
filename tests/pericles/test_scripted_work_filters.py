# ruff: noqa: E501 (the extra pack keeps one action per line)
"""Filters and arithmetic of the work rules, on a small custom registry (REQ-AGT-008, ADR-0016)."""

from collections.abc import Callable

import pytest
from conftest import ECON_PACK

from pericles.agents import rules
from pericles.agents.config import AgentConfig
from pericles.agents.view import Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry, load_registry
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.intents import Deposit, MoveTo, StartAction, Take
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
ROWS = ["." * 6 + "T" * 6] * 12
EXTRA = """
items:
  - {id: crumb, weight: 0.1, nutrition: 1, tags: [food]}
actions:
  - {id: a_berry, duration_ticks: 2, outputs: {berries: 1}, location: {node: bush}}
  - {id: a_frozen, duration_ticks: 2, outputs: {wood: 1}, tags: [sowing], location: {node: tree}}
  - {id: a_inputs, duration_ticks: 2, inputs: {seed: 1}, outputs: {wood: 1}, location: {node: tree}}
  - {id: a_tool, duration_ticks: 2, outputs: {wood: 1}, requires: {tools: [hammer]}, location: {node: tree}}
  - {id: a_know, duration_ticks: 2, outputs: {wood: 1}, requires: {knowledge: true}, location: {node: tree}}
  - {id: a_terrain, duration_ticks: 2, outputs: {wood: 1}, location: {node: tree, terrains: [forest]}}
  - {id: a_skill1, duration_ticks: 2, outputs: {wood: 1}, skill: carving, requires: {skill: carving, min_skill: 1}, location: {node: tree}}
  - {id: a_skill5, duration_ticks: 2, outputs: {wood: 1}, skill: carving, requires: {skill: carving, min_skill: 5}, location: {node: tree}}
"""


@pytest.fixture(scope="module")
def custom(tmp_path_factory: pytest.TempPathFactory) -> Registry:
    root = tmp_path_factory.mktemp("packs")
    base, extra = root / "econ", root / "extra"
    base.mkdir()
    extra.mkdir()
    (base / "content.yaml").write_text(ECON_PACK, encoding="utf-8")
    (extra / "content.yaml").write_text(EXTRA, encoding="utf-8")
    return load_registry([base, extra])


def view_of(
    registry: Registry,
    state: WorldState,
    memory: dict[str, Memory] | None = None,
    **cfg: object,
) -> View:
    ctx = Context.build(registry, default_config())
    config = AgentConfig(**cfg)  # type: ignore[arg-type]
    return View(
        ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), memory or {}
    )


def ids(actions: list) -> list[str]:  # type: ignore[type-arg]
    return [a.id for a in actions]


def test_jobs_keep_only_startable_node_actions_for_the_wanted_items(
    custom: Registry, make_world: MakeWorld
) -> None:
    """AC1: wanted output, no inputs, no tools, knowledge, terrain or unmet skill requirement."""
    plain = Villager("a", "A", Coord(0, 0))
    skilled = Villager("b", "B", Coord(0, 0), skills={"carving": 5.0, "woodcutting": 50.0})
    state = make_world(ROWS, [plain, skilled])
    view = view_of(custom, state)
    assert ids(rules.jobs(view, plain, ["wood"])) == ["a_frozen", "chop", "log"]
    assert ids(rules.jobs(view, skilled, ["wood"])) == [
        "a_frozen",
        "a_skill1",
        "a_skill5",
        "chop",
        "log",
    ]
    assert ids(rules.jobs(view, plain, ["berries"])) == ["a_berry", "pick"]
    both = ids(rules.jobs(view, skilled, ["plank", "wood"]))  # carve (no node) sorts before chop
    assert both == ["a_frozen", "a_skill1", "a_skill5", "chop", "log"]
    assert ids(rules.jobs(view, skilled, ["plank"])) == ["log"]  # not carve, tinker, nail, ...


def test_jobs_skip_actions_with_a_tag_blocked_this_season(
    custom: Registry, make_world: MakeWorld
) -> None:
    """AC1: in winter sowing is blocked; the other actions after it are still found."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    state.tick = 31 * 1440  # day 31: winter in the default calendar
    assert ids(rules.jobs(view_of(custom, state), a, ["wood"])) == ["chop", "log"]


def test_skill_score_is_one_plus_the_weighted_skill_share(
    custom: Registry, make_world: MakeWorld
) -> None:
    """AC1: skill counts only for the action's own skill; no skill or none held scores 1."""
    a = Villager("a", "A", Coord(0, 0), skills={"woodcutting": 50.0})
    b = Villager("b", "B", Coord(0, 0))
    view = view_of(custom, make_world(ROWS, [a, b]), skill_weight=2.0)
    max_skill = view.ctx.config.max_skill
    chop, pick = custom.actions["chop"], custom.actions["pick"]
    assert rules.skill_score(view, a, chop) == pytest.approx(1.0 + 2.0 * 50.0 / max_skill)
    assert rules.skill_score(view, b, chop) == 1.0
    assert rules.skill_score(view, a, pick) == 1.0


def test_fits_output_needs_room_for_one_unit(custom: Registry, make_world: MakeWorld) -> None:
    """AC1: exactly one unit of room is enough; none is not."""
    a = Villager("a", "A", Coord(0, 0))
    view = view_of(custom, make_world(ROWS, [a]))
    chop = custom.actions["chop"]
    a.inventory.add(custom, "wood", 14)  # 28 of 30: one wood fits
    assert rules.fits_output(view, a, chop)
    a.inventory.add(custom, "wood", 1)
    assert not rules.fits_output(view, a, chop)


def test_first_reachable_skips_what_cannot_be_carried(
    custom: Registry, make_world: MakeWorld
) -> None:
    """AC1: an output that does not fit is passed over for the next ranked action."""
    a = Villager("a", "A", Coord(2, 5))
    a.inventory.add(custom, "wood", 14)
    a.inventory.add(custom, "berries", 1)  # wood no longer fits, berries still do
    state = make_world(
        ROWS, [a], [Node("t", "tree", Coord(7, 2), 5), Node("b", "bush", Coord(2, 6), 5)]
    )
    ranked = [custom.actions["chop"], custom.actions["pick"]]
    decision = rules.first_reachable(view_of(custom, state), a, ranked)
    assert decision is not None and decision.job == "pick" and decision.target == "b"
    assert decision.intent == StartAction("a", "pick", "b")


def test_node_searches_honour_origin_and_radius(custom: Registry, make_world: MakeWorld) -> None:
    """AC1: gather and first_reachable search around the origin, within the radius."""
    a = Villager("a", "A", Coord(6, 2))
    trees = [Node("near", "tree", Coord(7, 2), 5), Node("far", "tree", Coord(11, 10), 5)]
    state = make_world(ROWS, [a], trees)
    view = view_of(custom, state)
    ranked = [custom.actions["chop"]]
    around_far = Coord(11, 9)
    for decision in (
        rules.gather(view, a, ["wood"], around_far, 3),
        rules.first_reachable(view, a, ranked, around_far, 3),
    ):
        assert decision is not None and decision.target == "far"
    a.pos = Coord(6, 6)  # both trees are now at least 5 away
    assert rules.gather(view, a, ["wood"], None, 3) is None
    assert rules.first_reachable(view, a, ranked, None, 3) is None
    assert rules.gather(view, a, ["wood"]) is not None


def test_demand_edge_cases(custom: Registry, make_world: MakeWorld) -> None:
    """AC1: no food reserve means no demand; one unit missing, or a one-nutrition food, counts."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    assert rules.demand(view_of(custom, state, food_reserve_per_capita=0.0), "crumb") == 0.0
    assert rules.demand(view_of(custom, state, food_reserve_per_capita=1.0), "crumb") == 1.0
    assert rules.demand(view_of(custom, state), "wood") == 0.0
    state.buildings["w"] = Building("w", "wall", Coord(1, 8), Ownership("communal"))
    assert rules.demand(view_of(custom, state), "wood") == 1.0  # a wall needs a single wood


def test_utility_shares_demand_among_the_others_on_an_output(
    custom: Registry, make_world: MakeWorld
) -> None:
    """AC1: demand / (1 + others on the output) scaled by skill; not its own rival."""
    a = Villager("a", "A", Coord(0, 0), skills={"woodcutting": 50.0})
    state = make_world(ROWS, [a, Villager("b", "B", Coord(0, 0))])
    state.buildings["w"] = Building("w", "wall", Coord(1, 8), Ownership("communal"))
    memory = {"a": Memory(job="chop"), "b": Memory(job="chop")}
    view = view_of(custom, state, memory)
    chop = custom.actions["chop"]
    expected = 1.0 / 2 * (1.0 + 50.0 / view.ctx.config.max_skill)
    assert rules.utility(view, a, chop) == pytest.approx(expected)


def test_deliver_targets_the_site(custom: Registry, make_world: MakeWorld) -> None:
    """AC1: both the delivery and the walk to it name the site as target."""
    a = Villager("a", "A", Coord(5, 2))
    a.inventory.add(custom, "wood", 3)
    state = make_world(ROWS, [a])
    state.buildings["w"] = Building("w", "wall", Coord(1, 8), Ownership("communal"))
    a.pos = Coord(1, 7)
    decision = rules.deliver(view_of(custom, state), a)
    assert decision is not None and decision.target == "w"
    assert decision.intent.__class__.__name__ == "Deliver"


def test_surplus_keeps_food_ration_and_whatever_sites_need(
    custom: Registry, make_world: MakeWorld
) -> None:
    """AC1: a needed item is kept (even one unit), the ration is kept, the rest is surplus."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    a.inventory.add(custom, "crumb", 70)  # 1 nutrition each: a 60-crumb ration
    a.inventory.add(custom, "berries", 6)  # 10 each: exactly the ration
    assert rules.surplus(view_of(custom, state), a) == [("crumb", 10)]
    a.inventory.add(custom, "plank", 2)
    a.inventory.add(custom, "wood", 3)
    state.buildings["w"] = Building("w", "wall", Coord(1, 8), Ownership("communal"))
    assert rules.surplus(view_of(custom, state), a) == [("crumb", 10), ("plank", 2)]
    del state.buildings["w"]
    state.buildings["v"] = Building("v", "vault", Coord(1, 8), Ownership("communal"))
    assert rules.surplus(view_of(custom, state), a) == [("crumb", 10), ("wood", 3)]


def storehouse(registry: Registry, state: WorldState, at: Coord, bid: str, room: int) -> Building:
    building = Building(bid, "storehouse", at, Ownership("communal"), complete=True)
    capacity = registry.buildings["storehouse"].storage
    building.storage.add(registry, "stone", capacity - room)
    state.buildings[bid] = building
    return building


def test_deposit_triggers_at_the_load_threshold(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: deposits start once the load reaches deposit_load of the carry limit, not before."""
    a = Villager("a", "A", Coord(2, 1))
    a.inventory.add(registry, "iron_ore", 10)  # 30 of 30
    state = make_world(ROWS, [a])
    storehouse(registry, state, Coord(3, 1), "st", 100)
    decision = rules.deposit(view_of(registry, state, deposit_load=1.0), a)
    assert decision is not None and decision.intent == Deposit("a", "st", "iron_ore", 10)
    assert decision.target == "st"
    a.inventory.remove("iron_ore", 1)
    assert rules.deposit(view_of(registry, state, deposit_load=1.0), a) is None
    assert rules.deposit(view_of(registry, state, deposit_load=0.99), a) is None
    assert rules.deposit(view_of(registry, state, deposit_load=0.5), a) is not None


def test_deposit_walks_to_a_store_with_room(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: full stores are skipped; a store with one slot takes one; far stores are walked to."""
    a = Villager("a", "A", Coord(2, 1))
    a.inventory.add(registry, "iron_ore", 10)
    state = make_world(ROWS, [a])
    storehouse(registry, state, Coord(3, 1), "s1", 0)
    storehouse(registry, state, Coord(2, 2), "s2", 1)
    view = view_of(registry, state, deposit_load=1.0)
    decision = rules.deposit(view, a)
    assert decision is not None and decision.intent == Deposit("a", "s2", "iron_ore", 1)
    assert decision.target == "s2"
    a.pos = Coord(9, 9)
    decision = rules.deposit(view_of(registry, state, deposit_load=1.0), a)
    assert decision is not None and isinstance(decision.intent, MoveTo)
    assert decision.target == "s2"
    del state.buildings["s2"]
    assert rules.deposit(view_of(registry, state, deposit_load=1.0), a) is None


def test_feed_takes_a_single_unit_and_names_the_store(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: one unit in a store is worth fetching, and the fetch names the store."""
    a = Villager("a", "A", Coord(2, 1), needs={"hunger": 60.0})
    state = make_world(ROWS, [a])
    store = storehouse(registry, state, Coord(3, 1), "s1", 100)
    store.storage.add(registry, "berries", 1)
    decision = rules.feed(view_of(registry, state), a)
    assert decision is not None and decision.intent == Take("a", "s1", "berries", 1)
    assert decision.target == "s1"
