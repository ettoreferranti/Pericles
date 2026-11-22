# ADR-0007: Laws as natural-language text with optional enforcement hooks

- **Status:** Accepted, amended by [ADR-0011](0011-detection-reputation-sanctions.md)
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

The experimenter wants to change both engine parameters and social rules. A central research question is whether societies follow laws that are only told to them as readily as laws that are mechanically enforced.

## Decision

Rules are (a) engine parameters and (b) laws. A law has text that is injected into every adult's prompt, and optionally an **enforcement hook** from a fixed declarative vocabulary (`tax`, `forbid`, `quota`, `penalty`, …) and a **violation predicate** over events. Violations are logged for both told-only and enforced laws. Where no predicate exists, an optional LLM-judge pass classifies violations, and it never affects the simulation. Villagers can pass laws in meetings. A hook is attached only if the proposal maps onto the vocabulary.

## Consequences

+ Enforced vs. told-only becomes a measurable variable.
− The hook vocabulary limits what can be enforced; it will grow over time.
− LLM-judge classifications are noisy and kept separate from ground-truth events.
