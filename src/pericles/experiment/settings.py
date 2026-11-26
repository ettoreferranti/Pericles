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
from pericles.llm.config import BackendSpec, LLMConfig
from pericles.llm.types import ModelSpec, Sampling

SECTIONS = ("engine", "agents", "llm")


class SettingsError(ValueError):
    """A settings file is invalid; the message starts with the dotted field path."""


def as_mapping(data: object, where: str) -> Mapping[str, Any]:
    if not isinstance(data, Mapping):
        raise SettingsError(f"{where}: expected a mapping")
    for key in data:
        if not isinstance(key, str):
            raise SettingsError(f"{where}: setting names must be strings, got {key!r}")
    return data


def values_for(
    cls: type[Any], data: Mapping[str, Any], where: str, nested: set[str]
) -> dict[str, Any]:
    """Validate the scalar fields of a dataclass; `nested` fields are left to the caller.

    Fields with `init=False` are derived (such as `Calendar`'s season table), not settings."""
    as_mapping(data, where)
    hints = typing.get_type_hints(cls)
    fields = {f.name: f for f in dataclasses.fields(cls) if f.init}
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
    season = as_mapping(data, where)
    values = values_for(Season, season, where, nested={"modifiers"})
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
    calendar = as_mapping(data, where)
    values = values_for(Calendar, calendar, where, nested={"seasons"})
    raw = calendar["seasons"]
    if not isinstance(raw, list):
        raise SettingsError(f"{where}.seasons: expected a list")
    seasons = tuple(_season(s, f"{where}.seasons[{i}]") for i, s in enumerate(raw))
    try:
        return Calendar(**values, seasons=seasons)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def engine_config_from_mapping(data: object, where: str = "engine") -> EngineConfig:
    engine = as_mapping(data, where)
    values = values_for(EngineConfig, engine, where, nested={"calendar"})
    if "calendar" in engine:
        values["calendar"] = _calendar(engine["calendar"], f"{where}.calendar")
    try:
        return EngineConfig(**values)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def agent_config_from_mapping(data: object, where: str = "agents") -> AgentConfig:
    agents = as_mapping(data, where)
    values = values_for(AgentConfig, agents, where, nested=set())
    try:
        return AgentConfig(**values)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def _read(path: Path) -> dict[str, Any]:
    try:
        raw = read_yaml(path)
    except ContentError as error:
        raise SettingsError(str(error)) from None
    as_mapping(raw, "settings")
    for key in sorted(raw):
        if key not in SECTIONS:
            raise SettingsError(f"{key}: unknown section")
    return raw


def load_settings(path: Path) -> EngineConfig:
    return engine_config_from_mapping(_read(path).get("engine", {}))


def load_agent_settings(path: Path) -> AgentConfig:
    return agent_config_from_mapping(_read(path).get("agents", {}))


LLM_NESTED = {"backends", "models", "assign"}


@dataclasses.dataclass(frozen=True)
class _BackendEntry:
    kind: str
    concurrency: int | None = None
    timeout_s: float | None = None
    url: str | None = None
    replies: str | None = None


@dataclasses.dataclass(frozen=True)
class _ModelEntry:
    backend: str
    name: str
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None


def _or(value: Any, default: Any) -> Any:
    return default if value is None else value


def llm_config_from_mapping(data: object, where: str = "llm") -> LLMConfig:
    llm = as_mapping(data, where)
    values = values_for(LLMConfig, llm, where, nested=LLM_NESTED)
    try:
        base = LLMConfig(**values)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None
    backends: dict[str, BackendSpec] = {}
    raw_backends = as_mapping(llm.get("backends", {}), f"{where}.backends")
    for key in sorted(raw_backends):
        at = f"{where}.backends.{key}"
        b = _BackendEntry(**values_for(_BackendEntry, as_mapping(raw_backends[key], at), at, set()))
        url = _or(b.url, base.ollama_url if b.kind == "ollama" else None)
        backends[key] = BackendSpec(
            b.kind,
            _or(b.concurrency, base.concurrency),
            _or(b.timeout_s, base.timeout_s),
            url,
            b.replies,
        )
    models: dict[str, ModelSpec] = {}
    raw_models = as_mapping(llm.get("models", {}), f"{where}.models")
    for key in sorted(raw_models):
        at = f"{where}.models.{key}"
        m = _ModelEntry(**values_for(_ModelEntry, as_mapping(raw_models[key], at), at, set()))
        sampling = Sampling(
            float(_or(m.temperature, base.temperature)),
            float(_or(m.top_p, base.top_p)),
            int(_or(m.max_tokens, base.max_tokens)),
        )
        models[key] = ModelSpec(m.backend, m.name, sampling)
    assign: dict[str, float] = {}
    raw_assign = as_mapping(llm.get("assign", {}), f"{where}.assign")
    for key in sorted(raw_assign):
        ratio = raw_assign[key]
        if isinstance(ratio, bool) or not isinstance(ratio, int | float):
            raise SettingsError(f"{where}.assign.{key}: expected a number")
        assign[key] = float(ratio)
    try:
        return dataclasses.replace(base, backends=backends, models=models, assign=assign)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def llm_config_to_mapping(config: LLMConfig) -> dict[str, Any]:
    """Every value of `config`, in the shape `llm_config_from_mapping` reads."""
    out: dict[str, Any] = {
        f.name: getattr(config, f.name)
        for f in dataclasses.fields(LLMConfig)
        if f.name not in LLM_NESTED
    }
    out["backends"] = {k: dataclasses.asdict(v) for k, v in sorted(config.backends.items())}
    out["models"] = {
        k: {"backend": m.backend, "name": m.name, **m.sampling.to_dict()}
        for k, m in sorted(config.models.items())
    }
    out["assign"] = dict(sorted(config.assign.items()))
    return out


def load_llm_settings(path: Path) -> LLMConfig:
    return llm_config_from_mapping(_read(path).get("llm", {}))
