from pathlib import Path

import pytest
import yaml

from pericles.experiment.config import experiment_from_mapping, load_experiment
from pericles.experiment.launch import advance, start
from pericles_tools.bench import perf_experiment

TINY_PIN = """
seed: 7
map:
  width: 24
  height: 24
  bands:
    - {terrain: grass, share: 0.6}
    - {terrain: forest, share: 0.3}
    - {terrain: rock, share: 0.1}
  start_terrain: grass
  start_radius: 4
  feature_size: 8
population:
  - {id: a, name: A, sex: female, age_days: 200, inventory: {berries: 4}}
  - {id: b, name: B, sex: male, age_days: 200, inventory: {berries: 4}}
  - {id: c, name: C, sex: female, age_days: 200, inventory: {berries: 4}}
  - {id: d, name: D, sex: male, age_days: 200, inventory: {berries: 4}}
run: {days: 2, snapshot_every_days: 1}
"""
PINNED = "02408d8b4b95a8c29f692879e26fe416a100304012f777da23d89fe52ebf77f0"


@pytest.mark.req("REQ-NFR-003")
def test_optimisations_do_not_change_a_scripted_run(tmp_path: Path) -> None:
    """AC1: speed work must leave a pinned scripted run's event log byte-for-byte equal."""
    session = start(experiment_from_mapping(yaml.safe_load(TINY_PIN), tmp_path), tmp_path / "run")
    advance(session, 2)
    assert session.run_dir.event_log.digest() == PINNED
    session.run_dir.close()


# A crowded village: building, couples and conception within three days.
CROWDED_PIN = "88526a93c0bf5ed9b17e5c8764d5802bff1e4e7e6a1474671c9071d1c5e48334"
# The baseline village through its first winter: births, seasons, stores.
BASELINE_PIN = "e3415e109b28f25a8e444d421630848ae890d9c2fd892a3f6a6cfc56cd709e1d"
BASELINE = Path(__file__).parents[2] / "experiments" / "baseline.yaml"


@pytest.mark.req("REQ-NFR-003")
def test_optimisations_do_not_change_a_crowded_scripted_run(tmp_path: Path) -> None:
    """AC1: speed work must leave a 30-villager run's event log byte-for-byte equal."""
    session = start(perf_experiment(villagers=30, size=48), tmp_path / "run")
    advance(session, 3)
    assert session.run_dir.event_log.digest() == CROWDED_PIN
    session.run_dir.close()


@pytest.mark.long
@pytest.mark.req("REQ-NFR-003")
def test_optimisations_do_not_change_the_baseline_winter(tmp_path: Path) -> None:
    """AC1: speed work must leave the baseline's first 41 days byte-for-byte equal."""
    session = start(load_experiment(BASELINE), tmp_path / "run")
    advance(session, 41)
    assert session.run_dir.event_log.digest() == BASELINE_PIN
    session.run_dir.close()
