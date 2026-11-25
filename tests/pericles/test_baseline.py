import dataclasses
from pathlib import Path

import pytest

from pericles.experiment.config import load_experiment
from pericles.experiment.defaults import default_config
from pericles.experiment.launch import advance, start
from pericles.experiment.rundir import RunDirectory

BASELINE = Path(__file__).parents[2] / "experiments" / "baseline.yaml"
WINTER_OVER = default_config().calendar.days_per_year + 1  # the first day after the first winter


def kinds(session_dir: Path) -> dict[str, list[dict[str, object]]]:
    run_dir = RunDirectory.open(session_dir)
    found: dict[str, list[dict[str, object]]] = {}
    for event in run_dir.event_log.events():
        found.setdefault(event.kind, []).append(dict(event.data))
    run_dir.close()
    return found


@pytest.mark.long
@pytest.mark.req("REQ-AGT-008")
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_the_baseline_village_survives_its_first_winter(tmp_path: Path, seed: int) -> None:
    """AC1/AC2: the all-scripted baseline keeps everyone alive through winter."""
    experiment = load_experiment(BASELINE)
    experiment = dataclasses.replace(
        experiment, seed=seed, resolved={**experiment.resolved, "seed": seed}
    )
    session = start(experiment, tmp_path / "run")
    state = advance(session, WINTER_OVER)
    session.run_dir.close()
    events = kinds(tmp_path / "run")
    causes = [d["cause"] for d in events.get("died", [])]
    assert "starvation" not in causes and "cold" not in causes, causes
    assert any(b.complete for b in state.buildings.values())
    assert events.get("couple_formed")
    assert len(state.villagers) >= len(experiment.population)


@pytest.mark.long
@pytest.mark.req("REQ-AGT-008")
def test_the_baseline_village_grows(tmp_path: Path) -> None:
    """AC2: the baseline reproduces: children are born within the configured run."""
    experiment = load_experiment(BASELINE)
    session = start(experiment, tmp_path / "run")
    advance(session)
    session.run_dir.close()
    assert kinds(tmp_path / "run").get("born")
