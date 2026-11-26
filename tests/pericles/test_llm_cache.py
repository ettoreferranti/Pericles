from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from pericles.llm.cache import CACHE_MODES, CacheMiss, ResponseCache, cache_key
from pericles.llm.types import BackendCall, Completion, Message, Sampling
from pericles.llm.validate import schema_of, unfenced, validate


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str
    steps: list[str]


SAMPLING = Sampling(0.7, 0.9, 256)


def call(**changes: object) -> BackendCall:
    base: dict[str, object] = {
        "model": "qwen3:latest",
        "messages": (Message("user", "plan your day"),),
        "sampling": SAMPLING,
        "seed": 11,
        "schema": schema_of(Plan),
        "kind": "plan",
        "villager": "ada",
    }
    base.update(changes)
    return BackendCall(**base)  # type: ignore[arg-type]


@pytest.mark.req("REQ-LLM-005")
def test_the_key_hashes_model_sampling_prompt_schema_and_seed() -> None:
    """AC1: changing any part of the key changes the key; kind and villager do not count."""
    key = cache_key("ollama:qwen3:latest", call())
    assert len(key) == 64
    assert key == cache_key("ollama:qwen3:latest", call(kind="vote", villager="bram"))
    assert key != cache_key("mlx:qwen3:latest", call())
    assert key != cache_key("ollama:qwen3:latest", call(sampling=Sampling(0.8, 0.9, 256)))
    assert key != cache_key("ollama:qwen3:latest", call(messages=(Message("user", "other"),)))
    assert key != cache_key("ollama:qwen3:latest", call(schema=None))
    assert key != cache_key("ollama:qwen3:latest", call(seed=12))


@pytest.mark.req("REQ-LLM-005")
def test_record_stores_every_response_and_replay_serves_it(tmp_path: Path) -> None:
    """AC2: record stores (replacing), replay reads, a replay miss is an error."""
    path = tmp_path / "responses.sqlite"
    recorder = ResponseCache(path, "record")
    assert recorder.get("k") is None
    recorder.put("k", Completion("first", 3, 1))
    recorder.put("k", Completion("second", 4, 2))
    assert len(recorder) == 1
    recorder.close()
    replayer = ResponseCache(path, "replay")
    assert replayer.get("k") == Completion("second", 4, 2)
    replayer.put("other", Completion("ignored", 1, 1))
    with pytest.raises(CacheMiss):
        replayer.get("other")
    replayer.close()


@pytest.mark.req("REQ-LLM-005")
def test_off_bypasses_the_cache() -> None:
    """AC2: in off mode nothing is read or stored, and no file is needed."""
    cache = ResponseCache(None, "off")
    cache.put("k", Completion("x", 1, 1))
    assert cache.get("k") is None
    assert len(cache) == 0
    cache.close()


@pytest.mark.req("REQ-LLM-005")
def test_bad_cache_settings_are_rejected(tmp_path: Path) -> None:
    """AC2: only the three modes exist, and record and replay need a file."""
    assert CACHE_MODES == ("off", "record", "replay")
    with pytest.raises(ValueError, match="cache mode must be one of"):
        ResponseCache(tmp_path / "c.sqlite", "sometimes")
    with pytest.raises(ValueError, match="cache mode 'record' needs a path"):
        ResponseCache(None, "record")


@pytest.mark.req("REQ-LLM-001")
@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('{"goal": "eat", "steps": ["gather"]}', None),
        ('```json\n{"goal": "eat", "steps": []}\n```', None),
        ('```\n{"goal": "eat", "steps": []}\n```  ', None),
        ('{"steps": []}', "goal: Field required"),
        ('{"goal": "eat", "steps": [], "mood": "ok"}', "mood: Extra inputs are not permitted"),
        ('{"goal": 3, "steps": []}', "goal: Input should be a valid string"),
        ("not json", "Invalid JSON"),
        ("", "Invalid JSON"),
    ],
)
def test_validation_names_the_field(text: str, error: str | None) -> None:
    """AC1: every output is validated against its schema; errors name the field."""
    value, message = validate(Plan, text)
    if error is None:
        assert isinstance(value, Plan) and message is None
    else:
        assert value is None and message is not None and message.startswith(error)


@pytest.mark.req("REQ-LLM-001")
def test_unfenced_removes_only_one_surrounding_fence() -> None:
    """AC1: text without a fence, or with text around it, is left alone."""
    assert unfenced('{"a": 1}') == '{"a": 1}'
    assert unfenced('see ```json\n{"a": 1}\n```') == 'see ```json\n{"a": 1}\n```'
    assert unfenced('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert schema_of(Plan)["required"] == ["goal", "steps"]
