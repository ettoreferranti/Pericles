import pytest

from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig


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
