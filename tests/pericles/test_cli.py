import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from pericles.experiment.cli import main
from pericles.experiment.rundir import RunDirectory

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
    assert "died out on day" in capsys.readouterr().out
