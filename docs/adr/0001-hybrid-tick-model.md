# ADR-0001: Hybrid tick-based time model

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

Local LLMs need roughly 0.5–5 s per decision. With 30–150 villagers, a real-time world where every villager thinks continuously is infeasible. A fully turn-based world is reproducible but slow, and it is wasteful because most moment-to-moment actions (walking, chopping) need no reasoning.

## Decision

The world advances in fixed, seeded, deterministic ticks. Villagers consult the LLM only at *decision points* (plan step done or failed, urgent need, conversation, meeting, notable event, idle, periodic re-plan). Plain code carries out the low-level actions. Two run modes: **wait-for-LLM** (the tick blocks until all due decisions return; reproducible, the default for experiments) and **live** (villagers continue their previous plan until a new decision arrives; not reproducible, flagged in run metadata).

## Consequences

+ Results are independent of hardware speed in wait mode.
+ Far fewer LLM calls than per-tick prompting.
− Wall-clock speed is bounded by the slowest pending decision.
− Requires a clear decision-trigger design (see ADR-0003).
