# NFR: Non-Functional Requirements

### REQ-NFR-001: Reproducibility
Must · M2 · Proposed
- AC1: Same config, seed, intervention schedule and LLM cache in replay mode → identical event-log hash (golden-run test in CI).

### REQ-NFR-002: Platform
Must · M0 · Proposed
- AC1: Runs on macOS (Apple Silicon) with Python ≥ 3.12 and Node ≥ 20. The core also runs on Linux, which CI uses with FakeBackend.

### REQ-NFR-003: Engine performance
Should · M1 · Proposed
- AC1: Without LLM calls (all scripted), the engine sustains ≥ 1000 ticks/s with 150 villagers on a 128×128 map on the target machine.

### REQ-NFR-004: LLM budget
Should · M2 · Proposed
- AC1: With default parameters, the average number of LLM calls per adult per in-game day is ≤ a configured budget (default 20), and this is reported by the metrics.

### REQ-NFR-005: Code quality gates
Must · M0 · Proposed
- AC1: CI runs `ruff`, `mypy --strict`, pytest, the traceability check, and the viewer lint, type check and tests. All must pass to merge.

### REQ-NFR-006: Mutation testing
Must · M0 · Proposed
- AC1: `mutmut` is configured for `core`, `agents` and `llm`. Stryker is configured for the viewer.
- AC2: The mutation score is ≥ 80% for `core` and ≥ 70% for the other packages, enforced on changed modules in PRs, with a full nightly run.

### REQ-NFR-007: Traceability
Must · M0 · Proposed
- AC1: A script generates the requirement → test matrix (Markdown) from requirement docs and test markers.
- AC2: CI fails if an `Accepted` or `Implemented` requirement has no linked test, or if a test references an unknown requirement ID.

### REQ-NFR-008: Documentation
Must · M0 · Proposed
- AC1: Each significant design decision has an ADR in `docs/adr/`. ADRs are never deleted, only superseded.
