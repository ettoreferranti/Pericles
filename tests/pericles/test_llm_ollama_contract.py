"""Contract tests against the local Ollama. Run with `uv run pytest -m slow`."""

import os

import pytest
from pydantic import BaseModel, ConfigDict

from pericles.llm.backend import LLMSetupError
from pericles.llm.ollama import OllamaBackend
from pericles.llm.types import BackendCall, Message, Sampling
from pericles.llm.validate import schema_of, validate

pytestmark = pytest.mark.slow
URL = os.environ.get("PERICLES_OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("PERICLES_OLLAMA_MODEL", "llama3.1:8b")


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colour: str
    count: int


@pytest.mark.req("REQ-LLM-002")
def test_the_configured_model_is_listed() -> None:
    """AC1/AC3: the live server lists the contract-test model."""
    OllamaBackend(URL, 30.0, 1).check([MODEL])


@pytest.mark.req("REQ-LLM-002")
def test_a_missing_model_fails_fast() -> None:
    """AC1/AC3: a model that is not pulled is named."""
    with pytest.raises(LLMSetupError, match="pericles-no-such-model"):
        OllamaBackend(URL, 30.0, 1).check(["pericles-no-such-model"])


@pytest.mark.req("REQ-LLM-002")
def test_schema_constrained_output_validates() -> None:
    """AC2/AC3: with `format`, the live model returns JSON matching the schema."""
    call = BackendCall(
        MODEL,
        (Message("user", "Name a colour and a small number, as JSON."),),
        Sampling(0.2, 0.9, 64),
        7,
        schema_of(Answer),
    )
    completion = OllamaBackend(URL, 300.0, 1).complete(call)
    value, error = validate(Answer, completion.text)
    assert error is None and isinstance(value, Answer)
    assert completion.tokens_in > 0 and completion.tokens_out > 0
