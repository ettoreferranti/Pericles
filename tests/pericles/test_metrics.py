from pathlib import Path

import pytest

from pericles.analysis.metrics import Row, daily_survival
from pericles.core.events import Event
from pericles.experiment.rundir import RunDirectory

pytestmark = pytest.mark.req("REQ-EXP-003")
CONFIG = {
    "engine": {"calendar": {"day_minutes": 100, "tick_minutes": 10}, "adult_age_days": 50},
    "population": [
        {"id": "a", "age_days": 60},
        {"id": "b", "age_days": 70},
        {"id": "k", "age_days": 49},
    ],
}


def by_day(rows: list[Row]) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    for row in rows:
        out.setdefault(row.day, {})[row.metric] = row.value
    return out


def test_daily_survival_counts_population_births_deaths_and_food() -> None:
    """AC1: daily metrics derive from the config and the event log alone."""
    events = [
        Event(3, 0, "ate", {"actor": "a", "nutrition": 30.0}),
        Event(5, 0, "born", {"child": "v9", "mother": "a"}),
        Event(12, 0, "came_of_age", {"villager": "k"}),
        Event(14, 0, "died", {"villager": "b", "cause": "cold"}),
        Event(14, 1, "died", {"villager": "v9", "cause": "starvation"}),
        Event(14, 2, "ate", {"actor": "a", "nutrition": 15.0}),
    ]
    days = by_day(daily_survival(CONFIG, events, last_tick=35))
    assert sorted(days) == [0, 1, 2, 3]
    assert days[0] == {
        "population": 4,
        "adults": 2,
        "children": 2,
        "births": 1,
        "deaths": 0,
        "food_eaten": 30.0,
    }
    assert days[1]["population"] == 2 and days[1]["adults"] == 2 and days[1]["children"] == 0
    assert days[1]["deaths"] == 2 and days[1]["deaths.cold"] == 1
    assert days[1]["deaths.starvation"] == 1
    assert days[1]["food_eaten"] == 15.0
    assert days[3] == {
        "population": 2,
        "adults": 2,
        "children": 0,
        "births": 0,
        "deaths": 0,
        "food_eaten": 0.0,
    }


def test_an_empty_log_reports_the_starting_village() -> None:
    """AC1: day 0 exists even before anything happens; no log, no rows."""
    assert by_day(daily_survival(CONFIG, [], last_tick=0))[0]["population"] == 3
    assert daily_survival(CONFIG, [], last_tick=None) == []


def test_metrics_round_trip_through_parquet(tmp_path: Path) -> None:
    """AC1: the run directory holds metrics.parquet."""
    run_dir = RunDirectory.create(tmp_path / "run", {"seed": 1}, seed=1)
    rows = [Row(0, "population", 3.0), Row(0, "deaths.cold", 1.0)]
    path = run_dir.write_metrics(rows)
    assert path.name == "metrics.parquet"
    assert run_dir.read_metrics() == rows
