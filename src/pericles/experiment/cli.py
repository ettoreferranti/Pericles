"""`pericles run` and `pericles resume` (REQ-EXP-003; ADR-0016)."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from pericles.experiment.config import ExperimentError, load_experiment
from pericles.experiment.launch import advance, reopen, start
from pericles.experiment.rundir import RunDirectoryError

EXIT_ERROR = 2


def _days(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pericles", description="Run Pericles villages.")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="start a run from an experiment file")
    run.add_argument("experiment", type=Path)
    run.add_argument("--out", type=Path, required=True, help="a new, empty run directory")
    run.add_argument("--days", type=_days, help="total in-game days (default: run.days)")
    again = sub.add_parser("resume", help="continue a run from its last usable snapshot")
    again.add_argument("run_dir", type=Path)
    again.add_argument("--days", type=_days, help="total in-game days (default: run.days)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "run":
            session = start(load_experiment(args.experiment), args.out)
        else:
            session = reopen(args.run_dir)
    except (ExperimentError, RunDirectoryError) as error:
        print(f"pericles: {error}", file=sys.stderr)
        return EXIT_ERROR
    try:
        for path in session.run_dir.skipped:
            print(f"pericles: skipped unusable snapshot {path}", file=sys.stderr)
        state = advance(session, args.days)
    finally:
        session.run_dir.close()
    day = state.tick // session.experiment.engine.calendar.ticks_per_day
    if state.villagers:
        print(f"Day {day}: {len(state.villagers)} villagers.")
    else:
        print(f"The village died out on day {day}.")
    return 0
