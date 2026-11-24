"""Scripted-behaviour parameters (ADR-0016). Every field is settable from a settings file."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

RELIEFS = ("eat", "sleep", "shelter")
MAX_LEVEL = 100.0


def _act_at() -> dict[str, float]:
    return {"eat": 50.0, "sleep": 75.0, "shelter": 60.0}


def _urgent_at() -> dict[str, float]:
    return {"eat": 85.0, "sleep": 95.0, "shelter": 85.0}


@dataclass(frozen=True)
class AgentConfig:
    # Need levels at which a villager acts, and at which it drops its work (ADR-0016 §2-§3)
    act_at: dict[str, float] = field(default_factory=_act_at)
    urgent_at: dict[str, float] = field(default_factory=_urgent_at)
    warm_until: float = 10.0
    # Carrying and stocking (ADR-0016 §4)
    food_carry: float = 60.0
    deposit_load: float = 0.7
    food_reserve_per_capita: float = 60.0
    storage_per_capita: float = 15.0
    skill_weight: float = 1.0
    # Building
    house_building: str = "house"
    store_building: str = "storehouse"
    site_search_radius: int = 12
    site_gap: int = 1
    max_builders: int = 3
    # Searching and pacing
    node_search_radius: int = 48
    index_cell: int = 8
    avoid_ticks: int = 240
    idle_ticks: int = 15
    # Children and couples
    child_follow_radius: int = 4
    couples: bool = True

    def __post_init__(self) -> None:
        problems = _problems(self)
        if problems:
            raise ValueError("; ".join(problems))


def _problems(c: AgentConfig) -> list[str]:
    if set(c.act_at) != set(RELIEFS) or set(c.urgent_at) != set(RELIEFS):
        return [f"act_at and urgent_at must give a level for each of {RELIEFS}"]
    levels = [*c.act_at.values(), *c.urgent_at.values()]
    reals = [
        *levels,
        c.warm_until,
        c.food_carry,
        c.deposit_load,
        c.food_reserve_per_capita,
        c.storage_per_capita,
        c.skill_weight,
    ]
    if not all(math.isfinite(v) for v in reals):
        return ["numeric parameters must be finite"]
    non_negative = (
        c.food_carry,
        c.food_reserve_per_capita,
        c.storage_per_capita,
        c.skill_weight,
        c.site_search_radius,
        c.site_gap,
        c.node_search_radius,
        c.child_follow_radius,
    )
    positive = (c.index_cell, c.avoid_ticks, c.idle_ticks, c.max_builders)
    checks = [
        (all(0 < v <= MAX_LEVEL for v in levels), "levels must be in (0, 100]"),
        (all(c.act_at[r] <= c.urgent_at[r] for r in RELIEFS), "need act_at <= urgent_at"),
        (0 <= c.warm_until < c.act_at["shelter"], "warm_until must be in [0, act_at.shelter)"),
        (0 < c.deposit_load <= 1, "deposit_load must be in (0, 1]"),
        (all(v >= 0 for v in non_negative), "amounts, weights and radii must be non-negative"),
        (all(v > 0 for v in positive), "cells, tick counts and builder limits must be positive"),
        (bool(c.house_building and c.store_building), "building ids must be non-empty"),
    ]
    return [message for ok, message in checks if not ok]
