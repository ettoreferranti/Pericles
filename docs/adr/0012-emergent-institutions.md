# ADR-0012: Emergent institutions from generic building blocks

- **Status:** Accepted (amends ADR-0011: default enforcement mode)
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

The experimenter wants to observe whether institutions such as police emerge on their own: villagers notice theft, decide to pay someone to patrol, and give that person powers. With ADR-0011, villagers could notice and discuss theft, but there was no way to create a paid role, no guard or patrol action, no recurring payment, no way to stop an act in progress, and owners could not notice unwitnessed losses. Also, the default `on_detection` mode applied penalties automatically as soon as anyone witnessed a violation. That made human enforcement redundant.

## Decision

1. The engine defines **no named institutions** (the hard-coded "chief" is removed). Villagers build institutions from generic primitives: **offices** (duties as text, holders, pay, term, permissions, removal by vote), **contracts** (recurring obligations, with breach detection), **permissions** from a fixed vocabulary (`confiscate`, `fine`, `ban`, `detain`, `spend_communal`), **watch actions** (`guard`, `patrol`, `follow`, `keep_watch`), **intervention** (interrupting another's multi-tick action) and the **communal store as a treasury**.
2. **Loss discovery:** owners notice unexplained decreases in their stores without learning the culprit.
3. The enforcement mode `none` is replaced by **`by_villagers`**, which becomes the **default**. The engine records violations but applies no penalty. Only villagers impose sanctions. (`none` and `by_villagers` would have behaved identically, because villager sanctions are always available, so they are merged.)
4. Office duties are never enforced by the engine. Neglect and abuse of office are possible and measured against ground truth.

## Consequences

+ Police, courts, tax collectors, guilds, and also corruption and protection rackets, can emerge and be compared across models and rule sets.
+ Every institution is attributable to specific meetings, votes and contracts in the event log.
− Without automatic enforcement, early runs may be lawless. That is intended, and `on_detection` / `certain` remain available per law.
− More LLM context (offices, contracts, duties) and more meeting types; prompt budgets must be watched.
− Permissions are a capability system the engine must enforce correctly (security-like testing).
