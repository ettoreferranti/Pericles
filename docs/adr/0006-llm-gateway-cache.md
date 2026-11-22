# ADR-0006: LLM gateway with backends, validation and response cache

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

Agents must be able to use different models (Ollama, MLX), be testable without a live model, and runs must be replayable bit-exactly even though LLM sampling is not deterministic.

## Decision

All LLM access goes through a gateway with a backend interface (`OllamaBackend`, `MLXBackend`, `FakeBackend`). The gateway applies schema-constrained generation where supported, validates every output, handles retries, schedules requests to avoid swapping models in and out of memory, records per-call metrics, and keeps a response cache keyed by `hash(model, params, prompt, seed)` with modes `off | record | replay`.

## Consequences

+ Deterministic tests with FakeBackend; bit-exact replays with the cache.
+ Re-running with the cache off measures how much model randomness changes outcomes.
− Prompt changes invalidate the cache (intended).
