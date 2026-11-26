"""MLX in-process backend, Apple Silicon only (REQ-LLM-003; ADR-0017 §3)."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pericles.llm.backend import BackendError, LLMSetupError
from pericles.llm.types import BackendCall, Completion, Sampling


class MLXRuntime(Protocol):
    def load(self, name: str) -> object: ...

    def chat_prompt(self, handle: object, messages: list[dict[str, str]]) -> str: ...

    def count(self, handle: object, text: str) -> int: ...

    def generate(self, handle: object, prompt: str, sampling: Sampling, seed: int) -> str: ...


def default_runtime() -> MLXRuntime:
    from pericles.llm.mlx_runtime import MlxLmRuntime

    return MlxLmRuntime()


def schema_instruction(schema: Mapping[str, Any]) -> str:
    return "Respond with only a JSON object that matches this JSON schema: " + json.dumps(
        dict(schema), sort_keys=True
    )


class MLXBackend:
    kind = "mlx"

    def __init__(self, concurrency: int = 1, runtime: MLXRuntime | None = None) -> None:
        self.concurrency = concurrency
        self._runtime = runtime
        self._handles: dict[str, object] = {}
        self._lock = threading.Lock()

    def describe(self) -> str:
        return "mlx (in-process)"

    def _ready(self) -> MLXRuntime:
        if self._runtime is None:
            try:
                self._runtime = default_runtime()
            except ImportError as error:
                raise LLMSetupError(
                    f"mlx: mlx-lm is not installed ({error}); run `uv sync --extra mlx` "
                    "on Apple Silicon"
                ) from None
        return self._runtime

    def _handle(self, name: str) -> object:
        if name not in self._handles:
            self._handles[name] = self._ready().load(name)
        return self._handles[name]

    def check(self, models: Sequence[str]) -> None:
        with self._lock:
            for name in models:
                try:
                    self._handle(name)
                except LLMSetupError:
                    raise
                except Exception as error:
                    raise LLMSetupError(f"mlx: cannot load model {name!r}: {error}") from None

    def complete(self, call: BackendCall) -> Completion:
        messages = [m.to_dict() for m in call.messages]
        if call.schema is not None:
            messages.append({"role": "system", "content": schema_instruction(call.schema)})
        with self._lock:  # MLX runs one generation at a time in-process
            try:
                runtime = self._ready()
                handle = self._handle(call.model)
                prompt = runtime.chat_prompt(handle, messages)
                text = runtime.generate(handle, prompt, call.sampling, call.seed)
                return Completion(text, runtime.count(handle, prompt), runtime.count(handle, text))
            except LLMSetupError:
                raise
            except Exception as error:
                raise BackendError(f"mlx: {error}") from None
