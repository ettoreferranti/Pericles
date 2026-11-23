"""Engine parameters (ADR-0014)."""

from __future__ import annotations

from dataclasses import dataclass, field

from pericles.core.calendar import Calendar, Season


def _neutral_calendar() -> Calendar:
    return Calendar(seasons=(Season("year", 40),))


@dataclass(frozen=True)
class EngineConfig:
    calendar: Calendar = field(default_factory=_neutral_calendar)
    carry_limit: float = 30.0
    max_skill: float = 100.0
    skill_practice: float = 1.0
    skill_speed_per_level: float = 0.005
    debug_invariants: bool = False

    def __post_init__(self) -> None:
        if self.carry_limit <= 0:
            raise ValueError("carry_limit must be positive")
        if self.max_skill <= 0:
            raise ValueError("max_skill must be positive")
        if self.skill_practice < 0 or self.skill_speed_per_level < 0:
            raise ValueError("skill rates must be non-negative")
