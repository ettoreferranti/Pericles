import json
import os
import shutil
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.scripted import scripted_controller
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo
from pericles.core.mapgen import TileMap
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment import rundir as rundir_module
from pericles.experiment.defaults import default_config
from pericles.experiment.rundir import RunDirectory, RunDirectoryError
from pericles.experiment.runner import IntentSource, SourceAgents, agent_events, resume, run

pytestmark = pytest.mark.req("REQ-EXP-003")


@pytest.fixture(autouse=True)
def close_run_directories(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Close every RunDirectory a test creates or opens, so no sqlite handle leaks."""
    opened: list[RunDirectory] = []
    for name in ("create", "open"):
        original = getattr(RunDirectory, name).__func__

        def tracked(
            cls: type[RunDirectory], /, *args: Any, _o: Any = original, **kw: Any
        ) -> RunDirectory:
            made: RunDirectory = _o(cls, *args, **kw)
            opened.append(made)
            return made

        monkeypatch.setattr(RunDirectory, name, classmethod(tracked))
    yield
    for made in opened:
        made.close()


def initial(small_map: TileMap, registry: Registry) -> tuple[WorldState, list[Coord]]:
    walkable = [
        Coord(x, y)
        for y in range(small_map.height)
        for x in range(small_map.width)
        if registry.terrains[small_map.terrain_at(Coord(x, y))].walkable
    ]
    start = small_map.start()
    villagers = [Villager(f"v{i}", f"V{i}", start) for i in range(4)]
    return WorldState.new(4, small_map, villagers), walkable


def source_for(walkable: list[Coord]) -> IntentSource:
    def source(state: WorldState) -> Sequence[Intent]:
        if state.tick % 7 != 0:
            return []
        return [
            MoveTo(v, walkable[(state.tick * 13 + i * 17) % len(walkable)])
            for i, v in enumerate(sorted(state.villagers))
        ]

    return source


def test_run_writes_events_and_snapshots(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC1/AC2: a run fills the event log tick by tick and snapshots periodically."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    final = run(
        run_dir,
        Engine(registry),
        state,
        SourceAgents(source_for(walkable)),
        until_tick=25,
        snapshot_every=10,
    )
    assert final.tick == 25
    assert run_dir.event_log.last_tick() == 24
    assert run_dir.snapshot_ticks() == [0, 10, 20]
    assert any(e.kind == "moved" for e in run_dir.event_log.events())
    run_dir.close()


def test_resume_after_crash_matches_uninterrupted_run(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC3: a run resumes from its last snapshot after a crash, with identical results."""
    state, walkable = initial(small_map, registry)
    source = SourceAgents(source_for(walkable))
    clean = RunDirectory.create(tmp_path / "clean", {}, seed=4)
    clean_final = run(clean, Engine(registry), state, source, until_tick=50, snapshot_every=10)

    state2, _ = initial(small_map, registry)
    crashing = RunDirectory.create(tmp_path / "crash", {}, seed=4)

    def exploding(s: WorldState) -> Sequence[Intent]:
        if s.tick == 37:
            raise RuntimeError("power cut")
        return source.intents(s)

    with pytest.raises(RuntimeError, match="power cut"):
        run(
            crashing,
            Engine(registry),
            state2,
            SourceAgents(exploding),
            until_tick=50,
            snapshot_every=10,
        )
    assert crashing.event_log.last_tick() == 36
    crashing.close()

    reopened = RunDirectory.open(tmp_path / "crash")
    resumed, _ = resume(reopened)
    assert resumed.tick == 30
    assert reopened.event_log.last_tick() == 29
    final = run(reopened, Engine(registry), resumed, source, until_tick=50, snapshot_every=10)
    assert final.digest() == clean_final.digest()
    assert reopened.event_log.digest() == clean.event_log.digest()
    clean.close()
    reopened.close()


def test_failed_event_write_leaves_no_partial_tick(
    tmp_path: Path, registry: Registry, small_map: TileMap, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC2/AC3: a crash while writing a tick loses at most that tick."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=4)
    log = run_dir.event_log
    original = log.append_tick

    def failing(tick: int, events: Sequence[Event]) -> None:
        if tick == 12:
            raise OSError("disk full")
        original(tick, events)

    monkeypatch.setattr(log, "append_tick", failing)
    with pytest.raises(OSError, match="disk full"):
        run(
            run_dir,
            Engine(registry),
            state,
            SourceAgents(source_for(walkable)),
            until_tick=20,
            snapshot_every=10,
        )
    assert log.last_tick() == 11
    assert run_dir.snapshot_ticks() == [0, 10]
    run_dir.close()


def test_resume_without_snapshot_fails(tmp_path: Path) -> None:
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=1)
    with pytest.raises(RunDirectoryError, match="no usable snapshot"):
        resume(run_dir)
    run_dir.close()


def test_run_rejects_bad_arguments(tmp_path: Path, registry: Registry, small_map: TileMap) -> None:
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=4)
    with pytest.raises(ValueError, match="snapshot_every"):
        run(
            run_dir,
            Engine(registry),
            state,
            SourceAgents(source_for(walkable)),
            until_tick=5,
            snapshot_every=0,
        )
    with pytest.raises(ValueError, match="until_tick"):
        run(
            run_dir,
            Engine(registry),
            state,
            SourceAgents(source_for(walkable)),
            until_tick=-1,
            snapshot_every=5,
        )
    run_dir.close()


def village(registry: Registry, small_map: TileMap) -> WorldState:
    start = small_map.start()
    people = [Villager(f"v{i}", f"V{i}", start, sex=("female", "male")[i % 2]) for i in range(4)]
    bushes = [
        Node(f"n{i}", "berry_bush", Coord(start.x + i - 2, start.y + 2), 20) for i in range(4)
    ]
    return WorldState.new(4, small_map, people, bushes)


def test_resume_matches_a_run_that_never_stopped(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC3: crash and resume give the same log, world and agent memory as an uninterrupted run."""
    engine = Engine(registry, default_config())
    straight_agents = scripted_controller(engine.context, AgentConfig())
    straight = RunDirectory.create(tmp_path / "a", {"seed": 4}, seed=4)
    straight_final = run(straight, engine, village(registry, small_map), straight_agents, 600, 50)
    crashed = RunDirectory.create(tmp_path / "b", {"seed": 4}, seed=4)
    run(
        crashed,
        engine,
        village(registry, small_map),
        scripted_controller(engine.context, AgentConfig()),
        60,
        50,
    )
    crashed.close()
    digests = []
    for load in (True, False):
        copy = tmp_path / f"copy-{load}"
        shutil.copytree(tmp_path / "b", copy)
        reopened = RunDirectory.open(copy)
        state, agents = resume(reopened)
        assert state.tick == 50
        controller = scripted_controller(Engine(registry, default_config()).context, AgentConfig())
        if load:
            controller.load(agents)
        final = run(reopened, Engine(registry, default_config()), state, controller, 600, 50)
        if load:
            assert reopened.event_log.digest() == straight.event_log.digest()
            assert final.digest() == straight_final.digest()
            assert controller.to_dict() == straight_agents.to_dict()
        digests.append(reopened.event_log.digest())
        reopened.close()
    assert digests[1] != straight.event_log.digest()  # without the memory the run diverges
    straight.close()


def test_resume_skips_corrupt_and_mismatched_snapshots(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC3: a damaged newest snapshot is skipped and reported, not fatal."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, SourceAgents(source_for(walkable)), 30, 10)
    snaps = run_dir.path / "snapshots"
    (snaps / "tick-0000000030.json").write_text('{"world": {"tick"', encoding="utf-8")
    os.replace(snaps / "tick-0000000010.json", snaps / "tick-0000000020.json")
    resumed, _ = resume(run_dir)
    assert resumed.tick == 0
    assert {p.name for p in run_dir.skipped} == {"tick-0000000030.json", "tick-0000000020.json"}
    assert run_dir.event_log.last_tick() is None


def test_resume_never_starts_ahead_of_the_log(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC2/AC3: a snapshot newer than the logged ticks is not used."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, SourceAgents(source_for(walkable)), 30, 10)
    run_dir.event_log.truncate_after(14)
    resumed, _ = resume(run_dir)
    assert resumed.tick == 10
    assert run_dir.event_log.last_tick() == 9


def test_no_usable_snapshot_is_a_run_directory_error(tmp_path: Path) -> None:
    """AC3: when nothing can be resumed, say so."""
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    with pytest.raises(RunDirectoryError, match="no usable snapshot"):
        resume(run_dir)
    (run_dir.path / "snapshots" / "tick-0000000000.json").write_text("[]", encoding="utf-8")
    with pytest.raises(RunDirectoryError, match="no usable snapshot"):
        resume(run_dir)


def test_snapshots_hold_agent_memory_and_are_fsynced(
    tmp_path: Path,
    registry: Registry,
    small_map: TileMap,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC1/AC3: a snapshot carries the controller memory and reaches the disk."""
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    state, _ = initial(small_map, registry)
    calls: list[int] = []
    real = os.fsync

    def counting(fd: int) -> None:
        calls.append(fd)
        real(fd)

    monkeypatch.setattr(os, "fsync", counting)
    run_dir.save_snapshot(state, {"memory": {"v0": "x"}})
    assert len(calls) >= 2  # the file, then its directory
    snapshot = run_dir.latest_snapshot()
    assert snapshot is not None and snapshot.agents == {"memory": {"v0": "x"}}
    assert snapshot.world == state.to_dict()


def test_a_run_stops_when_the_village_dies_out(
    tmp_path: Path, life: Registry, small_map: TileMap
) -> None:
    """AC1: an extinct village ends the run early, snapshotted at the end."""
    state = WorldState.new(4, small_map, [Villager("v0", "V", small_map.start())])
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    final = run(run_dir, Engine(life), state, SourceAgents(lambda s: []), 10_000, 1000)
    assert not final.villagers
    assert final.tick < 10_000
    assert run_dir.snapshot_ticks()[-1] == final.tick


def test_resume_skips_a_snapshot_whose_world_cannot_be_rebuilt(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC3: a well-formed but incomplete world is skipped, never a raw KeyError."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, SourceAgents(source_for(walkable)), 20, 10)
    (run_dir.path / "snapshots" / "tick-0000000020.json").write_text(
        '{"world": {"tick": 20}, "agents": {}}', encoding="utf-8"
    )
    resumed, _ = resume(run_dir)
    assert resumed.tick == 10
    assert [p.name for p in run_dir.skipped] == ["tick-0000000020.json"]


class MemoryAgents(SourceAgents):
    """Stateless agents that expose a recognisable memory blob."""

    def to_dict(self) -> dict[str, Any]:
        return {"memory": "kept"}


def test_run_snapshots_carry_the_agent_memory(
    tmp_path: Path, registry: Registry, life: Registry, small_map: TileMap
) -> None:
    """AC1/AC3: periodic and end-of-run snapshots both store the agents' memory."""
    state, _ = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, MemoryAgents(lambda s: []), 10, 5)
    _, agents = resume(run_dir)
    assert agents == {"memory": "kept"}
    first = next(s for s in run_dir.snapshots() if s.tick == 0)
    assert first.agents == {"memory": "kept"}

    lone = WorldState.new(4, small_map, [Villager("v0", "V", small_map.start())])
    dying = RunDirectory.create(tmp_path / "dying", {"seed": 4}, seed=4)
    final = run(dying, Engine(life), lone, MemoryAgents(lambda s: []), 10_000, 1000)
    last = dying.latest_snapshot()
    assert last is not None and last.tick == final.tick
    assert last.agents == {"memory": "kept"}


def test_resume_boundary_with_the_log(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC2/AC3: a snapshot exactly at the end of the log is used; one tick beyond is skipped."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, SourceAgents(source_for(walkable)), 30, 10)
    run_dir.event_log.truncate_after(19)
    resumed, _ = resume(run_dir)
    assert resumed.tick == 20
    assert [p.name for p in run_dir.skipped] == ["tick-0000000030.json"]

    empty = RunDirectory.create(tmp_path / "empty", {"seed": 4}, seed=4)
    other, _ = initial(small_map, registry)
    other.tick = 1
    empty.save_snapshot(other)
    with pytest.raises(RunDirectoryError, match="no usable snapshot"):
        resume(empty)


def test_resume_skips_a_snapshot_one_tick_ahead_of_the_log(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC2/AC3: with ticks 0-18 logged, the snapshot at 20 (needing 0-19) is not used."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, SourceAgents(source_for(walkable)), 20, 10)
    run_dir.event_log.truncate_after(18)
    resumed, _ = resume(run_dir)
    assert resumed.tick == 10
    assert [p.name for p in run_dir.skipped] == ["tick-0000000020.json"]
    run_dir.close()


def test_stray_snapshot_names_are_skipped_not_fatal(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC3: files that are not exactly tick-%010d.json are reported and ignored."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 4}, seed=4)
    run(run_dir, Engine(registry), state, SourceAgents(source_for(walkable)), 10, 10)
    snaps = run_dir.path / "snapshots"
    (snaps / "tick-old.json").write_text("{}", encoding="utf-8")
    (snaps / "tick-10.json").write_text("{}", encoding="utf-8")
    assert run_dir.snapshot_ticks() == [0, 10]
    resumed, _ = resume(run_dir)
    assert resumed.tick == 10
    assert {p.name for p in run_dir.skipped} == {"tick-old.json", "tick-10.json"}
    run_dir.close()


def test_the_final_snapshot_of_an_extinct_run_replaces_a_corrupt_file(
    tmp_path: Path, life: Registry, small_map: TileMap
) -> None:
    """AC1/AC3: the end-of-run snapshot is always rewritten."""
    state = WorldState.new(4, small_map, [Villager("v0", "V", small_map.start())])
    first = RunDirectory.create(tmp_path / "first", {"seed": 4}, seed=4)
    final = run(first, Engine(life), state, SourceAgents(lambda s: []), 10_000, 1000)
    first.close()
    again = RunDirectory.create(tmp_path / "again", {"seed": 4}, seed=4)
    (again.path / "snapshots" / f"tick-{final.tick:010d}.json").write_text("{", encoding="utf-8")
    state = WorldState.new(4, small_map, [Villager("v0", "V", small_map.start())])
    run(again, Engine(life), state, SourceAgents(lambda s: []), 10_000, 1000)
    snapshot = again.latest_snapshot()
    assert snapshot is not None and snapshot.tick == final.tick
    again.close()


def test_create_fsyncs_its_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3: snapshots/ and llm_cache/ entries are durable once the run directory exists."""
    synced: list[str] = []
    real = rundir_module._fsync_dir

    def spy(path: Path) -> None:
        synced.append(path.name)
        real(path)

    monkeypatch.setattr(rundir_module, "_fsync_dir", spy)
    RunDirectory.create(tmp_path / "run", {}, seed=1).close()
    assert "snapshots" in synced and "llm_cache" in synced


def test_resume_skips_a_snapshot_whose_agents_blob_will_not_load(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC3: a malformed agents blob falls back to the previous snapshot."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=4)
    engine = Engine(registry, default_config())
    run(run_dir, engine, state, SourceAgents(source_for(walkable)), 20, 10)
    bad = run_dir.snapshot_path(20)
    payload = json.loads(bad.read_text(encoding="utf-8"))
    payload["agents"] = {"memory": {"v0": "not a memory"}}
    bad.write_text(json.dumps(payload), encoding="utf-8")

    def load(agents: dict[str, Any]) -> None:
        for value in agents.get("memory", {}).values():
            if not isinstance(value, dict):
                raise TypeError("memory entries are mappings")

    restored, _ = resume(run_dir, load)
    assert restored.tick == 10
    assert run_dir.skipped == [bad]


class NotingAgents(SourceAgents):
    """Agents that report one plan_made note per tick, as a planner would."""

    def __init__(self, source: IntentSource) -> None:
        super().__init__(source)
        self.tick = 0

    def intents(self, state: WorldState) -> Sequence[Intent]:
        self.tick = state.tick
        return super().intents(state)

    def events(self) -> list[tuple[str, dict[str, Any]]]:
        return [("plan_made", {"actor": "a", "tick": self.tick})]


@pytest.mark.req("REQ-NFR-001")
def test_agent_events_follow_the_engine_events_of_their_tick(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC1: agent decisions are part of the logged, digested history."""
    state, walkable = initial(small_map, registry)
    source = source_for(walkable)
    base = RunDirectory.create(tmp_path / "base", {}, seed=4)
    run(base, Engine(registry), state, SourceAgents(source), until_tick=3, snapshot_every=10)
    engine_events = list(base.event_log.events())
    assert engine_events  # the comparison below is not vacuous

    noted = RunDirectory.create(tmp_path / "noted", {}, seed=4)
    state, _ = initial(small_map, registry)  # the engine mutates its input world
    run(noted, Engine(registry), state, NotingAgents(source), until_tick=3, snapshot_every=10)
    logged = list(noted.event_log.events())
    for tick in range(3):
        mine = [e for e in logged if e.tick == tick]
        engine = [e for e in engine_events if e.tick == tick]
        assert [(e.kind, e.data) for e in mine[:-1]] == [(e.kind, e.data) for e in engine]
        assert (mine[-1].kind, mine[-1].data) == ("plan_made", {"actor": "a", "tick": tick})
        assert [e.seq for e in mine] == list(range(len(engine) + 1))
    assert noted.event_log.digest() != base.event_log.digest()
    base.close()
    noted.close()


@pytest.mark.req("REQ-NFR-001")
def test_agent_events_numbers_notes_on_from_the_engine_events() -> None:
    """AC1: notes are events of the tick, numbered after the engine's."""
    made = agent_events(7, 3, [("plan_made", {"actor": "a"}), ("plan_failed", {"actor": "b"})])
    assert made == [
        Event(7, 3, "plan_made", {"actor": "a"}),
        Event(7, 4, "plan_failed", {"actor": "b"}),
    ]
    assert agent_events(7, 3, []) == []
