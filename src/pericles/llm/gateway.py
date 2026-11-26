"""The one way to call a model (REQ-LLM-001, -005, -007, -008, -009; ADR-0017)."""

from __future__ import annotations

import hashlib
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
        groups: dict[tuple[str, str], list[int]] = {}
        for i, spec in enumerate(specs):
            if i not in hits:
                groups.setdefault((spec.backend, spec.name), []).append(i)
        outcomes: dict[int, _Outcome] = {}
        for backend_key, name in sorted(groups):
            backend = self.backends[backend_key]
            indices = groups[(backend_key, name)]
            with ThreadPoolExecutor(max_workers=backend.concurrency) as pool:
                done = list(pool.map(lambda i, b=backend: self._attempt(b, calls[i]), indices))
            outcomes.update(zip(indices, done, strict=True))
        results: list[Result] = []
        unavailable: str | None = None
        for i, request in enumerate(requests):
            spec, call = specs[i], calls[i]
            backend = self.backends[spec.backend]
            if i in hits:
                result = self._result(request, hits[i], 0.0, cached=True)
                self._log(request, spec, call, result)
                results.append(result)
                continue
            outcome = outcomes[i]
            for error in outcome.errors:
                self._log_failure(request, spec, call, error)
            if outcome.completion is None:
                last = outcome.errors[-1]
                if self.policy.mode == "wait" and unavailable is None:
                    unavailable = (
                        f"{backend.describe()}: {len(outcome.errors)} failures in a row; "
                        f"last: {last}"
                    )
                results.append(Result(request, "", None, None, last, 0, 0, 0.0, False))
                continue
            self.cache.put(keys[i], outcome.completion)
            result = self._result(request, outcome.completion, outcome.latency_s, cached=False)
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

    def _attempt(self, backend: Backend, call: BackendCall) -> _Outcome:
        tries = 1 if self.policy.mode == "live" else self.policy.max_backend_failures
        errors: list[str] = []
        for failure in range(1, tries + 1):
            start = self._clock()
            try:
                completion = backend.complete(call)
            except BackendError as error:
                errors.append(str(error))
                if failure < tries:
                    self._sleep(self.policy.delay(failure))
                continue
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
