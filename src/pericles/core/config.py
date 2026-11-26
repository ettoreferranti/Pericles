"""Engine parameters (ADR-0014, ADR-0015). Every field is settable from a settings file."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, fields

from pericles.core.calendar import Calendar, Season

MODEL_RULES = ("inherit", "fixed")


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
    # Health and needs (ADR-0015 §1-§3)
    max_health: float = 100.0
    health_regen_per_hour: float = 1.0
    sleep_relief_per_hour: float = 12.0
    home_sleep_multiplier: float = 2.0
    shelter_relief_per_hour: float = 20.0
    # Age, couples and births (ADR-0015 §5-§7)
    sexes: tuple[str, ...] = ("female", "male")
    bearing_sex: str = "female"
    adult_age_days: int = 120
    old_age_days: int = 600
    old_age_death_chance: float = 0.002
    old_age_death_growth: float = 1.02
    gestation_days: int = 10
    birth_interval_days: int = 10
    conception_chance_per_day: float = 0.2
    birth_food_per_capita: float = 50.0
    couple_proposal_ttl_ticks: int = 60
    # Children and coming of age (ADR-0015 §8-§9)
    model_rule: str = "inherit"
    adult_model: str | None = None
    child_names: tuple[str, ...] = ()
    child_intents: tuple[str, ...] = (
        "move_to",
        "wait",
        "start_action",
        "eat",
        "sleep",
        "take",
        "deposit",
    )
    child_action_tags: tuple[str, ...] = ("light",)
    family_events: tuple[str, ...] = ("born", "died", "couple_formed", "came_of_age")
    village_events: tuple[str, ...] = ("building_completed", "technology_learned")
    childhood_memory_limit: int = 20
    # Experiment guard (ADR-0017 §9): a typo in map size must not hang map generation
    max_map_tiles: int = 1_048_576

    def __post_init__(self) -> None:
        problems = _problems(self)
        if problems:
            raise ValueError("; ".join(problems))


def _problems(c: EngineConfig) -> list[str]:
    floats = [getattr(c, f.name) for f in fields(c) if isinstance(getattr(c, f.name), float)]
    rates = (c.health_regen_per_hour, c.sleep_relief_per_hour, c.shelter_relief_per_hour)
    if not all(math.isfinite(v) for v in floats):
        return ["numeric parameters must be finite"]
    checks = [
        (c.carry_limit > 0, "carry_limit must be positive"),
        (c.max_skill > 0, "max_skill must be positive"),
        (
            c.skill_practice >= 0 and c.skill_speed_per_level >= 0,
            "skill rates must be non-negative",
        ),
        (c.max_health > 0, "max_health must be positive"),
        (min(rates) >= 0, "relief and regeneration rates must be non-negative"),
        (c.home_sleep_multiplier >= 1, "home_sleep_multiplier must be at least 1"),
        (
            len(c.sexes) > 0 and len(set(c.sexes)) == len(c.sexes),
            "sexes must be non-empty and unique",
        ),
        (c.bearing_sex in c.sexes, "bearing_sex must be one of sexes"),
        (c.adult_age_days > 0, "adult_age_days must be positive"),
        (c.old_age_days >= c.adult_age_days, "old_age_days must be at least adult_age_days"),
        (0 <= c.old_age_death_chance <= 1, "old_age_death_chance must be in [0, 1]"),
        (c.old_age_death_growth >= 1, "old_age_death_growth must be at least 1"),
        (c.gestation_days > 0, "gestation_days must be positive"),
        (c.birth_interval_days >= 0, "birth_interval_days must be non-negative"),
        (0 <= c.conception_chance_per_day <= 1, "conception_chance_per_day must be in [0, 1]"),
        (c.birth_food_per_capita >= 0, "birth_food_per_capita must be non-negative"),
        (c.couple_proposal_ttl_ticks > 0, "couple_proposal_ttl_ticks must be positive"),
        (c.model_rule in MODEL_RULES, f"model_rule must be one of {MODEL_RULES}"),
        (
            c.model_rule != "fixed" or c.adult_model is not None,
            "model_rule 'fixed' needs adult_model",
        ),
        (c.childhood_memory_limit >= 0, "childhood_memory_limit must be non-negative"),
        (c.max_map_tiles >= 1, "max_map_tiles must be at least 1"),
    ]
    return [message for ok, message in checks if not ok]
