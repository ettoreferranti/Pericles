"""The playable defaults: a four-season year whose winter blocks sowing (ADR-0014 §10)."""

from __future__ import annotations

from typing import Any

from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig

DEFAULT_CALENDAR = Calendar(
    seasons=(
        Season("spring", 10),
        Season("summer", 10),
        Season("autumn", 10),
        Season("winter", 10, blocked_tags=("sowing",)),
    )
)


def default_config(**overrides: Any) -> EngineConfig:
    return EngineConfig(calendar=DEFAULT_CALENDAR, **overrides)
