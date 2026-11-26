"""Start, continue and advance a run directory from an experiment (ADR-0016 §5-§7)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pericles.agents.controller import Controller
from pericles.agents.scripted import scripted_controller
from pericles.analysis.metrics import daily_survival
from pericles.core.engine import Engine
from pericles.core.state import WorldState
from pericles.experiment.config import Experiment, build_world, experiment_from_mapping
from pericles.experiment.rundir import RunDirectory
from pericles.experiment.runner import resume, run


@dataclass
class Session:
    run_dir: RunDirectory
    experiment: Experiment
    engine: Engine
    state: WorldState
    controller: Controller


def start(experiment: Experiment, out: Path) -> Session:
    """Build everything first, so a world that cannot be built leaves no run directory."""
    state = build_world(experiment)
    engine = Engine(experiment.registry, experiment.engine)
    controller = scripted_controller(engine.context, experiment.agents)
    run_dir = RunDirectory.create(out, experiment.resolved, seed=experiment.seed)
    return Session(run_dir, experiment, engine, state, controller)


def reopen(out: Path) -> Session:
    """Continue from the last usable snapshot; the run directory is closed if that fails."""
    run_dir = RunDirectory.open(out)
    try:
        experiment = experiment_from_mapping(run_dir.config, run_dir.path)
        engine = Engine(experiment.registry, experiment.engine)
        controller = scripted_controller(engine.context, experiment.agents)
        state, _ = resume(run_dir, controller.load)
    except BaseException:
        run_dir.close()
        raise
    return Session(run_dir, experiment, engine, state, controller)


def advance(session: Session, days: int | None = None) -> WorldState:
    """Run until `days` in-game days in total (default: run.days); then rewrite the metrics.

    The metrics run through the current tick's day: the last row is the village at the start
    of the current day (ADR-0016 §6)."""
    per_day = session.experiment.engine.calendar.ticks_per_day
    total = session.experiment.run.days if days is None else days
    session.state = run(
        session.run_dir,
        session.engine,
        session.state,
        session.controller,
        max(session.state.tick, total * per_day),
        session.experiment.run.snapshot_every_days * per_day,
    )
    log = session.run_dir.event_log
    rows = daily_survival(session.run_dir.config, log.events(), session.state.tick)
    session.run_dir.write_metrics(rows)
    return session.state
