# LLM: Gateway and Backends

### REQ-LLM-001: Backend interface
Must · M2 · Implemented
- AC1: All LLM access goes through the gateway's backend interface. No other module imports a backend client.
- AC2: `OllamaBackend`, `MLXBackend` and `FakeBackend` implement the interface.

### REQ-LLM-002: Ollama backend
Must · M2 · Implemented
- AC1: Lists the available models and fails fast with a clear message if a configured model is missing.
- AC2: Uses schema-constrained output (`format`) where available.
- AC3: Contract tests against a live Ollama instance are marked `slow` and excluded from CI.

### REQ-LLM-003: MLX backend
Should · M2 · Implemented
- AC1: Loads an MLX model by name/path and implements the interface, including JSON output validation.

### REQ-LLM-004: Fake backend
Must · M2 · Implemented
- AC1: Returns scripted responses keyed by call kind, villager or prompt pattern, or replays recorded responses.
- AC2: It can simulate latency, invalid output and errors for tests.

### REQ-LLM-005: Response cache
Must · M2 · Implemented
- AC1: Cache key = hash(model, sampling params, prompt, seed).
- AC2: In `record` mode every response is stored. In `replay` mode responses come from the cache, and a miss is an error. In `off` mode the cache is bypassed.
- AC3: A run replayed with `replay` mode produces an identical event-log hash.

### REQ-LLM-006: Model assignment
Must · M2 · Implemented
- AC1: The config can pin villagers to models, or split groups by ratio (seeded), with per-model sampling parameters.
- AC2: Every LLM call event records the model actually used.

### REQ-LLM-007: Scheduling
Should · M2 · Implemented
- AC1: The gateway batches pending requests by model and respects a configured concurrency limit per backend.
- AC2: The order of requests within a tick does not affect simulation results (see REQ-SIM-002 AC2).

### REQ-LLM-008: Call metrics
Must · M2 · Implemented
- AC1: Every call logs model, prompt hash, tokens in/out, latency, validity, retry count and raw output (compressed).

### REQ-LLM-009: Backend failure
Must · M2 · Accepted
- AC1: A backend error mid-run, in wait mode, pauses the run and retries with exponential backoff. After `max_backend_failures` the run stops cleanly and can be resumed.
- AC2: In live mode, the affected villagers use fallback behaviour, and the event is flagged.
