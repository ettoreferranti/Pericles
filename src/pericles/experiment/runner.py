"""Drive engine and agents, persist each tick, snapshot, resume after crashes (REQ-EXP-003)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.intents import Intent
from pericles.core.state import WorldState
from pericles.experiment.rundir import RunDirectory, RunDirectoryError

IntentSource = Callable[[WorldState], Sequence[Intent]]


class Agents(Protocol):
    def intents(self, state: WorldState) -> Sequence[Intent]: ...

    def observe(self, state: WorldState, events: Sequence[Event]) -> None: ...

    def to_dict(self) -> dict[str, Any]: ...


class SourceAgents:
    """A plain intent function (tests, replays) as stateless agents."""

    def __init__(self, source: IntentSource) -> None:
        self.source = source

    def intents(self, state: WorldState) -> Sequence[Intent]:
        return self.source(state)

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {}


def run(
    run_dir: RunDirectory,
    engine: Engine,
    state: WorldState,
    agents: Agents,
    until_tick: int,
    snapshot_every: int,
    *,
    stop_when_extinct: bool = True,
) -> WorldState:
    if snapshot_every < 1:
        raise ValueError("snapshot_every must be at least 1")
    if until_tick < state.tick:
        raise ValueError(f"until_tick {until_tick} is before the current tick {state.tick}")
    log = run_dir.event_log
    if state.tick % snapshot_every == 0 and state.tick not in run_dir.snapshot_ticks():
        run_dir.save_snapshot(state, agents.to_dict())
    while state.tick < until_tick:
        if stop_when_extinct and not state.villagers:
            run_dir.save_snapshot(state, agents.to_dict())
            break
        state, events = engine.step(state, agents.intents(state))
        agents.observe(state, events)
        log.append_tick(state.tick - 1, events)
        if state.tick % snapshot_every == 0:
            run_dir.save_snapshot(state, agents.to_dict())
    return state


def resume(
    run_dir: RunDirectory, load: Callable[[dict[str, Any]], None] | None = None
) -> tuple[WorldState, dict[str, Any]]:
    """Restore the newest usable snapshot the event log covers; truncate the log to it.

    `load` receives the snapshot's agents blob. A snapshot whose world or agents blob cannot
    be restored is skipped, and the next older one is tried."""
    last = run_dir.event_log.last_tick()
    logged = 0 if last is None else last + 1
    for snapshot in run_dir.snapshots():
        path = run_dir.snapshot_path(snapshot.tick)
        if snapshot.tick > logged:
            run_dir.skip(path)
            continue
        try:
            state = WorldState.from_dict(snapshot.world)
            if load is not None:
                load(snapshot.agents)
        except (KeyError, TypeError, ValueError, AttributeError):
            run_dir.skip(path)
            continue
        run_dir.event_log.truncate_after(state.tick - 1)
        return state, snapshot.agents
    raise RunDirectoryError(f"{run_dir.path}: no usable snapshot to resume from")
