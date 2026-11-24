"""Settings files: every engine parameter, tweakable without code changes (ADR-0015 §11)."""

from __future__ import annotations

import dataclasses
import typing
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from pericles.agents.config import AgentConfig
from pericles.core.calendar import Calendar, Season
from pericles.core.config import EngineConfig
from pericles.core.content.loader import ContentError, read_yaml
from pericles.core.content.schema import ModifierDef
from pericles.core.modifiers import Modifier

SECTIONS = ("engine", "agents")


class SettingsError(ValueError):
    """A settings file is invalid; the message starts with the dotted field path."""


def _mapping(data: object, where: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise SettingsError(f"{where}: expected a mapping")
    return data


def _values(
    cls: type[Any], data: Mapping[str, Any], where: str, nested: set[str]
) -> dict[str, Any]:
    """Validate the scalar fields of a dataclass; `nested` fields are left to the caller."""
    hints = typing.get_type_hints(cls)
    fields = {f.name: f for f in dataclasses.fields(cls)}
    for key in sorted(data):
        if key not in fields:
            raise SettingsError(f"{where}.{key}: unknown setting")
    for name, f in fields.items():
        required = f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
        if required and name not in data:
            raise SettingsError(f"{where}.{name}: missing")
    values: dict[str, Any] = {}
    for key in sorted(data):
        if key in nested:
            continue
        raw = data[key]
        value = tuple(raw) if isinstance(raw, list) else raw
        try:
            values[key] = TypeAdapter(hints[key]).validate_python(value, strict=True)
        except ValidationError as error:
            raise SettingsError(f"{where}.{key}: {error.errors()[0]['msg']}") from None
    return values


def _season(data: object, where: str) -> Season:
    season = _mapping(data, where)
    values = _values(Season, season, where, nested={"modifiers"})
    raw = season.get("modifiers", [])
    if not isinstance(raw, list):
        raise SettingsError(f"{where}.modifiers: expected a list")
    try:
        defs = TypeAdapter(tuple[ModifierDef, ...]).validate_python(tuple(raw))
    except ValidationError as error:
        first = error.errors()[0]
        loc = ".".join(str(part) for part in first["loc"])
        raise SettingsError(f"{where}.modifiers.{loc}: {first['msg']}") from None
    source = f"season:{values['name']}"
    return Season(**values, modifiers=tuple(Modifier.from_def(d, source) for d in defs))


def _calendar(data: object, where: str) -> Calendar:
    calendar = _mapping(data, where)
    values = _values(Calendar, calendar, where, nested={"seasons"})
    raw = calendar["seasons"]
    if not isinstance(raw, list):
        raise SettingsError(f"{where}.seasons: expected a list")
    seasons = tuple(_season(s, f"{where}.seasons[{i}]") for i, s in enumerate(raw))
    try:
        return Calendar(**values, seasons=seasons)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def engine_config_from_mapping(data: object, where: str = "engine") -> EngineConfig:
    engine = _mapping(data, where)
    values = _values(EngineConfig, engine, where, nested={"calendar"})
    if "calendar" in engine:
        values["calendar"] = _calendar(engine["calendar"], f"{where}.calendar")
    try:
        return EngineConfig(**values)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def agent_config_from_mapping(data: object, where: str = "agents") -> AgentConfig:
    agents = _mapping(data, where)
    values = _values(AgentConfig, agents, where, nested=set())
    try:
        return AgentConfig(**values)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = read_yaml(path)
    except ContentError as error:
        raise SettingsError(str(error)) from None
    for key in sorted(raw):
        if key not in SECTIONS:
            raise SettingsError(f"{key}: unknown section")
    return raw


def load_settings(path: Path) -> EngineConfig:
    return engine_config_from_mapping(_read(path).get("engine", {}))


def load_agent_settings(path: Path) -> AgentConfig:
    return agent_config_from_mapping(_read(path).get("agents", {}))
