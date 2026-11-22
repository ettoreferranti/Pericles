# Requirements Catalog

Requirements are derived from the [design spec](../superpowers/specs/2026-11-22-pericles-design.md).

## Conventions

- **ID:** `REQ-<AREA>-NNN`. IDs are stable: never reuse or renumber them. A withdrawn requirement keeps its ID with status `Withdrawn`.
- **Priority:** `Must` (v1), `Should` (v1 if feasible), `Could` (backlog).
- **Status:** `Proposed` → `Accepted` → `Implemented` (all acceptance criteria covered by passing tests) | `Withdrawn`.
- **Milestone:** M0–M5 (see spec §12).
- **Acceptance criteria** are numbered (`AC1`, `AC2`, …). Tests reference them as
  `@pytest.mark.req("REQ-SIM-001")`, and the docstring names the AC.
- CI fails if an `Accepted` or `Implemented` requirement has no linked test (ADR-0008).

## Areas

| Area | File | Scope |
|------|------|-------|
| SIM | [sim.md](sim.md) | World, time, content, resources, buildings, villagers, lifecycle |
| ECO | [eco.md](eco.md) | Barter, coins, ownership, storage |
| SOC | [soc.md](soc.md) | Dialogue, promises, board, meetings, laws, violations |
| AGT | [agt.md](agt.md) | Minds: triggers, prompts, planning, executor, memory, reflection, fallback |
| LLM | [llm.md](llm.md) | Gateway, backends, validation, cache, model assignment |
| EXP | [exp.md](exp.md) | Experiments, interventions, god powers, run directory, metrics, reports, sweeps |
| VIEW | [view.md](view.md) | 3D viewer, live/replay, panels, controls |
| NFR | [nfr.md](nfr.md) | Determinism, performance, quality, process |
