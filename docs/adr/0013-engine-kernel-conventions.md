# ADR-0013: Engine kernel conventions

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

The engine must be deterministic (REQ-SIM-002), fast enough for 1000 ticks/s with 150 scripted villagers (REQ-NFR-003), and driven by validated, data-driven content (ADR-0005). Spec §3.1 allowed only the stdlib and numpy in `core`. Content validation with precise error messages (REQ-SIM-005 AC1) is a large amount of hand-written code without a schema library.

## Decision

1. `pericles.core` may depend on **pydantic 2** (content schemas) and **PyYAML** (content files) in addition to the stdlib. numpy is not used until a measured need exists.
2. `Engine.step(state, intents)` **mutates `state` in place** and returns it together with the tick's events. Copying the world every tick is too slow. Determinism is guaranteed by construction: canonical intent order, then a shuffle with the state's RNG.
3. The world state owns **one seeded `random.Random`** (`WorldState.rng`, seeded from the string `"pericles-world-<seed>"`). Its full state is part of every snapshot. Map generation uses its own `random.Random(seed)`. Nothing in `core` uses module-level `random` functions, the wall clock, `uuid` or `secrets`.
4. State and event identity is defined by **canonical JSON** (sorted keys, compact separators, no NaN) hashed with SHA-256 (`digest`). Determinism tests compare digests.
5. An event's `tick` is the tick being processed. After `step`, `state.tick` is incremented, so a state with `tick == T` has processed ticks `0 … T-1`, and a snapshot at `T` pairs with log events `tick < T`.
6. **Modifier stacking order.** Matching modifiers apply in the order set → add → mul; within each op the given list order is kept; among `set` modifiers the last one wins; adds sum; muls multiply.

## Consequences

+ Fast ticks; exact replay comparisons by digest; precise content errors almost for free.
− In-place mutation means a crashed `step` leaves an inconsistent in-memory state. Recovery is always via the last snapshot (REQ-EXP-003 AC3).
− pydantic becomes part of the core's public surface (content model types).
- Amends spec §3.2 and the `step` signature quoted in REQ-SIM-002's statement; the acceptance criteria are unchanged.
