# SOC: Society, Communication and Law

### REQ-SOC-001: Dialogue
Must · M3 · Proposed
- AC1: An adult can start a dialogue with villagers within `dialogue_radius`. The target may decline.
- AC2: A dialogue has at most `max_dialogue_turns` turns. Every turn is validated against the dialogue-turn schema.
- AC3: A dialogue ends with a list of structured outcomes, each from `{trade, promise, teach, couple, report, refuse_help}`. An empty list means no outcome. The engine executes or records each outcome as its own event, in list order.
- AC4: The full transcript is logged as events.

### REQ-SOC-002: Promises
Must · M3 · Proposed
- AC1: A promise records promisor, promisee, terms and due tick.
- AC2: At the due tick, the engine evaluates fulfilment from events and emits `promise_kept` or `promise_broken`.
- AC3: Both parties' memories receive the outcome.

### REQ-SOC-003: Knowledge transfer
Must · M3 · Proposed
- AC1: A villager can teach a known recipe, building or tech to another in dialogue. After `teach_duration`, the learner knows it.
- AC2: A villager cannot teach something they do not know (rejected).
- AC3: A villager's starting knowledge is configurable per villager or group (full manual by default).

### REQ-SOC-004: Town-square board
Must · M3 · Proposed
- AC1: Any adult may post a message (length-capped). Posts are events.
- AC2: The latest `board_visible_posts` posts are part of the perception of every adult who visited the town square within `board_recall_days`.

### REQ-SOC-005: Meetings
Must · M3 · Proposed
- AC1: Any adult may call a meeting at an existing town hall, with a topic type `{proposal, law, election, project, sanction}` and a text.
- AC2: Invited adults decide whether to attend. Attendees give at most `max_meeting_speeches` speeches in a seeded order.
- AC3: The meeting ends with a vote by attendees. The engine resolves it by the configured voting rule (default: simple majority of attendees, ties fail).
- AC4: A meeting requires a quorum (parameter). Without one it is closed with no result.
- AC5: The accused in a `sanction` meeting is invited and may speak in their defence.

### REQ-SOC-006: Meeting outcomes
Must · M3 · Proposed
- AC1: A passed law proposal is added to active laws with `author: villagers`. Attendees learn it immediately (REQ-SOC-017).
- AC2: A passed election sets the chief role. Role effects are content-defined modifiers or permissions.
- AC3: A passed project creates a communal construction site or communal goal visible to all.
- AC4: A passed sanction is applied per REQ-SOC-014.

### REQ-SOC-007: Laws
Must · M3 · Proposed
- AC1: A law has id, text, author, enacted tick, enforcement mode (REQ-SOC-015), an optional penalty, an optional hook and an optional violation predicate.
- AC2: A villager's prompt contains the text of the active laws that villager knows (REQ-SOC-017).
- AC3: Laws can be added, amended or repealed by experimenter interventions or meeting outcomes, each with an event.

### REQ-SOC-008: Enforcement hooks
Must · M3 · Proposed
- AC1: The hook vocabulary includes at least `tax`, `forbid`, `quota` and `penalty`, each with a defined schema.
- AC2: `forbid` and `quota` define which actions count as violations. They do **not** block those actions unless the law's enforcement mode is `block` (REQ-SOC-015).
- AC3: `tax` transfers the configured share of matching transfers or production to the beneficiary automatically.
- AC4: An unknown hook type is rejected when the law is created.

### REQ-SOC-009: Ground-truth violation detection
Must · M3 · Proposed
- AC1: For a law with a violation predicate, every matching event emits a `law_violation` event, whatever the enforcement mode and whether or not anyone witnessed it. This is analyst-only ground truth, invisible to villagers.
- AC2: The violation event records the violator's state at the time (needs, the health of their dependents) for duress analysis (REQ-SOC-016).
- AC3: An optional LLM-judge pass classifies possible violations of laws that have no predicate. Its results are logged in a separate stream and never affect the simulation.

### REQ-SOC-010: Opinions
Must · M2 · Proposed
- AC1: Each adult keeps a trust score in [-1, 1] and a short note per known villager.
- AC2: Opinions are updated by reflection outputs and by built-in event rules (e.g. promise broken → trust decrease).

### REQ-SOC-011: Witnessing
Must · M3 · Proposed
- AC1: When an action completes, every adult within `witness_radius` (and awake) receives a memory of the plain fact (actor, action, target, items), without a "violation" label.
- AC2: An actor knows who could see them (the villagers within radius are part of their perception), so they can choose to act unseen.
- AC3: Witnessing is deterministic given the state (no randomness beyond the seeded RNG).

### REQ-SOC-012: Reports, accusations and hearsay
Must · M3 · Proposed
- AC1: Dialogue intents include `report` (tell about a third party's act) and `accuse` (claim a third party broke a law). Board posts may be marked as accusations.
- AC2: A listener stores a received report as hearsay memory, with its source and the claimed fact.
- AC3: Every accusation is checked against ground truth by the analysis (true, false, or unverifiable). The truth value is never visible to villagers.
- AC4: Hearsay can be passed on. The chain of sources is preserved.

### REQ-SOC-013: Reputation
Must · M3 · Proposed
- AC1: Trust in a villager is updated by acts witnessed (by a weight per act kind) and by hearsay received (weighted by trust in the source).
- AC2: Reputation-relevant memories about the villagers involved are prioritised in prompt retrieval.

### REQ-SOC-014: Sanctions
Must · M3 · Proposed
- AC1: Informal: a villager can decline dialogue, trade or help with anyone. Each refusal is an event with target and stated reason.
- AC2: Formal sanctions (via a `sanction` meeting or a law's penalty) include: `fine(items)`, `confiscate(items)`, `ban(building|store)` and `exile(duration)`.
- AC3: `ban` and `exile` are enforced by the engine as access rules. An exiled villager cannot enter the village core or use communal buildings for the duration. They can still survive outside (forage, hunt, fish).
- AC4: A sanction against a villager who lacks the fined items applies what they have and records the shortfall.

### REQ-SOC-015: Enforcement modes
Must · M3 · Proposed
Each law has a mode: `none | on_detection | certain | block`. Default: `on_detection`.
- AC1: `none`: violations are recorded as ground truth only. No automatic penalty.
- AC2: `on_detection`: the law's penalty is applied automatically only if the violation was witnessed by at least one adult, or reported by one within `report_window`.
- AC3: `certain`: the penalty is always applied and the violation is made public to all adults. The action itself still happens.
- AC4: `block`: the engine rejects matching intents (`forbidden_by_law:<id>`) and logs an `attempted_violation` event. This mode is opt-in, settable only by the experimenter, and flagged in the run metadata as removing agency.
- AC5: Except in `block` mode, the engine never rejects an intent only because it violates a law.

### REQ-SOC-016: Survival override (agency under duress)
Must · M3 · Proposed
- AC1: Except in `block` mode, a villager can always choose any physically possible action, including one that violates laws, to save their own life or a dependent's.
- AC2: A villager's prompt shows their own critical state and the critical state (hunger, health) of their partner and children, when known.
- AC3: Violations are tagged `under_duress` when the violator or a dependent was at or above the critical threshold at the time (REQ-SOC-009 AC2).
- AC4: Prompts neither encourage nor forbid breaking laws (see REQ-AGT-010).

### REQ-SOC-017: Law awareness
Must · M3 · Proposed
- AC1: By default, a villager knows a law if they were present when it was enacted (meeting attendee), read it on the board, or were told about it in dialogue. A law enacted by the experimenter is announced on the board.
- AC2: The config option `law_awareness: universal` makes every active law known to all adults, which was the original behaviour.
- AC3: Violations by villagers who did not know the law are tagged `unaware` in ground truth.
