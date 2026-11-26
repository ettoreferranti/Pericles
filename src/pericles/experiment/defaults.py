"""The playable defaults, read from the packaged settings file (ADR-0014 §10, ADR-0015 §11)."""

from __future__ import annotations

import dataclasses
from importlib.resources import files
from pathlib import Path
from typing import Any

from pericles.agents.config import AgentConfig
from pericles.core.config import EngineConfig
from pericles.core.content.loader import read_yaml
from pericles.experiment.settings import load_agent_settings, load_llm_settings, load_settings
from pericles.llm.config import LLMConfig

DEFAULT_SETTINGS = Path(str(files("pericles.experiment").joinpath("default_settings.yaml")))


def default_config(**overrides: Any) -> EngineConfig:
    return dataclasses.replace(load_settings(DEFAULT_SETTINGS), **overrides)


def default_agent_config(**overrides: Any) -> AgentConfig:
    return dataclasses.replace(load_agent_settings(DEFAULT_SETTINGS), **overrides)


def default_llm_config(**overrides: Any) -> LLMConfig:
    return dataclasses.replace(load_llm_settings(DEFAULT_SETTINGS), **overrides)


def default_settings_mapping() -> dict[str, Any]:
    """The packaged settings file as raw YAML data (ADR-0016 §5)."""
    return read_yaml(DEFAULT_SETTINGS)


DEFAULT_CALENDAR = default_config().calendar
