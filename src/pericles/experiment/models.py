"""Assign models to villagers: pins first, then a seeded ratio split (REQ-LLM-006; ADR-0017 §10)."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pericles.experiment.config import VillagerSpec


def quotas(n: int, ratios: Mapping[str, float]) -> dict[str, int]:
    """Exact counts summing to `n`, by the largest remainder; ties go to the model key."""
    total = sum(ratios.values())
    exact = {m: n * r / total for m, r in ratios.items()}
    counts = {m: int(v) for m, v in exact.items()}
    left = n - sum(counts.values())
    for m in sorted(exact, key=lambda m: (-(exact[m] - counts[m]), m))[:left]:
        counts[m] += 1
    return dict(sorted(counts.items()))


def assign_models(
    specs: Sequence[VillagerSpec], adult_age_days: int, ratios: Mapping[str, float], seed: int
) -> tuple[VillagerSpec, ...]:
    if not ratios:
        return tuple(specs)
    free = sorted(s.id for s in specs if s.model is None and s.age_days >= adult_age_days)
    random.Random(f"pericles-models:{seed}").shuffle(free)
    order = [m for m, count in quotas(len(free), ratios).items() for _ in range(count)]
    chosen = dict(zip(free, order, strict=True))
    return tuple(
        s.model_copy(update={"model": chosen[s.id]}) if s.id in chosen else s for s in specs
    )
