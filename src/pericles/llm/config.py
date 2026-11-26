"""Gateway configuration: modes, backends, models, assignment (ADR-0017 §9)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pericles.llm.cache import CACHE_MODES
from pericles.llm.gateway import MODES
from pericles.llm.types import ModelSpec, Sampling

BACKEND_KINDS = ("ollama", "mlx", "fake")


@dataclass(frozen=True)
class BackendSpec:
    kind: str
    concurrency: int
    timeout_s: float
    url: str | None = None
    replies: str | None = None


def _sampling_errors(where: str, sep: str, s: Sampling) -> list[str]:
    errors = []
    if not (math.isfinite(s.temperature) and s.temperature >= 0):
        errors.append(f"{where}temperature{sep}must be finite and non-negative")
    if not 0 < s.top_p <= 1:
        errors.append(f"{where}top_p{sep}must be in (0, 1]")
    if s.max_tokens < 1:
        errors.append(f"{where}max_tokens{sep}must be at least 1")
    return errors


@dataclass(frozen=True)
class LLMConfig:
    mode: str = "wait"
    cache: str = "record"
    cache_from: str | None = None
    backoff_base_s: float = 2.0
    backoff_factor: float = 2.0
    backoff_max_s: float = 60.0
    max_backend_failures: int = 5
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 512
    concurrency: int = 1
    timeout_s: float = 300.0
    ollama_url: str = "http://localhost:11434"
    backends: Mapping[str, BackendSpec] = field(default_factory=dict)
    models: Mapping[str, ModelSpec] = field(default_factory=dict)
    assign: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("backends", "models", "assign"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        errors = self._errors()
        if errors:
            raise ValueError(errors[0])

    def _errors(self) -> list[str]:
        errors: list[str] = []
        if self.mode not in MODES:
            errors.append(f"mode must be one of {MODES}")
        if self.cache not in CACHE_MODES:
            errors.append(f"cache must be one of {CACHE_MODES}")
        if self.cache == "replay" and self.cache_from is None:
            errors.append("cache 'replay' needs cache_from")
        if not (math.isfinite(self.backoff_base_s) and self.backoff_base_s > 0):
            errors.append("backoff_base_s must be positive")
        if not (math.isfinite(self.backoff_factor) and self.backoff_factor >= 1):
            errors.append("backoff_factor must be at least 1")
        if not (math.isfinite(self.backoff_max_s) and self.backoff_max_s >= self.backoff_base_s):
            errors.append("backoff_max_s must be at least backoff_base_s")
        if self.max_backend_failures < 1:
            errors.append("max_backend_failures must be at least 1")
        errors += _sampling_errors("", " ", Sampling(self.temperature, self.top_p, self.max_tokens))
        if self.concurrency < 1:
            errors.append("concurrency must be at least 1")
        if not (math.isfinite(self.timeout_s) and self.timeout_s > 0):
            errors.append("timeout_s must be positive")
        for key in sorted(self.backends):
            b = self.backends[key]
            if b.kind not in BACKEND_KINDS:
                errors.append(f"backends.{key}.kind: must be one of {BACKEND_KINDS}")
            if b.kind == "ollama" and not b.url:
                errors.append(f"backends.{key}.url: an ollama backend needs a url")
            if b.concurrency < 1:
                errors.append(f"backends.{key}.concurrency: must be at least 1")
            if not (math.isfinite(b.timeout_s) and b.timeout_s > 0):
                errors.append(f"backends.{key}.timeout_s: must be positive")
        for key in sorted(self.models):
            m = self.models[key]
            if m.backend not in self.backends:
                errors.append(f"models.{key}.backend: unknown backend {m.backend!r}")
            errors += _sampling_errors(f"models.{key}.", ": ", m.sampling)
        for key in sorted(self.assign):
            if key not in self.models:
                errors.append(f"assign.{key}: unknown model")
            elif not (math.isfinite(self.assign[key]) and self.assign[key] > 0):
                errors.append(f"assign.{key}: ratio must be finite and positive")
        return errors
