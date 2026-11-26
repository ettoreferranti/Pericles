import json
from typing import Any

import pytest

from pericles.llm.backend import Backend, BackendError, LLMSetupError
from pericles.llm.mlx import MLXBackend, schema_instruction
from pericles.llm.types import BackendCall, Message, Sampling

SAMPLING = Sampling(0.3, 0.8, 32)


class FakeRuntime:
    def __init__(self, fail_load: str | None = None, fail_generate: bool = False) -> None:
        self.loaded: list[str] = []
        self.prompts: list[list[dict[str, str]]] = []
        self.generated: list[tuple[str, Sampling, int]] = []
        self.fail_load = fail_load
        self.fail_generate = fail_generate

    def load(self, name: str) -> object:
        if name == self.fail_load:
            raise FileNotFoundError(f"no such model {name}")
        self.loaded.append(name)
        return {"name": name}

    def chat_prompt(self, handle: object, messages: list[dict[str, str]]) -> str:
        self.prompts.append(messages)
        return "|".join(m["content"] for m in messages)

    def count(self, handle: object, text: str) -> int:
        return len(text)

    def generate(self, handle: object, prompt: str, sampling: Sampling, seed: int) -> str:
        if self.fail_generate:
            raise RuntimeError("metal out of memory")
        self.generated.append((prompt, sampling, seed))
        return '{"ok": true}'


def call(schema: dict[str, Any] | None = None) -> BackendCall:
    return BackendCall("mlx-community/tiny", (Message("user", "hi"),), SAMPLING, 9, schema)


@pytest.mark.req("REQ-LLM-001")
def test_mlx_implements_the_interface() -> None:
    """AC2: MLXBackend satisfies the Backend protocol."""
    backend: Backend = MLXBackend(runtime=FakeRuntime())
    assert (backend.kind, backend.concurrency, backend.describe()) == ("mlx", 1, "mlx (in-process)")


@pytest.mark.req("REQ-LLM-003")
def test_a_model_is_loaded_once_by_name_or_path() -> None:
    """AC1: loads an MLX model by name or path, and keeps it loaded."""
    runtime = FakeRuntime()
    backend = MLXBackend(runtime=runtime)
    backend.check(["mlx-community/tiny", "/models/local"])
    backend.complete(call())
    assert runtime.loaded == ["mlx-community/tiny", "/models/local"]


@pytest.mark.req("REQ-LLM-003")
def test_complete_passes_sampling_seed_and_counts_tokens() -> None:
    """AC1: sampling and seed reach the runtime; tokens are counted with its tokenizer."""
    runtime = FakeRuntime()
    completion = MLXBackend(runtime=runtime).complete(call())
    assert completion.text == '{"ok": true}'
    assert runtime.generated == [("hi", SAMPLING, 9)]
    assert (completion.tokens_in, completion.tokens_out) == (2, len('{"ok": true}'))


@pytest.mark.req("REQ-LLM-003")
def test_the_schema_goes_into_the_prompt() -> None:
    """AC1: without constrained decoding, the JSON schema is stated in a system message."""
    runtime = FakeRuntime()
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    MLXBackend(runtime=runtime).complete(call(schema))
    sent = runtime.prompts[0]
    assert sent[0] == {"role": "user", "content": "hi"}
    assert sent[1] == {"role": "system", "content": schema_instruction(schema)}
    assert json.dumps(schema, sort_keys=True) in schema_instruction(schema)


@pytest.mark.req("REQ-LLM-003")
def test_load_failures_are_setup_errors() -> None:
    """AC1: a model that cannot be loaded fails fast, naming it."""
    with pytest.raises(LLMSetupError, match="mlx: cannot load model 'gone'"):
        MLXBackend(runtime=FakeRuntime(fail_load="gone")).check(["gone"])


@pytest.mark.req("REQ-LLM-003")
def test_generation_failures_are_backend_errors() -> None:
    """AC1: a runtime failure mid-run is a BackendError, so the gateway backs off."""
    with pytest.raises(BackendError, match="mlx: metal out of memory"):
        MLXBackend(runtime=FakeRuntime(fail_generate=True)).complete(call())


@pytest.mark.req("REQ-LLM-003")
def test_a_missing_mlx_install_says_how_to_install_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: without mlx-lm, check() explains `uv sync --extra mlx`."""
    import pericles.llm.mlx as module

    def missing() -> object:
        raise ImportError("No module named 'mlx_lm'")

    monkeypatch.setattr(module, "default_runtime", missing)
    with pytest.raises(LLMSetupError, match="uv sync --extra mlx"):
        MLXBackend().check(["mlx-community/tiny"])
