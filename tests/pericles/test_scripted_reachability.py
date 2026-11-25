"""Scripted villagers neither choose places they cannot reach nor retry ones they failed to
reach (ADR-0016 §3-§4)."""

from collections.abc import Callable
from typing import Any

import pytest

from pericles.agents import rules
from pericles.agents.config import AgentConfig
from pericles.agents.scripted import scripted_controller
from pericles.agents.view import Memory, NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import SetHome, Sleep
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

pytestmark = pytest.mark.req("REQ-AGT-008")
MakeWorld = Callable[..., WorldState]
# A 16 x 16 meadow; water rings tiles (7..10, 7..10), around the map centre (8, 8).
RING = [
    "." * 16
    if y < 6 or y > 11
    else ("." * 6 + "~" * 6 + "." * 4 if y in (6, 11) else "......~....~....")
    for y in range(16)
]
INSIDE, OUTSIDE = Coord(8, 8), Coord(2, 2)


def inside(c: Coord) -> bool:
    return 7 <= c.x <= 10 and 7 <= c.y <= 10


def view_of(
    registry: Registry, state: WorldState, memory: dict[str, Memory] | None = None, **cfg: object
) -> View:
    ctx = Context.build(registry, default_config())
    config = AgentConfig(**cfg)  # type: ignore[arg-type]
    return View(
        ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), memory or {}
    )


def run(
    registry: Registry, state: WorldState, ticks: int, log: Any, **cfg: object
) -> tuple[WorldState, list[str]]:
    engine = Engine(registry, default_config())
    controller = scripted_controller(engine.context, AgentConfig(**cfg))  # type: ignore[arg-type]
    kinds: list[str] = []
    for _ in range(ticks):
        state, events = engine.step(state, controller.intents(state))
        log.record(controller.memory, state.tick, events)
        controller.observe(state, events)
        kinds.extend(e.kind for e in events)
    return state, kinds


def fed(registry: Registry, villager: Villager) -> Villager:
    villager.inventory.add(registry, "berries", 20)
    return villager


def housed_outside(state: WorldState) -> None:
    state.buildings["h0"] = Building(
        "h0", "house", Coord(1, 13), Ownership("communal"), complete=True
    )
    for villager in state.villagers.values():
        villager.home = "h0"


def test_the_ring_map_encloses_the_centre(make_world: MakeWorld) -> None:
    """AC1: the fixture really cuts the centre off (water all round tiles 7..10)."""
    state = make_world(RING)
    assert state.tilemap.start() == INSIDE
    assert all(len(row) == 16 for row in RING)
    assert {state.tilemap.terrain_at(Coord(x, 6)) for x in range(6, 12)} == {"water"}
    assert {state.tilemap.terrain_at(Coord(6, y)) for y in range(6, 12)} == {"water"}
    assert {state.tilemap.terrain_at(Coord(11, y)) for y in range(6, 12)} == {"water"}
    assert {state.tilemap.terrain_at(Coord(x, 11)) for x in range(6, 12)} == {"water"}


def test_free_origin_offers_only_sites_the_villager_can_reach(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: the nearest clear spot to the centre lies inside the ring; a villager outside is
    offered the nearest one outside it, a villager inside the one inside."""
    state = make_world(RING, [Villager("a", "A", OUTSIDE), Villager("b", "B", Coord(9, 9))])
    view = view_of(registry, state)
    anywhere = view.free_origin("house")
    assert anywhere is not None and inside(anywhere)
    out = view.free_origin("house", OUTSIDE)
    assert out is not None and not inside(out)
    assert state.tilemap.terrain_at(out) == "grass"
    assert view.free_origin("house", Coord(9, 9)) == anywhere
    # A villager on an impassable tile starts from the tiles beside it.
    assert view.free_origin("house", Coord(6, 8)) is not None


def test_homeless_villagers_with_materials_place_a_house_they_can_reach(
    registry: Registry, make_world: MakeWorld, failure_log: Callable[[], Any]
) -> None:
    """AC1: with the village centre cut off by water, homeless villagers holding a house's
    materials still place one (outside the ring) instead of failing to walk to the centre."""
    a, b = (
        fed(registry, Villager("a", "A", OUTSIDE)),
        fed(registry, Villager("b", "B", Coord(3, 2))),
    )
    for item, qty in registry.buildings["house"].cost.items():
        a.inventory.add(registry, item, qty)
    state = make_world(RING, [a, b], [Node("n0", "berry_bush", Coord(1, 1), 50)])
    log = failure_log()
    state, kinds = run(registry, state, 200, log)
    assert "site_placed" in kinds
    assert [b for b in state.buildings.values() if not inside(b.origin)] == list(
        state.buildings.values()
    )
    assert "move_failed" not in kinds


def test_an_unreachable_supplied_site_is_not_retried_while_avoided(
    registry: Registry, make_world: MakeWorld, failure_log: Callable[[], Any]
) -> None:
    """AC1: a builder who cannot reach a supplied site avoids it for avoid_ticks."""
    state = make_world(RING, [fed(registry, Villager("a", "A", OUTSIDE))])
    housed_outside(state)
    state.buildings["s1"] = Building(
        "s1",
        "house",
        INSIDE,
        Ownership("communal"),
        delivered=dict(registry.buildings["house"].cost),
    )
    log = failure_log()
    run(registry, state, AgentConfig().avoid_ticks, log, storage_per_capita=0.0)
    assert [t for _, _, t in log.failures][:1] == ["s1"]
    assert log.repeats(AgentConfig().avoid_ticks) == []


def test_an_unreachable_delivery_target_is_not_retried_while_avoided(
    registry: Registry, make_world: MakeWorld, failure_log: Callable[[], Any]
) -> None:
    """AC1: a villager holding what a site needs, who cannot reach it, avoids it for
    avoid_ticks."""
    a = fed(registry, Villager("a", "A", OUTSIDE))
    a.inventory.add(registry, "wood", 3)
    state = make_world(RING, [a])
    housed_outside(state)
    state.buildings["s1"] = Building("s1", "house", INSIDE, Ownership("communal"))
    log = failure_log()
    run(registry, state, AgentConfig().avoid_ticks, log, storage_per_capita=0.0)
    assert [t for _, _, t in log.failures][:1] == ["s1"]
    assert log.repeats(AgentConfig().avoid_ticks) == []


def test_an_unreachable_home_is_not_retried_while_avoided(
    registry: Registry, make_world: MakeWorld, failure_log: Callable[[], Any]
) -> None:
    """AC1: a tired, cold villager whose home it cannot reach avoids it for avoid_ticks."""
    sleep_at, cold_at = AgentConfig().act_at["sleep"], AgentConfig().act_at["shelter"]
    a = fed(registry, Villager("a", "A", OUTSIDE, needs={"fatigue": sleep_at, "cold": cold_at}))
    state = make_world(RING, [a])
    state.buildings["h0"] = Building("h0", "house", INSIDE, Ownership("communal"), complete=True)
    a.home = "h0"
    log = failure_log()
    run(registry, state, AgentConfig().avoid_ticks, log, storage_per_capita=0.0)
    assert [t for _, _, t in log.failures][:1] == ["h0"]
    assert log.repeats(AgentConfig().avoid_ticks) == []


def test_an_avoided_home_means_sleeping_in_place_and_no_trip_for_shelter(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: sleep happens where the villager stands, and shelter passes, while home is
    avoided; with home not avoided both head home."""
    sleep_at, cold_at = AgentConfig().act_at["sleep"], AgentConfig().act_at["shelter"]
    a = Villager("a", "A", OUTSIDE, needs={"fatigue": sleep_at, "cold": cold_at}, home="h0")
    state = make_world(RING, [a])
    state.buildings["h0"] = Building(
        "h0", "house", Coord(12, 13), Ownership("communal"), complete=True
    )
    fresh = view_of(registry, state)
    assert rules.sleep(fresh, a) is not None and rules.sleep(fresh, a).target == "h0"  # type: ignore[union-attr]
    assert rules.shelter(fresh, a) is not None and rules.shelter(fresh, a).target == "h0"  # type: ignore[union-attr]
    avoided = view_of(registry, state, {"a": Memory(avoid={"h0": state.tick + 5})})
    decision = rules.sleep(avoided, a)
    assert decision is not None and (decision.intent, decision.target) == (Sleep("a"), None)
    assert rules.shelter(avoided, a) is None


def test_avoided_sites_are_skipped_for_building_and_delivery(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: build and deliver pass over an avoided site for the next one."""
    a = Villager("a", "A", OUTSIDE, home="h0")
    a.inventory.add(registry, "wood", 3)
    state = make_world(RING, [a])
    state.buildings["h0"] = Building(
        "h0", "house", Coord(1, 13), Ownership("communal"), complete=True
    )
    cost = dict(registry.buildings["house"].cost)
    state.buildings["s1"] = Building(
        "s1", "house", Coord(2, 4), Ownership("communal"), delivered=cost
    )
    state.buildings["s2"] = Building(
        "s2", "house", Coord(12, 2), Ownership("communal"), delivered=cost
    )
    state.buildings["s3"] = Building("s3", "house", Coord(2, 8), Ownership("communal"))
    state.buildings["s4"] = Building("s4", "house", Coord(13, 13), Ownership("communal"))
    fresh = view_of(registry, state, storage_per_capita=0.0)
    assert rules.build(fresh, a).target == "s1"  # type: ignore[union-attr]
    assert rules.deliver(fresh, a).target == "s3"  # type: ignore[union-attr]
    memory = {"a": Memory(avoid={"s1": state.tick + 5, "s3": state.tick + 5})}
    avoided = view_of(registry, state, memory, storage_per_capita=0.0)
    assert rules.build(avoided, a).target == "s2"  # type: ignore[union-attr]
    assert rules.deliver(avoided, a).target == "s4"  # type: ignore[union-attr]


def test_avoided_houses_are_not_taken_as_homes(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a homeless villager skips an avoided house for the next; a couple does not move
    to an avoided couple house."""
    a = Villager("a", "A", OUTSIDE)
    state = make_world(RING, [a])
    for bid, at in (("h0", Coord(2, 4)), ("h1", Coord(12, 2))):
        state.buildings[bid] = Building(bid, "house", at, Ownership("communal"), complete=True)
    assert rules.home(view_of(registry, state), a).intent == SetHome("a", "h0")  # type: ignore[union-attr]
    avoid_h0 = {"a": Memory(avoid={"h0": state.tick + 5})}
    assert rules.home(view_of(registry, state, avoid_h0), a).intent == SetHome("a", "h1")  # type: ignore[union-attr]
    both = {"a": Memory(avoid={"h0": state.tick + 5, "h1": state.tick + 5})}
    assert rules.home(view_of(registry, state, both), a) is None
    # A couple apart: each partner's home fits both, so they choose one; avoided, they wait.
    b = Villager("b", "B", Coord(12, 3), partner="a", home="h1")
    a.partner, a.home = "b", "h0"
    state.villagers["b"] = b
    chosen = rules.home(view_of(registry, state), a)
    assert chosen is not None and isinstance(chosen.intent, SetHome)
    target = chosen.intent.building
    assert target == "h1"
    avoid_target = {"a": Memory(avoid={target: state.tick + 5})}
    assert rules.home(view_of(registry, state, avoid_target), a) is None
