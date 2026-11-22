from collections.abc import Sequence
from pathlib import Path

import pytest

from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo
from pericles.core.mapgen import TileMap
from pericles.core.state import Villager, WorldState
from pericles.experiment.rundir import RunDirectory, RunDirectoryError
from pericles.experiment.runner import IntentSource, resume, run

pytestmark = pytest.mark.req("REQ-EXP-003")


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
        run_dir, Engine(registry), state, source_for(walkable), until_tick=25, snapshot_every=10
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
    source = source_for(walkable)
    clean = RunDirectory.create(tmp_path / "clean", {}, seed=4)
    clean_final = run(clean, Engine(registry), state, source, until_tick=50, snapshot_every=10)

    state2, _ = initial(small_map, registry)
    crashing = RunDirectory.create(tmp_path / "crash", {}, seed=4)

    def exploding(s: WorldState) -> Sequence[Intent]:
        if s.tick == 37:
            raise RuntimeError("power cut")
        return source(s)

    with pytest.raises(RuntimeError, match="power cut"):
        run(crashing, Engine(registry), state2, exploding, until_tick=50, snapshot_every=10)
    assert crashing.event_log.last_tick() == 36
    crashing.close()

    reopened = RunDirectory.open(tmp_path / "crash")
    resumed = resume(reopened)
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
            run_dir, Engine(registry), state, source_for(walkable), until_tick=20, snapshot_every=10
        )
    assert log.last_tick() == 11
    assert run_dir.snapshot_ticks() == [0, 10]
    run_dir.close()


def test_resume_without_snapshot_fails(tmp_path: Path) -> None:
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=1)
    with pytest.raises(RunDirectoryError, match="no snapshot"):
        resume(run_dir)
    run_dir.close()


def test_run_rejects_bad_arguments(tmp_path: Path, registry: Registry, small_map: TileMap) -> None:
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=4)
    with pytest.raises(ValueError, match="snapshot_every"):
        run(run_dir, Engine(registry), state, source_for(walkable), until_tick=5, snapshot_every=0)
    with pytest.raises(ValueError, match="until_tick"):
        run(run_dir, Engine(registry), state, source_for(walkable), until_tick=-1, snapshot_every=5)
    run_dir.close()
