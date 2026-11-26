"""The one way to call a model (REQ-LLM-001, -005, -007, -008, -009; ADR-0017)."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pericles.core.canonical import canonical_json
from pericles.llm.backend import Backend, BackendError
from pericles.llm.cache import CacheMiss, ResponseCache, cache_key
from pericles.llm.calls import CallLog, CallRecord
from pericles.llm.types import BackendCall, Completion, ModelSpec, Request, Result
from pericles.llm.validate import schema_of, validate

MODES = ("wait", "live")


@dataclass(frozen=True)
class FailurePolicy:
    mode: str
    backoff_base_s: float
    backoff_factor: float
    backoff_max_s: float
    max_backend_failures: int

    def delay(self, failures: int) -> float:
        """Seconds to wait after the `failures`-th failure in a row (counting from 1)."""
        return min(self.backoff_base_s * self.backoff_factor ** (failures - 1), self.backoff_max_s)


class BackendUnavailable(Exception):
    """Wait mode: a backend failed `max_backend_failures` times in a row. Stop and resume."""


class _Health:
    """One backend's failures in a row during one `complete_all`, shared by its workers."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._lock = threading.Lock()
        self.failures = 0
        self.last = ""

    def given_up(self) -> bool:
        with self._lock:
            return self.failures >= self._limit

    def failed(self, error: str) -> bool:
        """Count a failure; True once the backend has failed `limit` times in a row."""
        with self._lock:
            self.failures += 1
            self.last = error
            return self.failures >= self._limit

    def succeeded(self) -> None:
        with self._lock:
            if self.failures < self._limit:
                self.failures = 0


@dataclass(frozen=True)
class _Outcome:
    completion: Completion | None
    latency_s: float
    errors: tuple[str, ...]


def prompt_hash(call: BackendCall) -> str:
    text = canonical_json([m.to_dict() for m in call.messages])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_models(models: Mapping[str, ModelSpec], backends: Mapping[str, Backend]) -> None:
    """Fail fast: each backend confirms it can serve the models configured on it."""
    for key in sorted(backends):
        names = sorted({spec.name for spec in models.values() if spec.backend == key})
        if names:
            backends[key].check(names)


class Gateway:
    def __init__(
        self,
        models: Mapping[str, ModelSpec],
        backends: Mapping[str, Backend],
        cache: ResponseCache,
        policy: FailurePolicy,
        calls: CallLog | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        for key in sorted(models):
            if models[key].backend not in backends:
                raise ValueError(f"model {key!r}: unknown backend {models[key].backend!r}")
        if policy.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {policy.mode!r}")
        self.models = dict(models)
        self.backends = dict(backends)
        self.cache = cache
        self.policy = policy
        self.calls = calls
        self._clock = clock
        self._sleep = sleep

    def check(self) -> None:
        check_models(self.models, self.backends)

    def complete(self, request: Request) -> Result:
        return self.complete_all([request])[0]

    def complete_all(self, requests: Sequence[Request]) -> list[Result]:
        specs = [self._spec(r) for r in requests]
        calls = [self._call(r, s) for r, s in zip(requests, specs, strict=True)]
        keys = [
            cache_key(f"{self.backends[s.backend].kind}:{s.name}", c)
            for s, c in zip(specs, calls, strict=True)
        ]
        hits: dict[int, Completion] = {}
        for i, request in enumerate(requests):
            try:
                hit = self.cache.get(keys[i])
            except CacheMiss:
                raise CacheMiss(
                    f"replay: no cached response for {request.kind} by {request.villager} "
                    f"at tick {request.tick} (model {request.model})"
                ) from None
            if hit is not None:
                hits[i] = hit
        leaders: dict[int, int] = {}
        first: dict[str, int] = {}
        for i in range(len(requests)):
            if i not in hits:
                leaders[i] = first.setdefault(keys[i], i)
        groups: dict[tuple[str, str], list[int]] = {}
        for i, leader in leaders.items():
            if i == leader:
                groups.setdefault((specs[i].backend, specs[i].name), []).append(i)
        health = {key: _Health(self.policy.max_backend_failures) for key in self.backends}
        outcomes: dict[int, _Outcome] = {}
        for backend_key, name in sorted(groups):
            backend, state = self.backends[backend_key], health[backend_key]
            indices = groups[(backend_key, name)]
            with ThreadPoolExecutor(max_workers=backend.concurrency) as pool:
                done = list(
                    pool.map(lambda i, b=backend, h=state: self._attempt(b, calls[i], h), indices)
                )
            outcomes.update(zip(indices, done, strict=True))
        results: list[Result] = []
        unavailable: str | None = None
        for i, request in enumerate(requests):
            spec, call = specs[i], calls[i]
            if i in hits:
                result = self._result(request, hits[i], 0.0, cached=True)
                self._log(request, spec, call, result)
                results.append(result)
                continue
            leader = leaders[i]
            outcome = outcomes[leader]
            if i == leader:
                for error in outcome.errors:
                    self._log_failure(request, spec, call, error)
            if outcome.completion is None:
                state = health[spec.backend]
                last = outcome.errors[-1] if outcome.errors else state.last
                if self.policy.mode == "wait" and unavailable is None:
                    unavailable = (
                        f"{self.backends[spec.backend].describe()}: "
                        f"{self.policy.max_backend_failures} failures in a row; "
                        f"last: {state.last}"
                    )
                results.append(Result(request, "", None, None, last, 0, 0, 0.0, False))
                continue
            if i == leader:
                self.cache.put(keys[i], outcome.completion)
                result = self._result(request, outcome.completion, outcome.latency_s, cached=False)
            else:
                result = self._result(request, outcome.completion, 0.0, cached=True)
            self._log(request, spec, call, result)
            results.append(result)
        if unavailable is not None:
            raise BackendUnavailable(unavailable)
        return results

    def close(self) -> None:
        self.cache.close()
        if self.calls is not None:
            self.calls.close()

    def _spec(self, request: Request) -> ModelSpec:
        if request.model not in self.models:
            raise ValueError(f"unknown model {request.model!r}")
        return self.models[request.model]

    @staticmethod
    def _call(request: Request, spec: ModelSpec) -> BackendCall:
        schema = None if request.output is None else schema_of(request.output)
        return BackendCall(
            spec.name,
            request.messages,
            spec.sampling,
            request.seed,
            schema,
            request.kind,
            request.villager,
        )

    def _attempt(self, backend: Backend, call: BackendCall, health: _Health) -> _Outcome:
        """Live: one try. Wait: retry with backoff until a success or the backend gives up."""
        errors: list[str] = []
        while not health.given_up():
            start = self._clock()
            try:
                completion = backend.complete(call)
            except BackendError as error:
                errors.append(str(error))
                if self.policy.mode == "live" or health.failed(str(error)):
                    break
                self._sleep(self.policy.delay(len(errors)))
                continue
            health.succeeded()
            return _Outcome(completion, self._clock() - start, tuple(errors))
        return _Outcome(None, 0.0, tuple(errors))

    @staticmethod
    def _result(
        request: Request, completion: Completion, latency: float, *, cached: bool
    ) -> Result:
        value, error = (None, None)
        if request.output is not None:
            value, error = validate(request.output, completion.text)
        return Result(
            request,
            completion.text,
            value,
            error,
            None,
            completion.tokens_in,
            completion.tokens_out,
            latency,
            cached,
        )

    def _log(self, request: Request, spec: ModelSpec, call: BackendCall, result: Result) -> None:
        if self.calls is None:
            return
        self.calls.append(
            CallRecord(
                request.tick,
                request.villager,
                request.kind,
                request.model,
                self.backends[spec.backend].kind,
                spec.name,
                prompt_hash(call),
                result.tokens_in,
                result.tokens_out,
                result.latency_s,
                result.valid,
                result.error,
                request.attempt,
                result.cached,
                request.template,
                result.text,
            )
        )

    def _log_failure(
        self, request: Request, spec: ModelSpec, call: BackendCall, error: str
    ) -> None:
        if self.calls is None:
            return
        self.calls.append(
            CallRecord(
                request.tick,
                request.villager,
                request.kind,
                request.model,
                self.backends[spec.backend].kind,
                spec.name,
                prompt_hash(call),
                0,
                0,
                0.0,
                False,
                f"backend: {error}",
                request.attempt,
                False,
                request.template,
                "",
            )
        )
