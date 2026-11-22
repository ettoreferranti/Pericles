# ADR-0004: Append-only event log as the single source of truth

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

Metrics, replay, the viewer, the analysis reports and the reproducibility checks all need the same view of what happened in a run.

## Decision

The engine emits typed, versioned events for every state change, decision, LLM call and intervention into an append-only log (SQLite per run), written transactionally per tick. Periodic state snapshots allow fast seeking. All consumers derive their data from the log.

## Consequences

+ One consistent history; easy to add new metrics after the fact.
+ Replay = snapshot + events.
− The event schema becomes a contract and needs versioning and migration discipline.
− Log size must be watched (raw LLM outputs can be large; store them compressed).
