"""Contract test against a real MLX model. Run with `uv run pytest -m slow`."""

import os

import pytest
from pydantic import BaseModel, ConfigDict

pytestmark = pytest.mark.slow
pytest.importorskip("mlx_lm")

from pericles.llm.mlx import MLXBackend  # noqa: E402
from pericles.llm.types import BackendCall, Message, Sampling  # noqa: E402
from pericles.llm.validate import schema_of, validate  # noqa: E402

MODEL = os.environ.get("PERICLES_MLX_MODEL", "mlx-community/Qwen2.5-0.5B-Instruct-4bit")


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colour: str


@pytest.mark.req("REQ-LLM-003")
def test_a_real_model_loads_and_answers_in_json() -> None:
    """AC1: loads by name, implements the interface, output passes JSON validation."""
    backend = MLXBackend()
    backend.check([MODEL])
    completion = backend.complete(
        BackendCall(
            MODEL,
            (Message("user", 'Reply with {"colour": "<a colour>"} and nothing else.'),),
            Sampling(0.0, 1.0, 32),
            3,
            schema_of(Answer),
        )
    )
    value, error = validate(Answer, completion.text)
    assert error is None and isinstance(value, Answer), completion.text
    assert completion.tokens_in > 0 and completion.tokens_out > 0
