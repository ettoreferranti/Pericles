"""Drive the engine, persist each tick, snapshot, and resume after crashes (REQ-EXP-003)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pericles.core.engine import Engine
from pericles.core.intents import Intent
from pericles.core.state import WorldState
from pericles.experiment.rundir import RunDirectory, RunDirectoryError

IntentSource = Callable[[WorldState], Sequence[Intent]]


def run(
    run_dir: RunDirectory,
    engine: Engine,
    state: WorldState,
    source: IntentSource,
    until_tick: int,
    snapshot_every: int,
) -> WorldState:
    if snapshot_every < 1:
        raise ValueError("snapshot_every must be at least 1")
    if until_tick < state.tick:
        raise ValueError(f"until_tick {until_tick} is before the current tick {state.tick}")
    log = run_dir.event_log
    if state.tick % snapshot_every == 0 and state.tick not in run_dir.snapshot_ticks():
        run_dir.save_snapshot(state)
    while state.tick < until_tick:
        intents = source(state)
        state, events = engine.step(state, intents)
        log.append_tick(state.tick - 1, events)
        if state.tick % snapshot_every == 0:
            run_dir.save_snapshot(state)
    return state


def resume(run_dir: RunDirectory) -> WorldState:
    snapshot = run_dir.latest_snapshot()
    if snapshot is None:
        raise RunDirectoryError(f"{run_dir.path}: no snapshot to resume from")
    state = WorldState.from_dict(snapshot)
    run_dir.event_log.truncate_after(state.tick - 1)
    return state
