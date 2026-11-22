# ADR-0008: Requirements traceability and mutation testing

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

The project is an experiment platform. Wrong simulation behaviour silently corrupts research results. The owner wants tests built against requirements and mutation testing to check the tests.

## Decision

Requirements live in `docs/requirements/` with stable IDs (`REQ-<AREA>-NNN`) and acceptance criteria. Tests declare what they cover with `@pytest.mark.req(...)`. A script generates a traceability matrix, and CI fails if an accepted requirement has no tests. Mutation testing uses `mutmut` (Python) and Stryker (viewer), with initial score targets ≥ 80% for `core` and ≥ 70% elsewhere. It runs incrementally on PRs and in full nightly or on demand.

## Consequences

+ Every behaviour is traceable to a requirement; weak tests are exposed.
− Mutation runs are slow; incremental scoping is required.
− Requirement documents must be kept in sync (enforced by CI).
