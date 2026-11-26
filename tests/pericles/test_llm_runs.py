import sqlite3
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo
from pericles.core.mapgen import TileMap
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config
from pericles.experiment.llm import CACHE_FILE, CALLS_FILE, open_gateway, replay_source
from pericles.experiment.rundir import RunDirectory
from pericles.experiment.runner import resume, run
from pericles.llm.backend import Backend, LLMSetupError
from pericles.llm.cache import ResponseCache
from pericles.llm.config import BackendSpec, LLMConfig
from pericles.llm.fake import FakeBackend, FakeError, FakeRule
from pericles.llm.gateway import BackendUnavailable, Gateway
from pericles.llm.types import Message, ModelSpec, Request, Sampling


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pick: int


class ProbeAgents:
    """Test agents: every 7 ticks each villager asks the gateway where to walk."""

    def __init__(self, gateway: Gateway, walkable: list[Coord]) -> None:
        self.gateway = gateway
        self.walkable = walkable

    def intents(self, state: WorldState) -> Sequence[Intent]:
        if state.tick % 7:
            return []
        ids = sorted(state.villagers)
        requests = [
            Request(
                "probe",
                v,
                state.tick,
                "m",
                (Message("user", f"{v} at {state.tick}"),),
                state.tick,
                Probe,
            )
            for v in ids
        ]
        results = self.gateway.complete_all(requests)
        return [
            MoveTo(v, self.walkable[r.value.pick % len(self.walkable)])
            for v, r in zip(ids, results, strict=True)
            if isinstance(r.value, Probe)
        ]

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        return None

    def events(self) -> list[tuple[str, dict[str, Any]]]:
        return []

    def to_dict(self) -> dict[str, Any]:
        return {}


def setup(small_map: TileMap, registry: Registry) -> tuple[WorldState, list[Coord]]:
    walkable = [
        Coord(x, y)
        for y in range(small_map.height)
        for x in range(small_map.width)
        if registry.terrains[small_map.terrain_at(Coord(x, y))].walkable
    ]
    villagers = [Villager(f"v{i}", f"V{i}", small_map.start(), model="m") for i in range(3)]
    return WorldState.new(5, small_map, villagers), walkable


def config(cache: str, cache_from: Path | None = None) -> LLMConfig:
    return LLMConfig(
        cache=cache,
        cache_from=None if cache_from is None else str(cache_from),
        backoff_base_s=0.001,
        backoff_max_s=0.001,
        max_backend_failures=2,
        backends={"test": BackendSpec("fake", 1, 1.0)},
        models={"m": ModelSpec("test", "fake-m", Sampling(0.7, 0.9, 16))},
    )


def drive(
    path: Path,
    llm: LLMConfig,
    backend: Backend,
    small_map: TileMap,
    registry: Registry,
    until: int = 30,
) -> RunDirectory:
    state, walkable = setup(small_map, registry)
    run_dir = RunDirectory.create(path, {}, seed=5)
    gateway = open_gateway(llm, {"test": backend}, run_dir)
    try:
        run(
            run_dir,
            Engine(registry, default_config()),
            state,
            ProbeAgents(gateway, walkable),
            until,
            10,
        )
    finally:
        gateway.close()
    return run_dir


@pytest.mark.req("REQ-LLM-005")
def test_a_replayed_run_has_the_same_event_digest(
    tmp_path: Path, small_map: TileMap, registry: Registry
) -> None:
    """LLM-005 AC3: replay mode reproduces the event log without any backend call."""
    picks = tuple(f'{{"pick": {n * 37}}}' for n in range(40))
    recorded = drive(
        tmp_path / "rec", config("record"), FakeBackend([FakeRule(picks)]), small_map, registry
    )
    silent = FakeBackend()
    replayed = drive(
        tmp_path / "rep", config("replay", tmp_path / "rec"), silent, small_map, registry
    )
    assert silent.calls == []
    assert replayed.event_log.digest() == recorded.event_log.digest()
    assert (tmp_path / "rep" / "llm_cache" / CACHE_FILE).exists()
    recorded.close()
    replayed.close()


@pytest.mark.req("REQ-LLM-005")
def test_replay_source_accepts_a_run_its_cache_dir_or_the_file(tmp_path: Path) -> None:
    """AC2: cache_from may point at the run, its llm_cache, or responses.sqlite."""
    cache = tmp_path / "run" / "llm_cache"
    cache.mkdir(parents=True)
    ResponseCache(cache / CACHE_FILE, "record").close()
    for given in (tmp_path / "run", cache, cache / CACHE_FILE):
        assert replay_source(given) == cache / CACHE_FILE
    with pytest.raises(LLMSetupError, match=r"llm\.cache_from: no responses\.sqlite"):
        replay_source(tmp_path / "nowhere")


@pytest.mark.req("REQ-LLM-005")
def test_replay_source_rejects_files_that_are_not_response_caches(tmp_path: Path) -> None:
    """AC2: a bad cache_from is reported by name before any run directory exists."""
    text = tmp_path / "exp.yaml"
    text.write_text("seed: 1\n", encoding="utf-8")
    with pytest.raises(
        LLMSetupError, match=r"llm\.cache_from: .*exp\.yaml is not a response cache"
    ):
        replay_source(text)
    other = tmp_path / "other.sqlite"
    sqlite3.connect(other).close()
    with pytest.raises(
        LLMSetupError, match=r"llm\.cache_from: .*other\.sqlite is not a response cache"
    ):
        replay_source(other)


@pytest.mark.req("REQ-LLM-009")
def test_a_backend_that_stays_down_stops_the_run_cleanly_and_it_resumes(
    tmp_path: Path, small_map: TileMap, registry: Registry
) -> None:
    """AC1: after max_backend_failures the run stops at a tick boundary and can be resumed."""
    engine = Engine(registry, default_config())
    state, walkable = setup(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=5)
    # Tick 0: three good replies (one per villager). Tick 7: every call fails twice -> stop.
    flaky = FakeBackend(
        [FakeRule(('{"pick": 1}', '{"pick": 2}', '{"pick": 3}', FakeError("down")))]
    )
    gateway = open_gateway(config("record"), {"test": flaky}, run_dir)
    with pytest.raises(BackendUnavailable, match="2 failures in a row"):
        run(run_dir, engine, state, ProbeAgents(gateway, walkable), 30, 10)
    assert gateway.calls is not None
    stopped_log = list(gateway.calls.records())
    gateway.close()
    # the stop left failure rows behind: the resume must not keep them
    assert any((r.error or "").startswith("backend:") for r in stopped_log)
    assert run_dir.event_log.last_tick() == 6  # ticks 0-6 are whole; tick 7 never stepped
    assert gateway.calls is not None
    restored, _ = resume(run_dir)
    assert restored.tick == 0  # the only snapshot is tick 0
    resumed_at = restored.tick  # run() advances the restored state in place
    healthy = FakeBackend([FakeRule(('{"pick": 4}',))])
    gateway = open_gateway(config("record"), {"test": healthy}, run_dir)
    assert gateway.calls is not None
    gateway.calls.truncate_after(restored.tick - 1)
    run(run_dir, engine, restored, ProbeAgents(gateway, walkable), 30, 10)
    assert run_dir.event_log.last_tick() == 29
    rows = list(gateway.calls.records())
    assert all(r.tick >= resumed_at for r in rows)
    assert not any((r.error or "").startswith("backend:") for r in rows)
    assert Counter(r.tick for r in rows) == {t: 3 for t in (0, 7, 14, 21, 28)}
    assert (tmp_path / "run" / CALLS_FILE).exists()
    gateway.close()
    run_dir.close()
