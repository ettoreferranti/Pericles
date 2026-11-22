# ADR-0011: Enforcement by detection, reputation and villager-imposed sanctions

- **Status:** Accepted (amends ADR-0007)
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

ADR-0007 made laws text plus optional mechanical hooks. A `forbid` hook blocked actions outright, and violations were visible only to the analyst. The experimenter wants to observe whether villagers notice rule-breaking and react to it (e.g. ostracising an outlaw), whether villagers can choose not to follow rules, and in particular whether someone facing starvation, or the death of their child, puts their own survival above the society's rules.

## Decision

1. **The engine never blocks an action only because it is illegal** (default). Enforcement is a per-law mode: `none`, `on_detection` (the default: penalty only if witnessed or reported), `certain` (penalty always, violation made public), or `block` (opt-in experimenter setting, flagged as removing agency; blocked attempts are logged).
2. **Witnessing:** adults within `witness_radius` remember the plain fact of an act, not a "violation" label. Their own model judges it. Actors know who could see them.
3. **Information spreads:** `report` and `accuse` dialogue intents and accusation posts. Hearsay is stored with its chain of sources. Accusations are scored true, false or unverifiable against ground truth, for analysis only.
4. **Reputation:** trust moves with witnessed acts and with hearsay, weighted by trust in the source.
5. **Sanctions are chosen by the villagers:** informal (refusing dialogue, trade or help) and formal, through a `sanction` meeting topic or a law penalty: fine, confiscate, ban from building or store, exile. Exiles can still survive outside the village.
6. **Law awareness spreads socially** by default (meetings, board, dialogue). `law_awareness: universal` is available as an option.
7. **Agency under duress:** prompts show the villager's own critical state and that of their partner and children. Violations are tagged `under_duress` and `unaware`. Prompts are neutral: they neither tell villagers to obey nor to break laws. Motive comes from needs and personality traits.

## Consequences

+ Rule-following, detection, gossip, false accusation, punishment and ostracism become observable and comparable across models.
+ The survival-vs-society trade-off is always available to agents (outside opt-in block mode).
+ Enforcement strength (`none` → `certain`) is an experimental variable.
− More LLM context (hearsay, family state, penalties) and more event types.
− Instruction-tuned models are biased towards obedience. Neutral prompt framing is required (REQ-AGT-010), and the obedience bias itself is a finding to report, not a bug to tune away.
− Ground truth vs. villager belief must be kept strictly separate in data and code.
