from pathlib import Path

import pytest

from pericles.llm.backend import Backend, BackendError, LLMSetupError
from pericles.llm.fake import FakeBackend, FakeError, FakeRule
from pericles.llm.types import BackendCall, Message, Request, Result, Sampling

SAMPLING = Sampling(temperature=0.5, top_p=0.9, max_tokens=64)


def call(kind: str = "plan", villager: str = "ada", text: str = "hello there") -> BackendCall:
    return BackendCall(
        "m", (Message("system", "sys"), Message("user", text)), SAMPLING, 1, None, kind, villager
    )


@pytest.mark.req("REQ-LLM-001")
def test_the_fake_backend_implements_the_interface() -> None:
    """AC2: FakeBackend satisfies the Backend protocol."""
    backend: Backend = FakeBackend()
    assert backend.kind == "fake"
    assert backend.concurrency == 1
    assert backend.describe() == "fake backend"


@pytest.mark.req("REQ-LLM-004")
def test_rules_match_by_kind_villager_and_pattern_first_match_wins() -> None:
    """AC1: scripted responses keyed by call kind, villager or prompt pattern."""
    backend = FakeBackend(
        [
            FakeRule(("by-pattern",), pattern=r"storm"),
            FakeRule(("by-villager",), villager="bram"),
            FakeRule(("by-kind",), kind="vote"),
            FakeRule(("anything",)),
        ]
    )
    assert backend.complete(call(text="a storm comes")).text == "by-pattern"
    assert backend.complete(call(villager="bram")).text == "by-villager"
    assert backend.complete(call(kind="vote")).text == "by-kind"
    assert backend.complete(call()).text == "anything"


@pytest.mark.req("REQ-LLM-004")
def test_a_pattern_only_looks_at_the_last_message() -> None:
    """AC1: the system message does not count for a pattern."""
    backend = FakeBackend([FakeRule(("hit",), pattern="sys")])
    with pytest.raises(BackendError, match="no scripted reply for kind 'plan', villager 'ada'"):
        backend.complete(call())


@pytest.mark.req("REQ-LLM-004")
def test_replies_are_served_in_order_and_the_last_repeats() -> None:
    """AC1/AC2: a rule replays a recorded sequence; invalid output is just a reply."""
    backend = FakeBackend([FakeRule(("not json", '{"ok": true}'))])
    assert [backend.complete(call()).text for _ in range(3)] == [
        "not json",
        '{"ok": true}',
        '{"ok": true}',
    ]


@pytest.mark.req("REQ-LLM-004")
def test_errors_and_latency_are_simulated() -> None:
    """AC2: a FakeError raises BackendError; delay_s goes through the injected sleep."""
    slept: list[float] = []
    backend = FakeBackend([FakeRule((FakeError("down"), "up"), delay_s=0.25)], sleep=slept.append)
    with pytest.raises(BackendError, match="fake backend: down"):
        backend.complete(call())
    assert backend.complete(call()).text == "up"
    assert slept == [0.25, 0.25]


@pytest.mark.req("REQ-LLM-004")
def test_tokens_are_counted_in_words_and_calls_are_recorded() -> None:
    """AC1: token counts are word counts, so tests can assert on metrics."""
    backend = FakeBackend([FakeRule(("one two three",))])
    completion = backend.complete(call(text="four five"))
    assert (completion.tokens_in, completion.tokens_out) == (3, 3)
    assert [c.villager for c in backend.calls] == ["ada"]


@pytest.mark.req("REQ-LLM-004")
def test_check_reports_models_the_fake_does_not_serve() -> None:
    """AC2: a fake can stand in for a server that lacks a model."""
    FakeBackend().check(["anything"])
    with pytest.raises(LLMSetupError, match="not available: b, c"):
        FakeBackend(models=["a"]).check(["a", "b", "c"])


@pytest.mark.req("REQ-LLM-004")
@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"replies": ()}, "at least one reply"),
        ({"replies": ("x",), "delay_s": -1.0}, "non-negative"),
    ],
)
def test_bad_rules_are_rejected(rule: dict[str, object], message: str) -> None:
    """AC1: a rule needs a reply and a non-negative delay."""
    with pytest.raises(ValueError, match=message):
        FakeRule(**rule)  # type: ignore[arg-type]


@pytest.mark.req("REQ-LLM-004")
def test_rules_load_from_yaml(tmp_path: Path) -> None:
    """AC1: recorded responses replay from a YAML script."""
    script = tmp_path / "replies.yaml"
    script.write_text(
        "- {villager: bram, replies: ['{\"a\": 1}']}\n"
        "- {kind: plan, delay_s: 0.5, replies: [{error: busy}, 'ok']}\n",
        encoding="utf-8",
    )
    backend = FakeBackend.from_file(script, concurrency=2)
    assert backend.concurrency == 2
    assert backend.complete(call(villager="bram")).text == '{"a": 1}'
    assert backend.rules[1] == FakeRule((FakeError("busy"), "ok"), kind="plan", delay_s=0.5)


@pytest.mark.req("REQ-LLM-004")
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{a: 1}", "expected a list of rules"),
        ("- 3\n", r"\[0\]: expected a mapping"),
        ("- {replies: [x], colour: red}\n", r"\[0\]\.colour: unknown key"),
        ("- {replies: []}\n", r"\[0\]\.replies: expected a non-empty list"),
        ("- {replies: [3]}\n", r"\[0\]\.replies\[0\]: a reply is text or"),
        ("- {replies: [x], kind: 3}\n", r"\[0\]\.kind: expected text"),
        ("- {replies: [x], delay_s: fast}\n", r"\[0\]\.delay_s: expected a number"),
        ("- {replies: [x], pattern: '('}\n", r"\[0\]: "),
        ("- [unclosed\n", "replies.yaml"),
    ],
)
def test_bad_scripts_name_the_entry(tmp_path: Path, text: str, message: str) -> None:
    """AC1: script errors are LLMSetupErrors that name the file and entry."""
    script = tmp_path / "replies.yaml"
    script.write_text(text, encoding="utf-8")
    with pytest.raises(LLMSetupError, match=message):
        FakeBackend.from_file(script)


@pytest.mark.req("REQ-LLM-001")
def test_result_validity_needs_no_validation_or_backend_error() -> None:
    """AC1: a Result is valid only without a validation error and a backend error."""
    request = Request("plan", "ada", 0, "m", (Message("user", "x"),), 1)

    def result(error: str | None, backend_error: str | None) -> Result:
        return Result(request, "", None, error, backend_error, 0, 0, 0.0, False)

    assert result(None, None).valid
    assert not result("goal: Field required", None).valid
    assert not result(None, "down").valid
    assert Message("user", "x").to_dict() == {"role": "user", "content": "x"}
    assert SAMPLING.to_dict() == {"temperature": 0.5, "top_p": 0.9, "max_tokens": 64}
