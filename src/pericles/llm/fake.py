"""A scripted backend for tests and CI (REQ-LLM-004; ADR-0017 §3)."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pericles.llm.backend import BackendError, LLMSetupError
from pericles.llm.types import BackendCall, Completion


@dataclass(frozen=True)
class FakeError:
    message: str


Reply = str | FakeError
RULE_KEYS = ("replies", "kind", "villager", "pattern", "delay_s")


@dataclass(frozen=True)
class FakeRule:
    replies: tuple[Reply, ...]
    kind: str | None = None
    villager: str | None = None
    pattern: str | None = None
    delay_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.replies:
            raise ValueError("a fake rule needs at least one reply")
        if self.delay_s < 0:
            raise ValueError("delay_s must be non-negative")
        if self.pattern is not None:
            re.compile(self.pattern)

    def matches(self, call: BackendCall) -> bool:
        if self.kind is not None and call.kind != self.kind:
            return False
        if self.villager is not None and call.villager != self.villager:
            return False
        if self.pattern is None:
            return True
        last = call.messages[-1].content if call.messages else ""
        return re.search(self.pattern, last) is not None


class FakeBackend:
    kind = "fake"

    def __init__(
        self,
        rules: Sequence[FakeRule] = (),
        *,
        models: Sequence[str] | None = None,
        concurrency: int = 1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rules = tuple(rules)
        self.models = None if models is None else tuple(models)
        self.concurrency = concurrency
        self.calls: list[BackendCall] = []
        self._sleep = sleep
        self._served = [0] * len(self.rules)
        self._lock = threading.Lock()

    def describe(self) -> str:
        return "fake backend"

    def check(self, models: Sequence[str]) -> None:
        if self.models is None:
            return
        missing = [m for m in models if m not in self.models]
        if missing:
            raise LLMSetupError(f"fake backend: model(s) not available: {', '.join(missing)}")

    def complete(self, call: BackendCall) -> Completion:
        with self._lock:
            self.calls.append(call)
            index = next((i for i, r in enumerate(self.rules) if r.matches(call)), None)
            if index is None:
                raise BackendError(
                    f"fake backend: no scripted reply for kind {call.kind!r}, "
                    f"villager {call.villager!r}"
                )
            rule = self.rules[index]
            reply = rule.replies[min(self._served[index], len(rule.replies) - 1)]
            self._served[index] += 1
        if rule.delay_s:
            self._sleep(rule.delay_s)
        if isinstance(reply, FakeError):
            raise BackendError(f"fake backend: {reply.message}")
        tokens_in = sum(len(m.content.split()) for m in call.messages)
        return Completion(reply, tokens_in, len(reply.split()))

    @classmethod
    def from_file(cls, path: Path, *, concurrency: int = 1) -> FakeBackend:
        """Rules from YAML: a list of {replies, kind?, villager?, pattern?, delay_s?}.

        A reply is text or {error: message}."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise LLMSetupError(f"{path}: {error}") from None
        if not isinstance(raw, list):
            raise LLMSetupError(f"{path}: expected a list of rules")
        rules = [_rule(entry, f"{path}[{i}]") for i, entry in enumerate(raw)]
        return cls(rules, concurrency=concurrency)


def _reply(value: object, where: str) -> Reply:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and list(value) == ["error"] and isinstance(value["error"], str):
        return FakeError(value["error"])
    raise LLMSetupError(f"{where}: a reply is text or {{error: message}}")


def _rule(entry: object, where: str) -> FakeRule:
    if not isinstance(entry, dict):
        raise LLMSetupError(f"{where}: expected a mapping")
    unknown = sorted(str(k) for k in entry if k not in RULE_KEYS)
    if unknown:
        raise LLMSetupError(f"{where}.{unknown[0]}: unknown key")
    replies = entry.get("replies")
    if not isinstance(replies, list) or not replies:
        raise LLMSetupError(f"{where}.replies: expected a non-empty list")
    texts: dict[str, Any] = {}
    for key in ("kind", "villager", "pattern"):
        value = entry.get(key)
        if value is not None and not isinstance(value, str):
            raise LLMSetupError(f"{where}.{key}: expected text")
        texts[key] = value
    delay = entry.get("delay_s", 0.0)
    if isinstance(delay, bool) or not isinstance(delay, int | float):
        raise LLMSetupError(f"{where}.delay_s: expected a number")
    parsed = tuple(_reply(r, f"{where}.replies[{j}]") for j, r in enumerate(replies))
    try:
        return FakeRule(parsed, delay_s=float(delay), **texts)
    except (ValueError, re.error) as error:
        raise LLMSetupError(f"{where}: {error}") from None
