"""Seeded trait draws for population entries that leave traits out (REQ-AGT-009; ADR-0018 §10)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pericles.experiment.config import VillagerSpec


def draw_traits(
    population: Sequence[VillagerSpec], traits: Sequence[str], count: int, seed: int
) -> list[VillagerSpec]:
    if count > len(traits):
        raise ValueError(
            f"drawn_traits: {count} is more than the {len(traits)} traits in the packs"
        )
    if count == 0:
        return list(population)
    rng = random.Random(f"traits:{seed}")
    pool = sorted(traits)
    return [
        spec
        if spec.traits is not None
        else spec.model_copy(update={"traits": tuple(sorted(rng.sample(pool, count)))})
        for spec in population
    ]
