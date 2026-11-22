# ADR-0005: Data-driven content packs and a generic modifier system

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

The experimenter wants to extend the world later (for example a school or engineer's hut where villagers research technologies that make work faster or cheaper). Hard-coding buildings and recipes would make every addition a code change.

## Decision

Resources, items, actions, recipes, buildings, technologies and traits are defined in YAML content packs, validated (schema + referential integrity) and loaded into a registry. The engine implements only generic concepts. A **modifier** `(selector, attribute, op, value, scope, source)` is the single mechanism through which tools, skills, technologies, laws, seasons and god powers alter the world. Technologies are unlocked by research recipes at research buildings.

## Consequences

+ New content without engine changes; tech tree grows on the backlog.
+ Effects are inspectable and attributable to a source.
− Generic engine code is harder to write than special cases.
− Modifier stacking order must be defined and tested.
