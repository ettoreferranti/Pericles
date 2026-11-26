import math
from dataclasses import replace

import pytest

from pericles.llm.config import BACKEND_KINDS, BackendSpec, LLMConfig
from pericles.llm.types import ModelSpec, Sampling

OLLAMA = BackendSpec("ollama", 1, 300.0, url="http://localhost:11434")
QWEN = ModelSpec("local", "qwen3:latest", Sampling(0.7, 0.9, 512))


def config(**changes: object) -> LLMConfig:
    values: dict[str, object] = {
        "backends": {"local": OLLAMA},
        "models": {"qwen": QWEN},
        "assign": {"qwen": 1.0},
    }
    values.update(changes)
    return replace(LLMConfig(), **values)  # type: ignore[arg-type]


@pytest.mark.req("REQ-LLM-006")
def test_a_complete_config_is_valid_and_frozen() -> None:
    """AC1: backends, models with sampling, and an assignment split."""
    made = config()
    assert made.models["qwen"].sampling.temperature == 0.7
    assert BACKEND_KINDS == ("ollama", "mlx", "fake")
    with pytest.raises(TypeError):
        made.models["other"] = QWEN  # type: ignore[index]


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"mode": "fast"}, "mode must be one of"),
        ({"cache": "always"}, "cache must be one of"),
        ({"cache": "replay"}, "cache 'replay' needs cache_from"),
        ({"backoff_base_s": 0.0}, "backoff_base_s must be positive"),
        ({"backoff_factor": 0.5}, "backoff_factor must be at least 1"),
        ({"backoff_max_s": 0.5}, "backoff_max_s must be at least backoff_base_s"),
        ({"max_backend_failures": 0}, "max_backend_failures must be at least 1"),
        ({"temperature": -0.1}, "temperature must be finite and non-negative"),
        ({"temperature": math.nan}, "temperature must be finite and non-negative"),
        ({"top_p": 0.0}, "top_p must be in"),
        ({"top_p": 1.5}, "top_p must be in"),
        ({"max_tokens": 0}, "max_tokens must be at least 1"),
        ({"concurrency": 0}, "concurrency must be at least 1"),
        ({"timeout_s": 0.0}, "timeout_s must be positive"),
        (
            {"backends": {"local": BackendSpec("vllm", 1, 1.0)}},
            "backends.local.kind: must be one of",
        ),
        (
            {"backends": {"local": BackendSpec("ollama", 1, 1.0)}},
            "backends.local.url: an ollama backend needs a url",
        ),
        (
            {"backends": {"local": BackendSpec("fake", 0, 1.0)}},
            "backends.local.concurrency: must be at least 1",
        ),
        (
            {"backends": {"local": BackendSpec("fake", 1, 0.0)}},
            "backends.local.timeout_s: must be positive",
        ),
        (
            {"models": {"qwen": replace(QWEN, backend="cloud")}},
            "models.qwen.backend: unknown backend 'cloud'",
        ),
        (
            {"models": {"qwen": replace(QWEN, sampling=Sampling(0.7, 0.9, 0))}},
            "models.qwen.max_tokens: must be at least 1",
        ),
        (
            {"models": {"qwen": replace(QWEN, sampling=Sampling(-1.0, 0.9, 5))}},
            "models.qwen.temperature",
        ),
        ({"models": {"qwen": replace(QWEN, sampling=Sampling(0.5, 2.0, 5))}}, "models.qwen.top_p"),
        ({"assign": {"llama": 1.0}}, "assign.llama: unknown model"),
        ({"assign": {"qwen": 0.0}}, "assign.qwen: ratio must be finite and positive"),
        ({"assign": {"qwen": math.inf}}, "assign.qwen: ratio must be finite and positive"),
    ],
)
def test_invalid_configs_name_the_field(changes: dict[str, object], message: str) -> None:
    """AC1: every part of the model configuration is checked."""
    with pytest.raises(ValueError, match=message):
        config(**changes)


@pytest.mark.req("REQ-LLM-006")
def test_boundary_values_are_valid() -> None:
    """AC1: the limits themselves are allowed."""
    made = config(
        backoff_base_s=0.5,
        backoff_factor=1.0,
        backoff_max_s=0.5,
        max_backend_failures=1,
        top_p=1.0,
        max_tokens=1,
        concurrency=1,
        timeout_s=0.5,
        backends={"local": BackendSpec("fake", 1, 0.5)},
    )
    assert made.max_backend_failures == 1


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"cache": "replay"}, "cache 'replay' needs cache_from"),
        ({"backoff_base_s": 0.0}, "backoff_base_s must be positive"),
        ({"backoff_factor": 0.5}, "backoff_factor must be at least 1"),
        ({"backoff_max_s": 0.5}, "backoff_max_s must be at least backoff_base_s"),
        ({"max_backend_failures": 0}, "max_backend_failures must be at least 1"),
        ({"concurrency": 0}, "concurrency must be at least 1"),
        ({"timeout_s": 0.0}, "timeout_s must be positive"),
        ({"max_tokens": 0}, "max_tokens must be at least 1"),
        ({"top_p": 0.0}, "top_p must be in (0, 1]"),
    ],
)
def test_error_messages_are_exact(changes: dict[str, object], message: str) -> None:
    """AC1: the message is the bare field message, with no stray text."""
    with pytest.raises(ValueError) as caught:
        config(**changes)
    assert str(caught.value) == message
