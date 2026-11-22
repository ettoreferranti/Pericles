# ADR-0009: Dialogue, town-square board and meetings from v1

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

Barter, cooperation, leadership and collective decision-making all depend on communication. Communication is also the most LLM-expensive feature. The owner wants collective decision-making from the start.

## Decision

v1 includes (1) pairwise or small-group **dialogue** between nearby villagers, capped in turns and ending in a structured outcome (trade, promise, teaching, couple formation, nothing); (2) a public **town-square board**; (3) **village meetings** at the town hall, called by any adult, with capped speeches and a **vote** whose result the engine resolves (pass a law, elect a chief, approve a communal project).

## Consequences

+ Politics and institutions can emerge.
− High LLM cost; turn caps and attendance choices are essential parameters.
− Requires a robust mapping from free text to structured outcomes.
