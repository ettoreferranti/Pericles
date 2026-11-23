import math

import pytest

from pericles.core.calendar import Calendar, Season
from pericles.core.config import MODEL_RULES, EngineConfig


@pytest.mark.req("REQ-SIM-013")
def test_defaults() -> None:
    """AC2: the carry limit is an engine parameter with a documented default."""
    config = EngineConfig()
    assert config.carry_limit == 30.0
    assert (config.max_skill, config.skill_practice, config.skill_speed_per_level) == (
        100.0,
        1.0,
        0.005,
    )
    assert config.debug_invariants is False
    assert config.calendar == Calendar(seasons=(Season("year", 40),))


@pytest.mark.req("REQ-SIM-014")
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"carry_limit": 0.0}, "carry_limit must be positive"),
        ({"max_skill": 0.0}, "max_skill must be positive"),
        ({"skill_practice": -1.0}, "skill rates must be non-negative"),
        ({"skill_speed_per_level": -0.1}, "skill rates must be non-negative"),
    ],
)
def test_invalid_config_is_rejected(kwargs: dict[str, float], message: str) -> None:
    """AC1/AC2: skill parameters are validated."""
    with pytest.raises(ValueError, match=f"^{message}$"):
        EngineConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.req("REQ-SIM-014")
@pytest.mark.parametrize(
    "kwargs",
    [
        {"carry_limit": 0.5},
        {"max_skill": 0.5},
        {"skill_practice": 0.0},
        {"skill_speed_per_level": 0.0},
        {"skill_practice": 0.5, "skill_speed_per_level": 0.5},
    ],
)
def test_boundary_values_are_accepted(kwargs: dict[str, float]) -> None:
    """AC1/AC2: zero skill rates and small positive limits are valid."""
    config = EngineConfig(**kwargs)  # type: ignore[arg-type]
    assert config == EngineConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.req("REQ-SIM-012")
def test_life_defaults_are_valid() -> None:
    """The core defaults describe a working life cycle."""
    config = EngineConfig()
    assert config.max_health == 100.0
    assert config.sexes == ("female", "male")
    assert config.bearing_sex == "female"
    assert config.model_rule == "inherit"
    assert config.adult_model is None
    assert config.child_intents == (
        "move_to",
        "wait",
        "start_action",
        "eat",
        "sleep",
        "take",
        "deposit",
    )
    assert config.child_action_tags == ("light",)
    assert MODEL_RULES == ("inherit", "fixed")


@pytest.mark.req("REQ-SIM-012")
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"max_health": 0.0}, "max_health must be positive"),
        ({"health_regen_per_hour": -1.0}, "relief and regeneration rates must be non-negative"),
        ({"sleep_relief_per_hour": -1.0}, "relief and regeneration rates must be non-negative"),
        ({"shelter_relief_per_hour": -1.0}, "relief and regeneration rates must be non-negative"),
        ({"home_sleep_multiplier": 0.5}, "home_sleep_multiplier must be at least 1"),
        (
            {"sexes": ()},
            "sexes must be non-empty and unique; bearing_sex must be one of sexes",
        ),
        ({"sexes": ("f", "f"), "bearing_sex": "f"}, "sexes must be non-empty and unique"),
        ({"bearing_sex": "other"}, "bearing_sex must be one of sexes"),
        ({"adult_age_days": 0}, "adult_age_days must be positive"),
        (
            {"old_age_days": 10, "adult_age_days": 20},
            "old_age_days must be at least adult_age_days",
        ),
        ({"old_age_death_chance": 1.5}, r"old_age_death_chance must be in \[0, 1\]"),
        ({"old_age_death_chance": -0.1}, r"old_age_death_chance must be in \[0, 1\]"),
        ({"old_age_death_growth": 0.9}, "old_age_death_growth must be at least 1"),
        ({"gestation_days": 0}, "gestation_days must be positive"),
        ({"birth_interval_days": -1}, "birth_interval_days must be non-negative"),
        ({"conception_chance_per_day": 2.0}, r"conception_chance_per_day must be in \[0, 1\]"),
        ({"birth_food_per_capita": -1.0}, "birth_food_per_capita must be non-negative"),
        ({"couple_proposal_ttl_ticks": 0}, "couple_proposal_ttl_ticks must be positive"),
        ({"model_rule": "random"}, r"model_rule must be one of \('inherit', 'fixed'\)"),
        ({"model_rule": "fixed"}, "model_rule 'fixed' needs adult_model"),
        ({"childhood_memory_limit": -1}, "childhood_memory_limit must be non-negative"),
        ({"carry_limit": math.inf}, "numeric parameters must be finite"),
        ({"max_health": math.nan}, "numeric parameters must be finite"),
    ],
)
def test_invalid_life_parameters_are_rejected(kwargs: dict[str, object], message: str) -> None:
    """Every life parameter is validated, with a message naming the rule."""
    with pytest.raises(ValueError, match=f"^{message}$"):
        EngineConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.req("REQ-SIM-012")
@pytest.mark.parametrize(
    "kwargs",
    [
        {"home_sleep_multiplier": 1.0},
        {"max_health": 0.5},
        {"adult_age_days": 1, "old_age_days": 1},
        {"gestation_days": 1},
        {"couple_proposal_ttl_ticks": 1},
        {"sexes": ("only",), "bearing_sex": "only"},
        {"old_age_days": 120, "adult_age_days": 120},
        {"old_age_death_chance": 0.0},
        {"old_age_death_chance": 1.0},
        {"old_age_death_growth": 1.0},
        {"birth_interval_days": 0},
        {"conception_chance_per_day": 0.0},
        {"conception_chance_per_day": 1.0},
        {"birth_food_per_capita": 0.0},
        {"model_rule": "fixed", "adult_model": "m"},
        {"childhood_memory_limit": 0},
        {
            "health_regen_per_hour": 0.0,
            "sleep_relief_per_hour": 0.0,
            "shelter_relief_per_hour": 0.0,
        },
    ],
)
def test_life_parameter_boundaries_are_accepted(kwargs: dict[str, object]) -> None:
    """The inclusive ends of each range are valid."""
    EngineConfig(**kwargs)  # type: ignore[arg-type]


@pytest.mark.req("REQ-SIM-012")
def test_several_broken_rules_are_all_reported() -> None:
    """One message per broken rule, joined in rule order."""
    with pytest.raises(ValueError) as error:
        EngineConfig(max_health=0.0, gestation_days=0)
    assert str(error.value) == "max_health must be positive; gestation_days must be positive"
