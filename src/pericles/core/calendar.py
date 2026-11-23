"""In-game time: ticks, days, day/night and seasons (REQ-SIM-002 AC3, REQ-SIM-003 AC1)."""

from __future__ import annotations

from dataclasses import dataclass

from pericles.core.modifiers import Modifier


@dataclass(frozen=True)
class Season:
    name: str
    days: int
    blocked_tags: tuple[str, ...] = ()
    modifiers: tuple[Modifier, ...] = ()


@dataclass(frozen=True)
class GameTime:
    tick: int
    day: int
    minute_of_day: int
    year: int
    season: str
    day_of_season: int
    is_daytime: bool


@dataclass(frozen=True)
class Calendar:
    seasons: tuple[Season, ...]
    tick_minutes: int = 1
    day_minutes: int = 1440
    sunrise_minute: int = 360
    sunset_minute: int = 1200

    def __post_init__(self) -> None:
        if not self.seasons:
            raise ValueError("calendar needs at least one season")
        if any(season.days <= 0 for season in self.seasons):
            raise ValueError("every season must last at least one day")
        if self.tick_minutes <= 0 or self.day_minutes % self.tick_minutes != 0:
            raise ValueError("tick_minutes must be positive and divide day_minutes")
        if not 0 <= self.sunrise_minute < self.sunset_minute <= self.day_minutes:
            raise ValueError("need 0 <= sunrise_minute < sunset_minute <= day_minutes")

    @property
    def ticks_per_day(self) -> int:
        return self.day_minutes // self.tick_minutes

    @property
    def days_per_year(self) -> int:
        return sum(season.days for season in self.seasons)

    def _locate(self, tick: int) -> tuple[int, int, int, Season, int]:
        """(day, minute_of_day, year, season, day_of_season) for a tick."""
        if tick < 0:
            raise ValueError("tick must be non-negative")
        day, minute = divmod(tick * self.tick_minutes, self.day_minutes)
        year, day_of_year = divmod(day, self.days_per_year)
        for season in self.seasons:
            if day_of_year < season.days:
                return day, minute, year, season, day_of_year
            day_of_year -= season.days
        raise AssertionError("unreachable")  # pragma: no mutate - day_of_year < days_per_year

    def time_of(self, tick: int) -> GameTime:
        day, minute, year, season, day_of_season = self._locate(tick)
        return GameTime(
            tick=tick,
            day=day,
            minute_of_day=minute,
            year=year,
            season=season.name,
            day_of_season=day_of_season,
            is_daytime=self.sunrise_minute <= minute < self.sunset_minute,
        )

    def season_at(self, tick: int) -> Season:
        return self._locate(tick)[3]
