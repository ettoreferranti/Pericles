import itertools
import threading
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from pericles.llm.backend import BackendError, LLMSetupError
from pericles.llm.cache import CacheMiss, ResponseCache
from pericles.llm.calls import CallLog
from pericles.llm.fake import FakeBackend, FakeError, FakeRule
from pericles.llm.gateway import (
    BackendUnavailable,
    FailurePolicy,
    Gateway,
    _Health,
    check_models,
    prompt_hash,
)
from pericles.llm.types import BackendCall, Completion, Message, ModelSpec, Request, Sampling


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pick: int


SAMPLING = Sampling(0.7, 0.9, 64)
WAIT = FailurePolicy("wait", 2.0, 3.0, 10.0, 4)
LIVE = FailurePolicy("live", 2.0, 3.0, 10.0, 4)


def request(villager: str = "ada", model: str = "m", tick: int = 3, attempt: int = 0) -> Request:
    return Request(
        "plan",
        villager,
        tick,
        model,
        (Message("user", f"hello {villager}"),),
        seed=tick,
        output=Choice,
        attempt=attempt,
        template="plan-v1",
    )


def gateway(
    backends: dict[str, FakeBackend],
    tmp_path: Path,
    *,
    mode: str = "record",
    policy: FailurePolicy = WAIT,
    models: dict[str, ModelSpec] | None = None,
    slept: list[float] | None = None,
) -> Gateway:
    models = models or {"m": ModelSpec("f", "fake-m", SAMPLING)}
    cache = ResponseCache(None if mode == "off" else tmp_path / "responses.sqlite", mode)
    counter = itertools.count()
    return Gateway(
        models,
        backends,
        cache,
        policy,
        CallLog(tmp_path / f"calls-{mode}.sqlite"),
        clock=lambda: float(next(counter)),
        sleep=(slept if slept is not None else []).append,
    )


@pytest.mark.req("REQ-LLM-001")
def test_a_valid_reply_is_validated_and_logged(tmp_path: Path) -> None:
    """AC1: a request goes through the gateway to the backend and comes back validated."""
    backend = FakeBackend([FakeRule(('{"pick": 2}',))])
    g = gateway({"f": backend}, tmp_path)
    result = g.complete(request())
    assert result.valid and result.value == Choice(pick=2) and not result.cached
    assert result.latency_s == 1.0
    sent = backend.calls[0]
    assert (sent.model, sent.seed, sent.kind, sent.villager) == ("fake-m", 3, "plan", "ada")
    assert sent.schema == Choice.model_json_schema()
    g.close()


@pytest.mark.req("REQ-LLM-008")
def test_every_call_is_logged_with_its_metrics(tmp_path: Path) -> None:
    """AC1: model, prompt hash, tokens, latency, validity, retry count, raw output."""
    backend = FakeBackend([FakeRule(('{"pick": "x"}',))])
    g = gateway({"f": backend}, tmp_path)
    result = g.complete(request(attempt=2))
    assert result.error is not None and result.error.startswith("pick:")
    assert g.calls is not None
    (record,) = list(g.calls.records())
    assert (record.model, record.backend, record.backend_model) == ("m", "fake", "fake-m")
    assert record.prompt_hash == prompt_hash(backend.calls[0])
    assert (record.tokens_in, record.tokens_out, record.latency_s) == (2, 2, 1.0)
    assert (record.valid, record.attempt, record.cached) == (False, 2, False)
    assert record.error == result.error
    assert (record.raw, record.template, record.tick) == ('{"pick": "x"}', "plan-v1", 3)
    g.close()


@pytest.mark.req("REQ-LLM-005")
def test_replay_answers_from_the_cache_without_a_backend(tmp_path: Path) -> None:
    """AC2: record stores, replay serves without calling the backend; a miss is an error."""
    recorder = gateway({"f": FakeBackend([FakeRule(('{"pick": 1}',))])}, tmp_path)
    recorder.complete(request())
    recorder.close()
    silent = FakeBackend()
    replayer = gateway({"f": silent}, tmp_path, mode="replay")
    result = replayer.complete(request())
    assert result.cached and result.value == Choice(pick=1) and result.latency_s == 0.0
    assert silent.calls == []
    assert replayer.calls is not None
    assert [r.cached for r in replayer.calls.records()] == [True]
    with pytest.raises(
        CacheMiss, match=r"no cached response for plan by bram at tick 3 \(model m\)"
    ):
        replayer.complete(request("bram"))
    replayer.close()


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_backs_off_then_succeeds(tmp_path: Path) -> None:
    """AC1: a backend error pauses with exponential backoff and retries."""
    backend = FakeBackend([FakeRule((FakeError("busy"), FakeError("busy"), '{"pick": 1}'))])
    slept: list[float] = []
    g = gateway({"f": backend}, tmp_path, slept=slept)
    assert g.complete(request()).valid
    assert slept == [2.0, 6.0]
    assert g.calls is not None
    rows = list(g.calls.records())
    assert [(r.valid, r.error) for r in rows] == [
        (False, "backend: fake backend: busy"),
        (False, "backend: fake backend: busy"),
        (True, None),
    ]
    g.close()


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_gives_up_after_max_backend_failures(tmp_path: Path) -> None:
    """AC1: after max_backend_failures in a row the gateway raises BackendUnavailable."""
    slept: list[float] = []
    g = gateway({"f": FakeBackend([FakeRule((FakeError("down"),))])}, tmp_path, slept=slept)
    with pytest.raises(
        BackendUnavailable, match="fake backend: 4 failures in a row; last: fake backend: down"
    ):
        g.complete(request())
    assert slept == [2.0, 6.0, 10.0]
    assert g.calls is not None
    assert len(list(g.calls.records())) == 4
    g.close()


@pytest.mark.req("REQ-LLM-009")
def test_live_mode_returns_a_backend_error_at_once(tmp_path: Path) -> None:
    """AC2 (gateway part): in live mode a failure is one try and a flagged result."""
    slept: list[float] = []
    backend = FakeBackend(
        [FakeRule((FakeError("down"),), villager="ada"), FakeRule(('{"pick": 5}',))]
    )
    g = gateway({"f": backend}, tmp_path, policy=LIVE, slept=slept)
    failed, fine = g.complete_all([request("ada"), request("bram")])
    assert failed.backend_error == "fake backend: down" and failed.value is None
    assert not failed.valid and failed.request == request("ada")
    assert (failed.text, failed.tokens_in, failed.tokens_out) == ("", 0, 0)
    assert (failed.latency_s, failed.cached) == (0.0, False)
    assert fine.value == Choice(pick=5)
    assert slept == []
    assert g.calls is not None
    rows = {r.villager: r for r in g.calls.records()}
    assert (rows["ada"].valid, rows["ada"].error) == (False, "backend: fake backend: down")
    assert rows["bram"].valid
    assert len(g.cache) == 1
    g.close()


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_give_up_in_a_mixed_batch_keeps_the_good_results(tmp_path: Path) -> None:
    """AC1: one villager's backend failure does not lose another's logged, cached reply."""
    backend = FakeBackend(
        [FakeRule((FakeError("down"),), villager="ada"), FakeRule(('{"pick": 5}',))]
    )
    g = gateway({"f": backend}, tmp_path)
    with pytest.raises(BackendUnavailable):
        g.complete_all([request("bram"), request("ada")])
    assert g.calls is not None
    rows = list(g.calls.records())
    assert [(r.villager, r.valid) for r in rows] == [("bram", True)] + [("ada", False)] * 4
    g.close()
    silent = FakeBackend()
    replayer = gateway({"f": silent}, tmp_path, mode="replay")
    result = replayer.complete(request("bram"))
    assert result.cached and result.value == Choice(pick=5)
    assert silent.calls == []
    replayer.close()


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_counts_failures_per_backend_not_per_request(tmp_path: Path) -> None:
    """AC1: after max_backend_failures failures in a row on a backend the run stops."""
    backend = FakeBackend([FakeRule((FakeError("down"),))])
    slept: list[float] = []
    g = gateway({"f": backend}, tmp_path, slept=slept)
    with pytest.raises(
        BackendUnavailable, match="fake backend: 4 failures in a row; last: fake backend: down"
    ):
        g.complete_all([request(v) for v in ("ada", "bram", "cleo", "dov")])
    assert len(backend.calls) == 4
    assert slept == [2.0, 6.0, 10.0]
    assert g.calls is not None
    assert [r.villager for r in g.calls.records()] == ["ada"] * 4
    with pytest.raises(BackendUnavailable, match="4 failures in a row"):
        g.complete(request("eve"))
    assert len(backend.calls) == 8
    g.close()


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_give_up_spares_other_backends(tmp_path: Path) -> None:
    """AC1: a dead backend stops the run but a healthy one's replies are cached and logged."""
    down = FakeBackend([FakeRule((FakeError("down"),))])
    healthy = FakeBackend([FakeRule(('{"pick": 7}',))])
    models = {"m": ModelSpec("f", "fake-m", SAMPLING), "n": ModelSpec("g", "fake-n", SAMPLING)}
    g = gateway({"f": down, "g": healthy}, tmp_path, models=models)
    with pytest.raises(BackendUnavailable, match="4 failures in a row"):
        g.complete_all([request("ada", model="m"), request("bram", model="n")])
    assert (len(down.calls), len(healthy.calls)) == (4, 1)
    assert g.calls is not None
    rows = list(g.calls.records())
    assert [(r.villager, r.valid) for r in rows] == [("ada", False)] * 4 + [("bram", True)]
    g.close()
    replayer = gateway(
        {"f": FakeBackend(), "g": FakeBackend()}, tmp_path, mode="replay", models=models
    )
    assert replayer.complete(request("bram", model="n")).value == Choice(pick=7)
    replayer.close()


@pytest.mark.req("REQ-LLM-009")
def test_a_success_resets_the_backend_failure_count(tmp_path: Path) -> None:
    """AC1: only failures in a row count; a success in between starts the count again."""
    backend = FakeBackend(
        [
            FakeRule((FakeError("busy"), '{"pick": 1}'), villager="ada"),
            FakeRule((FakeError("busy"),) * 3 + ('{"pick": 2}',), villager="bram"),
        ]
    )
    slept: list[float] = []
    g = gateway({"f": backend}, tmp_path, slept=slept)
    ada, bram = g.complete_all([request("ada"), request("bram")])
    assert (ada.value, bram.value) == (Choice(pick=1), Choice(pick=2))
    assert (ada.latency_s, bram.latency_s) == (1.0, 1.0)
    assert len(backend.calls) == 6
    assert slept == [2.0, 2.0, 6.0, 10.0]
    g.close()


@pytest.mark.req("REQ-LLM-009")
def test_concurrent_requests_share_the_backend_failure_count(tmp_path: Path) -> None:
    """AC1: worker threads on one backend stop once it has failed max times in a row."""
    backend = FakeBackend([FakeRule((FakeError("down"),))], concurrency=3)
    g = gateway({"f": backend}, tmp_path)
    with pytest.raises(BackendUnavailable, match="4 failures in a row"):
        g.complete_all([request(v) for v in "abcdefgh"])
    assert 4 <= len(backend.calls) <= 4 + 2
    g.close()


@pytest.mark.req("REQ-LLM-009")
def test_a_late_success_does_not_revive_a_given_up_backend() -> None:
    """AC1: once a backend has failed max times in a row, an in-flight success keeps it down."""
    health = _Health(2)
    assert not health.failed("a") and not health.given_up()
    assert health.failed("b") and health.given_up()
    health.succeeded()
    assert health.given_up() and health.last == "b"
    fresh = _Health(2)
    fresh.failed("a")
    fresh.succeeded()
    assert not fresh.failed("c")


@pytest.mark.req("REQ-LLM-005")
def test_identical_requests_in_a_batch_call_the_backend_once(tmp_path: Path) -> None:
    """AC2: duplicates share one reply, so a replay serves what the run saw."""
    backend = FakeBackend([FakeRule(('{"pick": 1}', '{"pick": 2}'))])
    g = gateway({"f": backend}, tmp_path)
    first, second = g.complete_all([request("ada"), request("ada")])
    assert len(backend.calls) == 1
    assert first.value == second.value == Choice(pick=1)
    assert (first.cached, second.cached) == (False, True)
    assert (first.latency_s, second.latency_s) == (1.0, 0.0)
    assert g.calls is not None
    rows = list(g.calls.records())
    assert [(r.cached, r.raw) for r in rows] == [(False, '{"pick": 1}'), (True, '{"pick": 1}')]
    g.close()
    replayer = gateway({"f": FakeBackend()}, tmp_path, mode="replay")
    again = replayer.complete_all([request("ada"), request("ada")])
    assert [r.value for r in again] == [Choice(pick=1)] * 2
    replayer.close()


@pytest.mark.req("REQ-LLM-009")
def test_live_mode_duplicates_share_a_backend_error(tmp_path: Path) -> None:
    """AC2 (gateway part): a duplicate of a failed request carries the same error, unlogged."""
    backend = FakeBackend([FakeRule((FakeError("down"),))])
    g = gateway({"f": backend}, tmp_path, policy=LIVE)
    first, second = g.complete_all([request("ada"), request("ada")])
    assert first.backend_error == second.backend_error == "fake backend: down"
    assert len(backend.calls) == 1
    assert g.calls is not None
    assert len(list(g.calls.records())) == 1
    g.close()


def test_failure_policy_delay_is_capped() -> None:
    """The n-th failure in a row waits base * factor^(n-1), at most backoff_max_s."""
    assert [WAIT.delay(n) for n in (1, 2, 3, 4)] == [2.0, 6.0, 10.0, 10.0]


@pytest.mark.req("REQ-LLM-007")
def test_results_follow_request_order_not_completion_order(tmp_path: Path) -> None:
    """AC2: shuffling the requests changes no villager's result."""
    rules = [FakeRule((f'{{"pick": {n}}}',), villager=v) for n, v in enumerate("abcde")]
    forward = gateway({"f": FakeBackend(rules, concurrency=3)}, tmp_path, mode="off")
    backward = gateway({"f": FakeBackend(rules, concurrency=3)}, tmp_path, mode="off")
    ids = list("abcde")
    first = forward.complete_all([request(v) for v in ids])
    second = backward.complete_all([request(v) for v in reversed(ids)])
    assert [r.request.villager for r in first] == ids
    assert [r.request.villager for r in second] == list(reversed(ids))
    one = {r.request.villager: r.value for r in first}
    two = {r.request.villager: r.value for r in second}
    assert one == two == {v: Choice(pick=n) for n, v in enumerate(ids)}
    forward.close()
    backward.close()


class Tracking(FakeBackend):
    """Counts calls in flight and records the model order."""

    def __init__(
        self, rules: Sequence[FakeRule], concurrency: int, gate: threading.Barrier | None
    ) -> None:
        super().__init__(rules, concurrency=concurrency)
        self.in_flight = 0
        self.peak = 0
        self.order: list[str] = []
        self.gate = gate
        self.lock = threading.Lock()

    def complete(self, call: BackendCall) -> Completion:
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            self.order.append(call.model)
        if self.gate is not None:
            self.gate.wait(timeout=5)
        try:
            return super().complete(call)
        finally:
            with self.lock:
                self.in_flight -= 1


@pytest.mark.req("REQ-LLM-007")
def test_requests_are_batched_by_model_within_the_concurrency_limit(tmp_path: Path) -> None:
    """AC1: one model at a time per backend, at most `concurrency` calls in flight."""
    backend = Tracking([FakeRule(('{"pick": 0}',))], concurrency=2, gate=threading.Barrier(2))
    models = {
        "x": ModelSpec("f", "model-x", SAMPLING),
        "y": ModelSpec("f", "model-y", SAMPLING),
    }
    g = gateway({"f": backend}, tmp_path, mode="off", models=models)
    mixed = [request(v, model=m) for v, m in zip("abcd", "yxyx", strict=True)]
    results = g.complete_all(mixed)
    assert [r.request.villager for r in results] == list("abcd")
    assert backend.order == ["model-x", "model-x", "model-y", "model-y"]
    assert backend.peak == 2
    assert g.calls is not None
    assert [r.villager for r in g.calls.records()] == list("abcd")
    g.close()


@pytest.mark.req("REQ-LLM-002")
def test_check_asks_each_backend_for_its_models(tmp_path: Path) -> None:
    """AC1 (gateway part): a configured model the backend lacks fails fast."""
    models = {
        "a": ModelSpec("one", "alpha", SAMPLING),
        "b": ModelSpec("one", "beta", SAMPLING),
        "c": ModelSpec("two", "gamma", SAMPLING),
    }
    backends = {"one": FakeBackend(models=["alpha", "beta"]), "two": FakeBackend(models=[])}
    with pytest.raises(LLMSetupError, match="not available: gamma"):
        check_models(models, backends)
    check_models({k: v for k, v in models.items() if k != "c"}, backends)


def test_gateway_rejects_unknown_backends_models_and_modes(tmp_path: Path) -> None:
    """A model must name a backend, a request a model, a policy a mode."""
    with pytest.raises(ValueError, match="model 'm': unknown backend 'f'"):
        gateway({}, tmp_path)
    with pytest.raises(ValueError, match="mode must be one of"):
        gateway(
            {"f": FakeBackend()}, tmp_path, policy=FailurePolicy("eventually", 1.0, 1.0, 1.0, 1)
        )
    g = gateway({"f": FakeBackend()}, tmp_path)
    with pytest.raises(ValueError, match="unknown model 'nope'"):
        g.complete(request(model="nope"))
    g.close()


def test_a_request_without_an_output_model_is_not_validated(tmp_path: Path) -> None:
    """Free text (e.g. a board post rendered later) passes through unvalidated."""
    g = gateway({"f": FakeBackend([FakeRule(("just words",))])}, tmp_path)
    plain = Request("post", "ada", 1, "m", (Message("user", "say hi"),), seed=1)
    result = g.complete(plain)
    assert result.valid and result.value is None and result.text == "just words"
    g.close()


def test_backend_error_type_is_reexported_for_callers() -> None:
    """Callers catch BackendError from pericles.llm.backend."""
    assert issubclass(BackendUnavailable, Exception)
    assert not issubclass(BackendUnavailable, BackendError)
