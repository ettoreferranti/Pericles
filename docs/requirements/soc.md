# SOC: Society, Communication and Law

### REQ-SOC-001: Dialogue
Must · M3 · Proposed
- AC1: An adult can start a dialogue with villagers within `dialogue_radius`. The target may decline.
- AC2: A dialogue has at most `max_dialogue_turns` turns. Every turn is validated against the dialogue-turn schema.
- AC3: A dialogue ends with a list of structured outcomes, each from `{trade, promise, teach, couple}`. An empty list means no outcome. The engine executes or records each outcome as its own event, in list order.
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
- AC2: The latest `board_visible_posts` posts are part of every adult's perception.

### REQ-SOC-005: Meetings
Must · M3 · Proposed
- AC1: Any adult may call a meeting at an existing town hall, with a topic type `{proposal, law, election, project}` and a text.
- AC2: Invited adults decide whether to attend. Attendees give at most `max_meeting_speeches` speeches in a seeded order.
- AC3: The meeting ends with a vote by attendees. The engine resolves it by the configured voting rule (default: simple majority of attendees, ties fail).
- AC4: A meeting requires a quorum (parameter). Without one it is closed with no result.

### REQ-SOC-006: Meeting outcomes
Must · M3 · Proposed
- AC1: A passed law proposal is added to active laws with `author: villagers`.
- AC2: A passed election sets the chief role. Role effects are content-defined modifiers or permissions.
- AC3: A passed project creates a communal construction site or communal goal visible to all.

### REQ-SOC-007: Laws
Must · M3 · Proposed
- AC1: A law has id, text, author, enacted tick and an optional enforcement hook and violation predicate.
- AC2: The text of every active law is included in the prompt context of every adult.
- AC3: Laws can be added, amended or repealed by experimenter interventions or meeting outcomes, each with an event.

### REQ-SOC-008: Enforcement hooks
Must · M3 · Proposed
- AC1: The hook vocabulary includes at least `tax`, `forbid`, `quota` and `penalty`, each with a defined schema.
- AC2: `forbid` makes the engine reject matching intents with reason `forbidden_by_law:<id>`.
- AC3: `tax` transfers the configured share of matching transfers or production to the beneficiary.
- AC4: An unknown hook type is rejected when the law is created.

### REQ-SOC-009: Violation detection
Must · M3 · Proposed
- AC1: For a law with a violation predicate, every matching event emits a `law_violation` event, for both enforced and told-only laws.
- AC2: An optional LLM-judge pass classifies possible violations of laws that have no predicate. Its results are logged in a separate stream and never affect the simulation.

### REQ-SOC-010: Opinions
Must · M2 · Proposed
- AC1: Each adult keeps a trust score in [-1, 1] and a short note per known villager.
- AC2: Opinions are updated by reflection outputs and by built-in event rules (e.g. promise broken → trust decrease).
