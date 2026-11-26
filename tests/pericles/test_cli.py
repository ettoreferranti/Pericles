import copy
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from pericles.experiment.cli import main
from pericles.experiment.rundir import RunDirectory
from pericles.llm.gateway import BackendUnavailable

pytestmark = pytest.mark.req("REQ-EXP-003")
TINY: dict[str, Any] = {
    "seed": 5,
    "map": {
        "width": 24,
        "height": 24,
        "bands": [
            {"terrain": "grass", "share": 0.6},
            {"terrain": "forest", "share": 0.3},
            {"terrain": "rock", "share": 0.1},
        ],
        "start_terrain": "grass",
        "start_radius": 4,
        "feature_size": 8,
    },
    "population": [
        {"id": "a", "name": "A", "sex": "female", "age_days": 200},
        {"id": "b", "name": "B", "sex": "male", "age_days": 200},
    ],
    "run": {"days": 2, "snapshot_every_days": 1},
    "engine": {
        "calendar": {
            "tick_minutes": 10,
            "day_minutes": 1440,
            "sunrise_minute": 360,
            "sunset_minute": 1200,
            "seasons": [{"name": "year", "days": 40}],
        }
    },
}


def write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "exp.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_run_writes_a_complete_run_directory(tmp_path: Path) -> None:
    """AC1: config snapshot, events, snapshots, llm_cache, metrics and meta."""
    out = tmp_path / "run"
    assert main(["run", str(write(tmp_path, TINY)), "--out", str(out), "--days", "1"]) == 0
    for name in (
        "config.yaml",
        "events.sqlite",
        "snapshots",
        "llm_cache",
        "metrics.parquet",
        "meta.json",
    ):
        assert (out / name).exists(), name
    run_dir = RunDirectory.open(out)
    assert run_dir.config["engine"]["calendar"]["tick_minutes"] == 10
    assert {r.day for r in run_dir.read_metrics()} == {0, 1}
    run_dir.close()


def test_resume_continues_to_the_requested_day(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC3: a run directory can be continued from its last snapshot."""
    out = tmp_path / "run"
    main(["run", str(write(tmp_path, TINY)), "--out", str(out), "--days", "1"])
    assert main(["resume", str(out)]) == 0
    run_dir = RunDirectory.open(out)
    assert run_dir.event_log.last_tick() == 2 * 144 - 1
    assert max(r.day for r in run_dir.read_metrics()) == 2
    assert "Day 2" in capsys.readouterr().out
    run_dir.close()


def test_errors_exit_2_with_the_field_named(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC1: bad experiments and missing run directories are reported, not raised."""
    bad = copy.deepcopy(TINY)
    bad["population"][0]["traits"] = ["lazy"]
    assert main(["run", str(write(tmp_path, bad)), "--out", str(tmp_path / "x")]) == 2
    assert "population[0].traits[0]: unknown trait 'lazy'" in capsys.readouterr().err
    assert main(["resume", str(tmp_path / "nowhere")]) == 2
    assert "not a run directory" in capsys.readouterr().err


def test_an_extinct_village_is_reported(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """AC1: a run whose population dies out stops and says when."""
    doomed = copy.deepcopy(TINY)
    doomed["engine"]["max_health"] = 0.001
    doomed["population"] = [{"id": "a", "name": "A", "age_days": 200}]
    never = {"eat": 100.0, "sleep": 100.0, "shelter": 100.0}
    doomed["agents"] = {"act_at": never, "urgent_at": never, "warm_until": 10.0}
    doomed["run"]["days"] = 30
    assert main(["run", str(write(tmp_path, doomed)), "--out", str(tmp_path / "run")]) == 0
    run_dir = RunDirectory.open(tmp_path / "run")
    deaths = [e.tick for e in run_dir.event_log.events() if e.kind == "died"]
    last = run_dir.event_log.last_tick()
    run_dir.close()
    assert len(deaths) == 1 and last == deaths[0]  # stopped on the tick the last one died
    per_day = 144
    assert last < doomed["run"]["days"] * per_day - 1  # early
    assert f"The village died out on day {deaths[0] // per_day}." in capsys.readouterr().out


def test_a_failed_resume_closes_the_run_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC3: resuming with no usable snapshot is reported and leaves no open event log."""
    out = tmp_path / "run"
    main(["run", str(write(tmp_path, TINY)), "--out", str(out), "--days", "1"])
    for snapshot in (out / "snapshots").iterdir():
        snapshot.unlink()
    closed: list[Path] = []
    original = RunDirectory.close

    def close(self: RunDirectory) -> None:
        closed.append(self.path)
        original(self)

    monkeypatch.setattr(RunDirectory, "close", close)
    assert main(["resume", str(out)]) == 2
    assert "no usable snapshot" in capsys.readouterr().err
    assert closed == [out]


@pytest.mark.req("REQ-LLM-002")
def test_a_missing_model_fails_fast_and_leaves_no_run_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC1: the model check runs before the run directory is created."""
    data = copy.deepcopy(TINY)
    data["llm"] = {
        "backends": {"local": {"kind": "ollama", "url": "http://127.0.0.1:9"}},
        "models": {"q": {"backend": "local", "name": "qwen3"}},
        "assign": {"q": 1.0},
    }
    path = write(tmp_path, data)
    assert main(["run", str(path), "--out", str(tmp_path / "out"), "--days", "1"]) == 2
    assert "cannot reach ollama at http://127.0.0.1:9" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.req("REQ-LLM-009")
def test_backend_unavailable_exits_3_with_resume_advice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: a run stopped by the backend says how to continue."""
    import pericles.experiment.cli as cli

    def stopped(session: object, days: int | None = None) -> object:
        raise BackendUnavailable("ollama at http://x: 5 failures in a row; last: down")

    monkeypatch.setattr(cli, "advance", stopped)
    out = tmp_path / "out"
    assert (
        main(["run", str(write(tmp_path, TINY)), "--out", str(out), "--days", "1"])
        == cli.EXIT_BACKEND
        == 3
    )
    err = capsys.readouterr().err
    assert "5 failures in a row" in err
    assert f"pericles resume {out}" in err


def test_meta_records_the_llm_modes(tmp_path: Path) -> None:
    """meta.json says how the LLM was run, and that wait mode is reproducible."""
    assert (
        main(["run", str(write(tmp_path, TINY)), "--out", str(tmp_path / "out"), "--days", "1"])
        == 0
    )
    meta = json.loads((tmp_path / "out" / "meta.json").read_text(encoding="utf-8"))
    assert (meta["llm_mode"], meta["cache_mode"], meta["reproducible"]) == ("wait", "record", True)
