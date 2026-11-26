"""The backend contract every model server implements (REQ-LLM-001; ADR-0017 §3)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pericles.llm.types import BackendCall, Completion


class BackendError(Exception):
    """A call failed for a reason that may pass: unreachable, timed out, server error."""


class LLMSetupError(Exception):
    """The LLM setup cannot work: a backend is unreachable at start or a model is missing."""


class Backend(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def concurrency(self) -> int: ...

    def describe(self) -> str: ...

    def check(self, models: Sequence[str]) -> None: ...

    def complete(self, call: BackendCall) -> Completion: ...
