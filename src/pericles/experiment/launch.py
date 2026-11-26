"""Start, continue and advance a run directory from an experiment (ADR-0016 §5-§7)."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from pericles.agents.controller import Controller
from pericles.agents.scripted import scripted_controller
from pericles.analysis.metrics import daily_survival
from pericles.core.engine import Engine
from pericles.core.state import WorldState
from pericles.experiment.config import Experiment, build_world, experiment_from_mapping
from pericles.experiment.llm import build_backends, open_gateway, replay_source, run_meta
from pericles.experiment.rundir import RunDirectory
from pericles.experiment.runner import resume, run
from pericles.llm.backend import Backend
from pericles.llm.cache import CacheMiss
from pericles.llm.gateway import BackendUnavailable, Gateway, check_models


@dataclass
class Session:
    run_dir: RunDirectory
    experiment: Experiment
    engine: Engine
    state: WorldState
    controller: Controller
    gateway: Gateway

    def close(self) -> None:
        self.gateway.close()
        self.run_dir.close()


def _backends(experiment: Experiment) -> dict[str, Backend]:
    """Build every backend, and check its models unless the run replays a cache.

    A replay needs no model installed (ADR-0017 §5); anything else fails here, before
    anything is written (§11)."""
    backends = build_backends(experiment.llm)
    if experiment.llm.cache != "replay":
        check_models(experiment.llm.models, backends)
    return backends


def start(experiment: Experiment, out: Path) -> Session:
    """Build and check everything first, so a run that cannot start leaves no directory."""
    state = build_world(experiment)
    engine = Engine(experiment.registry, experiment.engine)
    controller = scripted_controller(engine.context, experiment.agents)
    backends = _backends(experiment)
    if experiment.llm.cache == "replay":  # a resumed replay run already holds its copy
        assert experiment.llm.cache_from is not None
        replay_source(Path(experiment.llm.cache_from))
    existed = out.exists()
    run_dir = RunDirectory.create(
        out, experiment.resolved, seed=experiment.seed, extra=run_meta(experiment.llm)
    )
    try:
        gateway = open_gateway(experiment.llm, backends, run_dir)
    except BaseException:
        run_dir.close()
        _remove_created(out, existed)
        raise
    return Session(run_dir, experiment, engine, state, controller, gateway)


def _remove_created(out: Path, existed: bool) -> None:
    """Undo RunDirectory.create: the directory itself goes only if that call made it."""
    if not existed:
        shutil.rmtree(out)
        return
    for child in out.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()


def reopen(out: Path) -> Session:
    """Continue from the last usable snapshot; the run directory is closed if that fails."""
    run_dir = RunDirectory.open(out)
    try:
        experiment = experiment_from_mapping(run_dir.config, run_dir.path)
        engine = Engine(experiment.registry, experiment.engine)
        controller = scripted_controller(engine.context, experiment.agents)
        backends = _backends(experiment)
        state, _ = resume(run_dir, controller.load)
        gateway = open_gateway(experiment.llm, backends, run_dir)
        if gateway.calls is not None:
            gateway.calls.truncate_after(state.tick - 1)
    except BaseException:
        run_dir.close()
        raise
    return Session(run_dir, experiment, engine, state, controller, gateway)


def advance(session: Session, days: int | None = None) -> WorldState:
    """Run until `days` in-game days in total (default: run.days); then rewrite the metrics.

    The metrics run through the current tick's day: the last row is the village at the start
    of the current day (ADR-0016 §6)."""
    per_day = session.experiment.engine.calendar.ticks_per_day
    total = session.experiment.run.days if days is None else days
    try:
        session.state = run(
            session.run_dir,
            session.engine,
            session.state,
            session.controller,
            max(session.state.tick, total * per_day),
            session.experiment.run.snapshot_every_days * per_day,
        )
    except (BackendUnavailable, CacheMiss):
        _write_metrics(session)
        raise
    _write_metrics(session)
    return session.state


def _write_metrics(session: Session) -> None:
    log = session.run_dir.event_log
    last = log.last_tick()
    through = 0 if last is None else last + 1
    rows = daily_survival(session.run_dir.config, log.events(), through)
    session.run_dir.write_metrics(rows)
