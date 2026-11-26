"""Gateway value types (ADR-0017 §2)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Sampling:
    temperature: float
    top_p: float
    max_tokens: int

    def to_dict(self) -> dict[str, float | int]:
        return {"temperature": self.temperature, "top_p": self.top_p, "max_tokens": self.max_tokens}


@dataclass(frozen=True)
class ModelSpec:
    """A logical model: which backend serves it, under which name, with which sampling."""

    backend: str
    name: str
    sampling: Sampling


@dataclass(frozen=True)
class BackendCall:
    model: str
    messages: tuple[Message, ...]
    sampling: Sampling
    seed: int
    schema: Mapping[str, Any] | None = None
    kind: str = ""
    villager: str = ""


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class Request:
    """What a mind asks for; `model` is a key of `llm.models`."""

    kind: str
    villager: str
    tick: int
    model: str
    messages: tuple[Message, ...]
    seed: int
    output: type[BaseModel] | None = None
    attempt: int = 0
    template: str | None = None


@dataclass(frozen=True)
class Result:
    request: Request
    text: str
    value: BaseModel | None
    error: str | None
    backend_error: str | None
    tokens_in: int
    tokens_out: int
    latency_s: float
    cached: bool

    @property
    def valid(self) -> bool:
        return self.error is None and self.backend_error is None
