import re

import pytest

from pericles.core.calendar import Calendar, GameTime, Season

SEASONS = (Season("spring", 2), Season("summer", 2), Season("autumn", 1), Season("winter", 3))


@pytest.mark.req("REQ-SIM-002")
def test_each_tick_advances_time_by_tick_minutes() -> None:
    """AC3: one tick = tick_minutes of in-game time."""
    calendar = Calendar(seasons=SEASONS, tick_minutes=10)
    assert calendar.ticks_per_day == 144
    assert calendar.time_of(1).minute_of_day == 10
    assert calendar.time_of(7).minute_of_day == 70
    assert calendar.time_of(144) == GameTime(
        tick=144, day=1, minute_of_day=0, year=0, season="spring", day_of_season=1, is_daytime=False
    )


@pytest.mark.req("REQ-SIM-003")
@pytest.mark.parametrize(
    ("day", "season", "day_of_season", "year"),
    [
        (0, "spring", 0, 0),
        (1, "spring", 1, 0),
        (2, "summer", 0, 0),
        (4, "autumn", 0, 0),
        (5, "winter", 0, 0),
        (7, "winter", 2, 0),
        (8, "spring", 0, 1),
        (13, "winter", 0, 1),
    ],
)
def test_seasons_cycle(day: int, season: str, day_of_season: int, year: int) -> None:
    """AC1: the season can be derived from the tick."""
    calendar = Calendar(seasons=SEASONS)
    time = calendar.time_of(day * calendar.ticks_per_day + 5)
    assert (time.day, time.season, time.day_of_season, time.year) == (
        day,
        season,
        day_of_season,
        year,
    )
    assert calendar.days_per_year == 8


@pytest.mark.req("REQ-SIM-003")
@pytest.mark.parametrize(
    ("minute", "daytime"), [(0, False), (359, False), (360, True), (1199, True), (1200, False)]
)
def test_day_and_night(minute: int, daytime: bool) -> None:
    """AC1: day length is a parameter and time of day is derivable."""
    assert Calendar(seasons=SEASONS).time_of(minute).is_daytime is daytime


@pytest.mark.req("REQ-SIM-003")
def test_custom_day_length() -> None:
    calendar = Calendar(
        seasons=SEASONS, tick_minutes=5, day_minutes=100, sunrise_minute=20, sunset_minute=80
    )
    assert calendar.ticks_per_day == 20
    assert calendar.time_of(21).day == 1
    assert calendar.time_of(21).minute_of_day == 5


@pytest.mark.req("REQ-SIM-003")
@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"seasons": ()}, "calendar needs at least one season"),
        ({"seasons": (Season("x", 0),)}, "every season must last at least one day"),
        (
            {"seasons": SEASONS, "tick_minutes": 0},
            "tick_minutes must be positive and divide day_minutes",
        ),
        (
            {"seasons": SEASONS, "tick_minutes": 7},
            "tick_minutes must be positive and divide day_minutes",
        ),
        (
            {"seasons": SEASONS, "sunrise_minute": 1300},
            "need 0 <= sunrise_minute < sunset_minute <= day_minutes",
        ),
        (
            {"seasons": SEASONS, "sunrise_minute": -1},
            "need 0 <= sunrise_minute < sunset_minute <= day_minutes",
        ),
        (
            {"seasons": SEASONS, "sunset_minute": 1441},
            "need 0 <= sunrise_minute < sunset_minute <= day_minutes",
        ),
        (
            {"seasons": SEASONS, "sunrise_minute": 500, "sunset_minute": 500},
            "need 0 <= sunrise_minute < sunset_minute <= day_minutes",
        ),
    ],
)
def test_invalid_calendars_are_rejected(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        Calendar(**kwargs)  # type: ignore[arg-type]


@pytest.mark.req("REQ-SIM-003")
def test_sun_bounds_may_touch_day_edges() -> None:
    calendar = Calendar(seasons=SEASONS, sunrise_minute=0, sunset_minute=1440)
    assert calendar.time_of(0).is_daytime
    assert calendar.time_of(1439).is_daytime


@pytest.mark.req("REQ-SIM-003")
def test_negative_tick_is_rejected() -> None:
    with pytest.raises(ValueError, match=r"^tick must be non-negative$"):
        Calendar(seasons=SEASONS).time_of(-1)


@pytest.mark.req("REQ-SIM-003")
def test_season_at_returns_the_season_with_its_blocked_tags() -> None:
    """AC2: seasons carry the action tags they block, looked up by tick."""
    winter = Season("winter", 3, blocked_tags=("sowing",))
    calendar = Calendar(seasons=(Season("spring", 2), winter))
    per_day = calendar.ticks_per_day
    assert calendar.season_at(0) == Season("spring", 2)
    assert calendar.season_at(2 * per_day) is winter
    assert calendar.season_at(5 * per_day - 1) is winter
    assert calendar.season_at(5 * per_day) == Season("spring", 2)
    assert Season("x", 1).blocked_tags == ()
    with pytest.raises(ValueError, match=r"^tick must be non-negative$"):
        calendar.season_at(-1)
