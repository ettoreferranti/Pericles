import itertools
from dataclasses import dataclass

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pericles.core.content.registry import Registry, base_pack_path, load_registry
from pericles.core.engine import Engine
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo, Wait
from pericles.core.mapgen import Band, MapParams, TileMap, generate_map
from pericles.core.modifiers import Modifier, Op, Scope, Target
from pericles.core.state import Villager, WorldState


def fresh(small_map: TileMap, seed: int = 5) -> WorldState:
    return WorldState.new(
        seed,
        small_map,
        [Villager(v, v.upper(), Coord(10 + i, 12)) for i, v in enumerate(["a", "b", "c"])],
    )


def walkable_targets(small_map: TileMap, registry: Registry) -> list[Coord]:
    return [
        Coord(x, y)
        for y in range(small_map.height)
        for x in range(small_map.width)
        if registry.terrains[small_map.terrain_at(Coord(x, y))].walkable
    ]


def as_dicts(events: list[Event]) -> list[dict[str, object]]:
    return [e.to_dict() for e in events]


@pytest.mark.req("REQ-SIM-002")
def test_identical_inputs_give_identical_runs(registry: Registry, small_map: TileMap) -> None:
    """AC1: identical state, intents and seed → identical state and events."""
    targets = walkable_targets(small_map, registry)

    def run() -> tuple[str, list[dict[str, object]]]:
        engine, state = Engine(registry), fresh(small_map)
        log: list[dict[str, object]] = []
        for tick in range(60):
            intents: list[Intent] = []
            if tick % 20 == 0:
                intents = [
                    MoveTo(v, targets[(tick * 7 + i * 31) % len(targets)])
                    for i, v in enumerate("abc")
                ]
            state, events = engine.step(state, intents)
            log += as_dicts(events)
        return state.digest(), log

    assert run() == run()


@pytest.mark.req("REQ-SIM-002")
def test_submission_order_does_not_matter(registry: Registry, small_map: TileMap) -> None:
    """AC2: intents in any order resolve identically (including conflicts)."""
    targets = walkable_targets(small_map, registry)
    intents: list[Intent] = [
        MoveTo("a", targets[3]),
        MoveTo("a", targets[40]),
        MoveTo("b", targets[90]),
        Wait("c"),
        MoveTo("ghost", targets[1]),
    ]
    outcomes = set()
    for perm in itertools.permutations(intents):
        state, events = Engine(registry).step(fresh(small_map), list(perm))
        outcomes.add((state.digest(), str(as_dicts(events))))
    assert len(outcomes) == 1


@pytest.mark.req("REQ-SIM-002")
@settings(max_examples=30, deadline=None)
@given(st.permutations(list(range(6))))
def test_submission_order_property(order: list[int]) -> None:
    """AC2 (property): any permutation of a tick's intents gives the same result."""
    registry = load_registry([base_pack_path()])
    tilemap = generate_map(
        1, MapParams(12, 12, (Band("grass", 1.0),), start_terrain="grass"), registry
    )

    def villagers() -> list[Villager]:
        return [Villager(f"v{i}", f"V{i}", Coord(i, 0)) for i in range(6)]

    intents = [MoveTo(f"v{i}", Coord(11 - i, 11)) for i in range(6)]
    baseline = Engine(registry).step(WorldState.new(3, tilemap, villagers()), intents)
    shuffled = Engine(registry).step(
        WorldState.new(3, tilemap, villagers()),
        [intents[i] for i in order],
    )
    assert shuffled[0].digest() == baseline[0].digest()
    assert as_dicts(shuffled[1]) == as_dicts(baseline[1])


@pytest.mark.req("REQ-SIM-002")
def test_tick_increments_and_events_carry_processed_tick(
    registry: Registry, small_map: TileMap
) -> None:
    """AC3 (support): state.tick counts processed ticks; events carry the tick processed."""
    engine, state = Engine(registry), fresh(small_map)
    state, events = engine.step(state, [MoveTo("ghost", Coord(0, 0))])
    assert state.tick == 1
    assert [(e.tick, e.seq, e.kind) for e in events] == [(0, 0, "intent_rejected")]
    assert events[0].data == {"actor": "ghost", "intent": "move_to", "reason": "unknown_actor"}


@pytest.mark.req("REQ-SIM-004")
def test_villager_walks_path_and_arrives(registry: Registry) -> None:
    """AC1: movement follows the A* path; entering a tile costs its move_cost in ticks."""
    tilemap = TileMap(4, 1, ["grass", "forest", "grass", "grass"], [0.0] * 4)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    # tick 0: path set, progress 1.0 < forest cost 2, so no move yet
    state, events = engine.step(state, [MoveTo("a", Coord(3, 0))])
    assert [e.kind for e in events] == ["move_started"]
    assert events[0].data == {"actor": "a", "target": [3, 0], "steps": 3}
    assert state.villagers["a"].pos == Coord(0, 0)
    kinds: list[list[str]] = []
    for _ in range(4):
        state, events = engine.step(state, [])
        kinds.append([e.kind for e in events])
    # tick 1: progress 2 enters forest; ticks 2 and 3 enter grass (cost 1); tick 4: idle
    assert kinds == [["moved"], ["moved"], ["moved", "arrived"], []]
    assert state.villagers["a"].pos == Coord(3, 0)
    assert state.villagers["a"].path == []
    assert state.villagers["a"].move_progress == 0.0


@pytest.mark.req("REQ-SIM-004")
def test_unreachable_target_fails_cleanly(registry: Registry) -> None:
    """AC2: no path → a move_failed event, no exception."""
    tilemap = TileMap(3, 1, ["grass", "water", "grass"], [0.0] * 3)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    state, events = Engine(registry).step(state, [MoveTo("a", Coord(2, 0))])
    assert [(e.kind, e.data) for e in events] == [
        ("move_failed", {"actor": "a", "target": [2, 0], "reason": "no_path"})
    ]
    assert state.villagers["a"].path == []


@pytest.mark.req("REQ-SIM-004")
def test_move_to_own_tile_arrives_immediately(registry: Registry) -> None:
    tilemap = TileMap(2, 1, ["grass", "grass"], [0.0] * 2)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(1, 0))])
    state, events = Engine(registry).step(state, [MoveTo("a", Coord(1, 0))])
    assert [(e.kind, e.data) for e in events] == [("arrived", {"actor": "a", "at": [1, 0]})]


@pytest.mark.req("REQ-SIM-004")
def test_path_blocked_after_terrain_change(registry: Registry) -> None:
    # forest (cost 2) at (1, 0) keeps the villager at (0, 0) after tick 0
    tilemap = TileMap(3, 1, ["grass", "forest", "grass"], [0.0] * 3)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    state, _ = engine.step(state, [MoveTo("a", Coord(2, 0))])
    assert state.villagers["a"].pos == Coord(0, 0)
    state.tilemap = TileMap(3, 1, ["grass", "water", "grass"], [0.0] * 3)
    state, events = engine.step(state, [])
    assert [(e.kind, e.data) for e in events] == [
        ("move_failed", {"actor": "a", "target": [2, 0], "reason": "blocked"})
    ]
    assert state.villagers["a"].path == [] and state.villagers["a"].pos == Coord(0, 0)


@pytest.mark.req("REQ-SIM-002")
def test_wait_stops_movement(registry: Registry) -> None:
    tilemap = TileMap(5, 1, ["grass"] * 5, [0.0] * 5)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    state, events = engine.step(state, [MoveTo("a", Coord(4, 0))])
    assert [e.kind for e in events] == ["move_started", "moved"]
    state, events = engine.step(state, [Wait("a")])
    assert [(e.kind, e.data) for e in events] == [("stopped", {"actor": "a", "at": [1, 0]})]
    assert state.villagers["a"].pos == Coord(1, 0)
    state, events = engine.step(state, [Wait("a")])
    assert events == []


@pytest.mark.req("REQ-SIM-002")
def test_duplicate_and_unknown_intents_are_rejected(registry: Registry, small_map: TileMap) -> None:
    @dataclass(frozen=True)
    class Dance(Intent):
        kind = "dance"

    _, events = Engine(registry).step(fresh(small_map), [Wait("a"), Wait("a"), Dance("b")])
    reasons = sorted(e.data["reason"] for e in events if e.kind == "intent_rejected")
    assert reasons == ["duplicate_intent", "unknown_intent"]


@pytest.mark.req("REQ-SIM-002")
def test_register_custom_handler(registry: Registry, small_map: TileMap) -> None:
    @dataclass(frozen=True)
    class Shout(Intent):
        kind = "shout"

    def handle(state: WorldState, intent: Intent, sink: EventSink) -> None:
        sink.emit("shouted", actor=intent.actor)

    engine = Engine(registry)
    engine.register(Shout, handle)
    _, events = engine.step(fresh(small_map), [Shout("a")])
    assert [(e.kind, e.data) for e in events] == [("shouted", {"actor": "a"})]


@pytest.mark.req("REQ-SIM-006")
def test_step_expires_modifiers(registry: Registry, small_map: TileMap) -> None:
    """AC4: time-limited modifiers disappear when their tick passes."""
    state = fresh(small_map)
    keep = Modifier(Target("action"), "work_speed", Op.ADD, 1, "keep")
    temp = Modifier(Target("action"), "work_speed", Op.ADD, 1, "temp", Scope(until_tick=2))
    state.modifiers = (keep, temp)
    engine = Engine(registry)
    state, _ = engine.step(state, [])
    assert state.modifiers == (keep, temp)
    state, _ = engine.step(state, [])
    assert state.modifiers == (keep,)


def test_event_round_trip() -> None:
    sink = EventSink(4)
    first = sink.emit("moved", actor="a", to=[1, 2])
    second = sink.emit("arrived", actor="a", at=[1, 2])
    assert (first.seq, second.seq) == (0, 1)
    assert sink.events == [first, second]
    assert Event.from_dict(first.to_dict()) == first
    assert first.to_dict() == {
        "tick": 4,
        "seq": 0,
        "kind": "moved",
        "data": {"actor": "a", "to": [1, 2]},
    }


def test_intent_sort_key_is_canonical() -> None:
    assert MoveTo("a", Coord(1, 2)).sort_key() == ("a", "move_to", '{"actor":"a","target":[1,2]}')
    assert Wait("b").sort_key() == ("b", "wait", '{"actor":"b"}')


@pytest.mark.req("REQ-SIM-004")
def test_movement_events_and_state_for_several_villagers(registry: Registry) -> None:
    """AC1: every villager advances independently, in id order, with full event data."""
    tilemap = TileMap(6, 3, ["grass"] * 18, [0.0] * 18)
    engine = Engine(registry)
    state = WorldState.new(
        1,
        tilemap,
        [
            Villager("a", "A", Coord(0, 0)),  # idle: must not stop the others
            Villager("b", "B", Coord(0, 1)),  # stops in the middle (forest-free, 3 steps)
            Villager("c", "C", Coord(0, 2)),
        ],
    )
    state, events = engine.step(state, [MoveTo("b", Coord(2, 1)), MoveTo("c", Coord(1, 2))])
    # intent handling order is seeded-shuffled, so compare the two starts by actor
    assert sorted(
        (e.kind, e.data["actor"], e.data["target"], e.data["steps"]) for e in events[:2]
    ) == [
        ("move_started", "b", [2, 1], 2),
        ("move_started", "c", [1, 2], 1),
    ]
    assert [(e.seq, e.kind, e.data) for e in events[2:]] == [
        (2, "moved", {"actor": "b", "to": [1, 1]}),
        (3, "moved", {"actor": "c", "to": [1, 2]}),
        (4, "arrived", {"actor": "c", "at": [1, 2]}),
    ]
    assert state.tick == 1
    state, events = engine.step(state, [])
    assert [(e.tick, e.kind, e.data) for e in events] == [
        (1, "moved", {"actor": "b", "to": [2, 1]}),
        (1, "arrived", {"actor": "b", "at": [2, 1]}),
    ]
    assert state.tick == 2
    assert state.villagers["b"].path == [] and state.villagers["b"].move_progress == 0.0


@pytest.mark.req("REQ-SIM-004")
def test_blocked_path_reports_final_target_and_resets_progress(registry: Registry) -> None:
    """AC2: a blocked step reports the final target; other villagers still move."""
    tilemap = TileMap(5, 2, ["grass", "forest", "grass", "grass", "grass"] * 2, [0.0] * 10)
    engine = Engine(registry)
    state = WorldState.new(
        1,
        tilemap,
        [Villager("a", "A", Coord(0, 0)), Villager("b", "B", Coord(0, 1))],
    )
    state, _ = engine.step(state, [MoveTo("a", Coord(4, 0)), MoveTo("b", Coord(4, 1))])
    assert state.villagers["a"].move_progress == 1.0
    state.tilemap = TileMap(5, 2, ["grass", "water", "grass", "grass", "grass"] * 2, [0.0] * 10)
    state, events = engine.step(state, [])
    assert [(e.kind, e.data) for e in events] == [
        ("move_failed", {"actor": "a", "target": [4, 0], "reason": "blocked"}),
        ("move_failed", {"actor": "b", "target": [4, 1], "reason": "blocked"}),
    ]
    for vid in "ab":
        assert state.villagers[vid].path == []
        assert state.villagers[vid].move_progress == 0.0


@pytest.mark.req("REQ-SIM-002")
def test_wait_mid_move_clears_progress_and_path(registry: Registry) -> None:
    tilemap = TileMap(4, 1, ["grass", "forest", "grass", "grass"], [0.0] * 4)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    state, _ = engine.step(state, [MoveTo("a", Coord(3, 0))])
    assert state.villagers["a"].move_progress == 1.0
    state, events = engine.step(state, [Wait("a")])
    # the stop is processed before this tick's movement: nothing moves afterwards
    assert [e.kind for e in events] == ["stopped"]
    assert state.villagers["a"].path == []
    assert state.villagers["a"].move_progress == 0.0
    assert state.villagers["a"].pos == Coord(0, 0)


@pytest.mark.req("REQ-SIM-004")
def test_new_move_resets_progress_and_failed_or_trivial_moves_clear_path(
    registry: Registry,
) -> None:
    tilemap = TileMap(4, 1, ["grass", "forest", "grass", "water"], [0.0] * 4)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap, [Villager("a", "A", Coord(0, 0))])
    state, _ = engine.step(state, [MoveTo("a", Coord(2, 0))])
    assert state.villagers["a"].move_progress == 1.0
    state, events = engine.step(state, [MoveTo("a", Coord(3, 0))])
    assert [e.kind for e in events] == ["move_failed"]
    assert state.villagers["a"].path == []
    assert state.villagers["a"].move_progress == 0.0
    state, _ = engine.step(state, [MoveTo("a", Coord(2, 0))])
    state, events = engine.step(state, [MoveTo("a", Coord(0, 0))])
    assert [e.kind for e in events] == ["arrived"]
    assert state.villagers["a"].path == []
    assert state.villagers["a"].move_progress == 0.0


def test_cost_field_is_cached_per_tilemap(registry: Registry) -> None:
    tilemap = TileMap(2, 1, ["grass", "grass"], [0.0] * 2)
    engine = Engine(registry)
    state = WorldState.new(1, tilemap)
    first = engine._cost_field(state)
    assert engine._cost_field(state) is first
    state.tilemap = TileMap(2, 1, ["grass", "grass"], [0.0] * 2)
    assert engine._cost_field(state) is not first
