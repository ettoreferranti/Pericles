import json
from pathlib import Path

import pytest
import yaml

import pericles
from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap
from pericles.core.state import Villager, WorldState
from pericles.experiment.rundir import RunDirectory, RunDirectoryError

pytestmark = pytest.mark.req("REQ-EXP-003")

CONFIG = {"seed": 9, "map": {"width": 24}, "name": "test"}


def test_create_writes_layout(tmp_path: Path) -> None:
    """AC1: config snapshot, events.sqlite, snapshots/, llm_cache/ and meta.json."""
    run = RunDirectory.create(tmp_path / "run1", CONFIG, seed=9)
    root = tmp_path / "run1"
    assert yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) == CONFIG
    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    assert meta["schema_version"] == RunDirectory.SCHEMA_VERSION == 3  # agent memory in snapshots
    assert meta["seed"] == 9
    assert meta["pericles_version"] == pericles.__version__
    assert "created_utc" in meta and "python" in meta
    assert (root / "events.sqlite").exists()
    assert (root / "snapshots").is_dir() and (root / "llm_cache").is_dir()
    assert run.config == CONFIG and run.meta == meta
    run.close()


def test_create_into_empty_existing_directory(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    RunDirectory.create(tmp_path / "run", CONFIG, seed=1).close()


def test_refuses_to_reuse_a_non_empty_directory(tmp_path: Path) -> None:
    RunDirectory.create(tmp_path / "run", CONFIG, seed=1).close()
    with pytest.raises(RunDirectoryError, match="not empty"):
        RunDirectory.create(tmp_path / "run", CONFIG, seed=1)


def test_open_existing_and_validate(tmp_path: Path) -> None:
    RunDirectory.create(tmp_path / "run", CONFIG, seed=1).close()
    run = RunDirectory.open(tmp_path / "run")
    assert run.config == CONFIG
    run.close()
    with pytest.raises(RunDirectoryError, match="not a run directory"):
        RunDirectory.open(tmp_path)
    meta_path = tmp_path / "run" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["schema_version"] = 999
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    with pytest.raises(RunDirectoryError, match="schema version 999"):
        RunDirectory.open(tmp_path / "run")


def make_state(tick: int) -> WorldState:
    state = WorldState.new(
        3, TileMap(2, 1, ["grass", "grass"], [0.0, 0.5]), [Villager("a", "A", Coord(0, 0))]
    )
    state.tick = tick
    return state


def test_snapshots_save_and_latest(tmp_path: Path) -> None:
    run = RunDirectory.create(tmp_path / "run", CONFIG, seed=3)
    assert run.latest_snapshot() is None
    first = run.save_snapshot(make_state(0))
    run.save_snapshot(make_state(20))
    run.save_snapshot(make_state(10))
    assert first.name == "tick-0000000000.json"
    assert run.snapshot_ticks() == [0, 10, 20]
    latest = run.latest_snapshot()
    assert latest is not None and latest.tick == 20
    assert WorldState.from_dict(latest.world).digest() == make_state(20).digest()
    assert not list((tmp_path / "run" / "snapshots").glob("*.tmp"))
    run.close()


def test_event_log_is_shared(tmp_path: Path) -> None:
    run = RunDirectory.create(tmp_path / "run", CONFIG, seed=3)
    assert run.event_log is run.event_log
    run.event_log.append_tick(0, [])
    run.close()
    reopened = RunDirectory.open(tmp_path / "run")
    assert reopened.event_log.last_tick() == 0
    reopened.close()


def test_failed_create_never_overwrites_existing_run(tmp_path: Path) -> None:
    """AC1: creating over an existing run fails and leaves its files and events intact."""
    run = RunDirectory.create(tmp_path / "run", CONFIG, seed=1)
    run.event_log.append_tick(0, [])
    run.close()
    before = (tmp_path / "run" / "meta.json").read_text(encoding="utf-8")
    with pytest.raises(RunDirectoryError):
        RunDirectory.create(tmp_path / "run", {"other": 1}, seed=2)
    assert (tmp_path / "run" / "meta.json").read_text(encoding="utf-8") == before
    reopened = RunDirectory.open(tmp_path / "run")
    assert reopened.config == CONFIG and reopened.event_log.last_tick() == 0
    reopened.close()


def test_open_rejects_an_unreadable_meta(tmp_path: Path) -> None:
    """AC3: a damaged meta.json is a RunDirectoryError, not a JSONDecodeError."""
    RunDirectory.create(tmp_path / "run", CONFIG, seed=3).close()
    (tmp_path / "run" / "meta.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(RunDirectoryError, match="unreadable"):
        RunDirectory.open(tmp_path / "run")
    (tmp_path / "run" / "meta.json").write_text("[]", encoding="utf-8")
    with pytest.raises(RunDirectoryError, match="unreadable"):
        RunDirectory.open(tmp_path / "run")
