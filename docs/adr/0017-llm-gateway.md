# ADR-0017: LLM gateway, backends, cache and call log

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)
- **Refines:** ADR-0006

## Context

M2a builds the gateway that ADR-0006 describes (REQ-LLM-001…009). Minds come in M2b, memory and reflection in M2c. Runs must replay bit-exactly from a response cache, model families must be comparable, and an Ollama server that stops mid-run must not corrupt a run. On 2026-11-26 the user split M2 into three plans and put the MLX backend in M2a.

## Decision

1. **Package.**
   - `pericles.llm` knows no villages. It imports only the standard library, pydantic, PyYAML and `pericles.core.canonical`.
   - Only `ollama.py` imports `urllib`, and only `mlx_runtime.py` imports `mlx` or `mlx_lm`.
   - Only `pericles.llm` and `pericles.experiment` construct backends. Agents will call only `Gateway` and the types.
2. **Requests name logical models.**
   - A `Request` names a key of `llm.models`, with its kind, villager, tick, messages, seed, an optional pydantic output model, the attempt number and the template version.
   - The gateway resolves the key to a `ModelSpec` (backend key, backend model name, `Sampling`) and builds a `BackendCall`.
3. **Backends.** `kind`, `concurrency`, `describe()`, `check(models)` and `complete(call)`.
   - `check` raises `LLMSetupError` when the backend is unreachable or a model is missing. `complete` raises `BackendError` for failures that may pass.
   - **Ollama** uses `/api/tags` and `/api/chat` with `stream: false`, the output schema as `format`, and `temperature`, `top_p`, `num_predict` and `seed` as options. A model name without a tag means `:latest`.
   - **MLX** runs in-process, one call at a time. It has no constrained decoding, so it appends one system message giving the JSON schema. The gateway validates its output like any other.
   - **Fake** follows rules matched by kind, villager or a regex on the last message, first match wins. Each rule serves its replies in order and repeats the last one. A reply is text or `{error: message}`, and a rule may add a delay. Rules can be loaded from YAML.
4. **Validation.**
   - The output schema is the pydantic model's JSON schema. The text is validated with `model_validate_json`, after removing one surrounding Markdown code fence if present.
   - An invalid output is a `Result` with `value=None` and `error="<field path>: <message>"`. It never raises. Retries with the error fed back are the M2b mind's job (REQ-AGT-005).
5. **Cache.**
   - The key is the SHA-256 of canonical JSON `{model: "<backend kind>:<backend model>", sampling, messages, schema, seed}`.
   - It is stored in `llm_cache/responses.sqlite` (key, text, tokens in, tokens out).
   - `off` bypasses the cache. `record` calls the backend and stores (replacing) every response. `replay` answers from the cache only, and a miss raises `CacheMiss`.
   - A replay run copies its source cache (`llm.cache_from`: a run directory, its `llm_cache` directory, or the file) into its own `llm_cache` at start, so every run directory is self-contained.
6. **Call log.**
   - One row per call goes to `llm_calls.sqlite`, cache hits and backend errors included. Each row holds tick, villager, kind, logical model, backend kind, backend model, prompt hash (of the messages), tokens in and out, latency, validity, error, attempt, cached flag, template version and the zlib-compressed raw output.
   - It is kept out of `events.sqlite`, because latency and tokens differ between a run and its replay. That would break REQ-LLM-005 AC3.
   - On resume it is truncated like the event log.
7. **Scheduling.**
   - `complete_all(requests)` looks up the cache on the calling thread. It groups the misses by (backend, model) and runs the groups in sorted order, one model at a time per backend, so a backend never swaps models within a batch. Each group runs on a pool of `concurrency` threads.
   - Cache writes and call-log rows are made on the calling thread, in request order, so results never depend on completion order.
8. **Failure policy.**
   - In **wait** mode a failing call is retried after `min(backoff_base_s × backoff_factor^(n-1), backoff_max_s)` seconds. The count of failures in a row is kept per backend for the whole `complete_all` call, shared by that backend's worker threads; a success resets it, and the backoff uses the request's own failure count. A request stops after `max_backend_failures` failures of its own in a row, and the batch then raises as below. After `max_backend_failures` failures in a row on a backend, it is given up for the rest of the call: no more attempts reach it, other backends finish their work, every row (successes and the failed attempts actually made) is logged, successes are cached, and `BackendUnavailable` is raised. Identical requests (one cache key) in one batch call the backend once; the duplicates share the reply and are logged as cached, so a replay serves what the run saw.
   - The runner lets it propagate before the engine steps, so the event log ends at the last whole tick. The CLI exits 3 and the run continues with `pericles resume`.
   - In **live** mode a failing call is tried once, and its `Result` carries `backend_error`. M2b's mind falls back and flags it.
9. **`llm:` experiment section.**
   - The packaged defaults in `default_settings.yaml` cover every `LLMConfig` field: mode, cache, `cache_from`, backoff, failure limit, default sampling, default concurrency, timeout and Ollama URL.
   - An experiment adds `backends` (`kind: ollama | mlx | fake`), `models` (`backend`, `name`, optional sampling) and `assign` (ratios).
   - Fake `replies` paths and `cache_from` resolve against the experiment file. The resolved config stores every value.
   - `engine.max_map_tiles` bounds `map.width × map.height`.
10. **Model assignment.**
    - A villager's `model:` pins it, and must name a key of `llm.models`, as must `engine.adult_model`.
    - Adults without a pin are split by `assign`. Exact counts come from the largest remainder (ties by model key). The unpinned adult ids are sorted, then shuffled with `random.Random(f"pericles-models:{seed}")`, then assigned in model-key order.
    - The resolved population records the result, so reloading it assigns nothing new.
11. **Startup.**
    - `pericles run` builds the backends and checks every configured model before it creates the run directory. A missing model or unreachable server exits 2 with the model, the URL and the `ollama pull` command.
    - `meta.json` records `llm_mode`, `cache_mode` and `reproducible`, which is false in live mode.

## Consequences

- Tests and CI run the whole gateway with `FakeBackend`. Ollama and MLX contract tests are `slow` and run on the user's Mac.
- A recorded run can be replayed without any model installed.
- A prompt or sampling change invalidates the cache, as intended (ADR-0006).
- MLX output is unconstrained, so weak MLX models produce more invalid outputs than the same model under Ollama's `format`. The call log makes that measurable.
- Live-mode fallback flagging (REQ-LLM-009 AC2) and retries with the validation error (REQ-AGT-005) belong to the M2b mind.

Amended on 2026-11-26, after the final M2a review (REQ-LLM-009, REQ-LLM-005). §8 now counts failures in a row per backend for one `complete_all` call, shared by its worker threads, as well as each request's own failures in a row; whichever reaches `max_backend_failures` first stops the request. A dead backend with N waiting requests now costs `max_backend_failures` calls, not N times that. It also states that identical requests in one batch call the backend once.
