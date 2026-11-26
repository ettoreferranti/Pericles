import copy
import socket
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from pydantic import BaseModel, ConfigDict

from pericles.core.events import Event
from pericles.core.intents import Intent
from pericles.core.state import WorldState
from pericles.experiment.cli import main
from pericles.experiment.config import load_experiment
from pericles.experiment.launch import advance, reopen, start
from pericles.experiment.rundir import RunDirectory
from pericles.llm.backend import LLMSetupError
from pericles.llm.cache import CacheMiss, ResponseCache
from pericles.llm.calls import CallRecord
from pericles.llm.gateway import BackendUnavailable, Gateway
from pericles.llm.types import Message, Request

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
    "run": {"days": 1, "snapshot_every_days": 1},
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
GOOD = [{"replies": ['{"pick": 4}']}]
DOWN_AFTER_TWO = [{"replies": ['{"pick": 1}', '{"pick": 2}', {"error": "down"}]}]


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pick: int


class Asker:
    """Stand-in for a mind: from tick `first` on, every 7 ticks each villager asks the gateway."""

    def __init__(self, gateway: Gateway, first: int = 0) -> None:
        self.gateway = gateway
        self.first = first

    def intents(self, state: WorldState) -> Sequence[Intent]:
        if state.tick % 7 == 0 and state.tick >= self.first:
            self.gateway.complete_all(
                [
                    Request("probe", v, state.tick, "m", (Message("user", v),), state.tick, Probe)
                    for v in sorted(state.villagers)
                ]
            )
        return []

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {}


def experiment_file(tmp_path: Path, replies: list[Any], **llm: Any) -> Path:
    (tmp_path / "replies.yaml").write_text(yaml.safe_dump(replies), encoding="utf-8")
    data = copy.deepcopy(TINY)
    data["llm"] = {
        "backoff_base_s": 0.001,
        "backoff_max_s": 0.001,
        "max_backend_failures": 2,
        "backends": {"f": {"kind": "fake", "replies": "replies.yaml"}},
        "models": {"m": {"backend": "f", "name": "fake-m"}},
        "assign": {"m": 1.0},
        **llm,
    }
    path = tmp_path / "exp.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def unused_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def calls_of(session_gateway: Gateway) -> list[CallRecord]:
    assert session_gateway.calls is not None
    return list(session_gateway.calls.records())


@pytest.mark.req("REQ-LLM-009")
def test_a_backend_that_stays_down_stops_advance_writes_metrics_and_resumes(
    tmp_path: Path,
) -> None:
    """AC1: advance stops at a tick boundary with metrics written, and reopen continues."""
    out = tmp_path / "out"
    session = start(load_experiment(experiment_file(tmp_path, DOWN_AFTER_TWO)), out)
    session.controller = cast(Any, Asker(session.gateway))
    with pytest.raises(BackendUnavailable, match="2 failures in a row"):
        advance(session)
    assert session.run_dir.event_log.last_tick() == 6
    assert {r.day for r in session.run_dir.read_metrics()} == {0}
    session.close()

    (tmp_path / "replies.yaml").write_text(yaml.safe_dump(GOOD), encoding="utf-8")
    again = reopen(out)
    again.controller = cast(Any, Asker(again.gateway))
    advance(again)
    assert again.run_dir.event_log.last_tick() == 143
    rows = calls_of(again.gateway)
    assert not any((r.error or "").startswith("backend:") for r in rows)
    assert Counter(r.tick for r in rows) == {t: 2 for t in range(0, 144, 7)}
    assert {r.day for r in again.run_dir.read_metrics()} == {0, 1}
    again.close()


@pytest.mark.req("REQ-LLM-005")
def test_a_cache_miss_also_writes_the_metrics_before_it_propagates(tmp_path: Path) -> None:
    """AC1: a replay miss mid-run keeps the run resumable and its metrics current."""
    empty = tmp_path / "empty.sqlite"
    ResponseCache(empty, "record").close()
    path = experiment_file(tmp_path, GOOD, cache="replay", cache_from="empty.sqlite")
    session = start(load_experiment(path), tmp_path / "out")
    session.controller = cast(Any, Asker(session.gateway, first=7))
    with pytest.raises(CacheMiss):
        advance(session)
    assert session.run_dir.event_log.last_tick() == 6
    assert {r.day for r in session.run_dir.read_metrics()} == {0}
    session.close()


@pytest.mark.req("REQ-LLM-009")
def test_reopen_drops_call_rows_from_ticks_that_will_run_again(tmp_path: Path) -> None:
    """AC1: rows at or after the resume tick are removed; earlier rows stay."""
    out = tmp_path / "out"
    session = start(load_experiment(experiment_file(tmp_path, GOOD)), out)
    advance(session)  # to tick 144, snapshot at 144
    assert session.gateway.calls is not None
    for tick in (143, 144, 200):
        session.gateway.calls.append(
            CallRecord(
                tick,
                "a",
                "probe",
                "m",
                "f",
                "fake-m",
                "h",
                1,
                1,
                0.0,
                True,
                None,
                1,
                False,
                None,
                "{}",
            )
        )
    session.close()
    again = reopen(out)
    assert again.state.tick == 144
    assert [r.tick for r in calls_of(again.gateway)] == [143]
    again.close()


@pytest.mark.req("REQ-LLM-002")
def test_replay_needs_no_model_installed(tmp_path: Path) -> None:
    """ADR-0017: a recorded run replays without any model; the model check is skipped."""
    ResponseCache(tmp_path / "cache.sqlite", "record").close()
    baseline = tmp_path / "baseline"
    plain = tmp_path / "plain.yaml"
    plain.write_text(yaml.safe_dump(TINY), encoding="utf-8")
    assert main(["run", str(plain), "--out", str(baseline), "--days", "2"]) == 0
    data = copy.deepcopy(TINY)
    data["llm"] = {
        "cache": "replay",
        "cache_from": "cache.sqlite",
        "backends": {"local": {"kind": "ollama", "url": f"http://127.0.0.1:{unused_port()}"}},
        "models": {"q": {"backend": "local", "name": "qwen3"}},
        "assign": {"q": 1.0},
    }
    path = tmp_path / "replay.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["run", str(path), "--out", str(out)]) == 0
    assert main(["resume", str(out), "--days", "2"]) == 0  # reopen skips the check as well
    first = RunDirectory.open(baseline)
    second = RunDirectory.open(out)
    assert second.event_log.last_tick() == 2 * 144 - 1
    assert first.event_log.last_tick() == second.event_log.last_tick()
    assert first.event_log.digest() == second.event_log.digest()
    first.close()
    second.close()


@pytest.mark.req("REQ-LLM-002")
def test_a_failure_while_opening_the_gateway_leaves_nothing_behind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: if the run cannot be completed after its directory exists, the directory goes."""
    import pericles.experiment.launch as launch

    def broken(*args: object, **kwargs: object) -> Gateway:
        raise LLMSetupError("boom")

    closed: list[Path] = []
    original = RunDirectory.close

    def close(self: RunDirectory) -> None:
        closed.append(self.path)
        original(self)

    monkeypatch.setattr(launch, "open_gateway", broken)
    monkeypatch.setattr(RunDirectory, "close", close)
    experiment = load_experiment(experiment_file(tmp_path, GOOD))
    out = tmp_path / "out"
    with pytest.raises(LLMSetupError, match="boom"):
        start(experiment, out)
    assert not out.exists()
    assert closed == [out]
    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(LLMSetupError, match="boom"):
        start(experiment, existing)
    assert existing.is_dir() and list(existing.iterdir()) == []
