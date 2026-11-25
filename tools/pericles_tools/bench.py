"""Engine + scripted-agent throughput (REQ-NFR-003; ADR-0016 §8)."""

from __future__ import annotations

import argparse
import cProfile
import pstats
import tempfile
import time
from pathlib import Path

import yaml

from pericles.agents.scripted import scripted_controller
from pericles.core.engine import Engine
from pericles.experiment.config import Experiment, build_world, experiment_from_mapping

BASELINE = Path(__file__).resolve().parents[2] / "experiments" / "baseline.yaml"
SKILLS = ("foraging", "woodcutting", "masonry", "fishing", "hunting")
SEXES = ("female", "male")
AGES = (140, 200, 260, 320, 380)
SKILL_LEVEL = 20.0
PROFILE_ROWS = 20


def perf_experiment(villagers: int = 150, size: int = 128) -> Experiment:
    """The baseline village's map and settings at NFR-003 scale."""
    raw = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    raw["map"] = {**raw["map"], "width": size, "height": size}
    raw["population"] = [
        {
            "id": f"p{i:03d}",
            "name": f"P{i}",
            "sex": SEXES[i % len(SEXES)],
            "age_days": AGES[i % len(AGES)],
            "skills": {SKILLS[i % len(SKILLS)]: SKILL_LEVEL},
        }
        for i in range(villagers)
    ]
    with tempfile.TemporaryDirectory() as base:
        return experiment_from_mapping(raw, Path(base))


def measure(villagers: int = 150, size: int = 128, warmup: int = 2000, ticks: int = 3000) -> float:
    """Ticks per second over `ticks` steps after `warmup` steps, engine plus scripted agents."""
    experiment = perf_experiment(villagers, size)
    engine = Engine(experiment.registry, experiment.engine)
    controller = scripted_controller(engine.context, experiment.agents)
    state = build_world(experiment)
    for _ in range(warmup):
        state, events = engine.step(state, controller.intents(state))
        controller.observe(state, events)
    started = time.perf_counter()
    for _ in range(ticks):
        state, events = engine.step(state, controller.intents(state))
        controller.observe(state, events)
    return ticks / (time.perf_counter() - started)


def main() -> None:
    parser = argparse.ArgumentParser(prog="pericles_tools.bench")
    parser.add_argument("--villagers", type=int, default=150)
    parser.add_argument("--size", type=int, default=128)
    parser.add_argument("--warmup", type=int, default=2000)
    parser.add_argument("--ticks", type=int, default=3000)
    parser.add_argument("--profile", action="store_true")
    args = parser.parse_args()
    profile = cProfile.Profile()
    if args.profile:
        profile.enable()
    rate = measure(args.villagers, args.size, args.warmup, args.ticks)
    if args.profile:
        profile.disable()
        pstats.Stats(profile).sort_stats("cumulative").print_stats(PROFILE_ROWS)
    print(f"{rate:.0f} ticks/s ({args.villagers} villagers, {args.size}x{args.size})")


if __name__ == "__main__":
    main()
