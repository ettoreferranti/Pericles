"""The playable defaults, read from the packaged settings file (ADR-0014 §10, ADR-0015 §11)."""

from __future__ import annotations

import dataclasses
from importlib.resources import files
from pathlib import Path
from typing import Any

from pericles.core.config import EngineConfig
from pericles.experiment.settings import load_settings

DEFAULT_SETTINGS = Path(str(files("pericles.experiment").joinpath("default_settings.yaml")))


def default_config(**overrides: Any) -> EngineConfig:
    return dataclasses.replace(load_settings(DEFAULT_SETTINGS), **overrides)


DEFAULT_CALENDAR = default_config().calendar
