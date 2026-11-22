# AGT: Agent Minds

### REQ-AGT-001: Decision triggers
Must · M2 · Proposed
- AC1: An adult's mind requests an LLM plan only on these triggers: plan step completed, plan step failed, need over threshold, conversation request, meeting call, law change, god event within radius, idle, periodic re-plan.
- AC2: No LLM call happens on a tick where none of the triggers fired for that villager.
- AC3: The trigger kind is recorded with each decision event.

### REQ-AGT-002: Prompt builder
Must · M2 · Proposed
- AC1: The prompt contains identity and traits, needs, inventory and property, perception, known recipes and costs, active laws, retrieved memories, opinions of the villagers involved, current goals and plan, and recent board posts.
- AC2: Perception is limited to `perception_radius` plus the village store summary. No hidden state is leaked.
- AC3: The prompt stays under a configured token budget (default 2000) by trimming lower-priority sections in a documented order.
- AC4: Prompts are deterministic for a given state (same state → same prompt bytes).

### REQ-AGT-003: Plan output
Must · M2 · Proposed
- AC1: A plan is `{goal, steps:[{action, target, qty}], reason}`, validated against its schema.
- AC2: Every step's action exists in the valid-action catalog given in the prompt. Otherwise the output is invalid.

### REQ-AGT-004: Executor
Must · M2 · Proposed
- AC1: The executor turns each plan step into engine intents (pathfind, act, haul) without LLM calls.
- AC2: A step that the engine rejects, or that becomes impossible, marks the step failed with a reason and fires the `step_failed` trigger.
- AC3: A completed plan fires the `idle` trigger.

### REQ-AGT-005: Invalid output handling
Must · M2 · Proposed
- AC1: Invalid output (unparseable, schema-invalid, invalid action) is retried up to `max_retries` (default 2), with the validation error included in the retry prompt.
- AC2: After the retries are exhausted, the utility-AI fallback produces the next action.
- AC3: Every invalid output, retry and fallback is logged with model and reason.

### REQ-AGT-006: Memory
Must · M2 · Proposed
- AC1: Notable events involving or perceived by a villager are stored as memories with tick, text, importance and embedding.
- AC2: Retrieval returns the top-K memories by a documented score combining recency, importance and relevance.
- AC3: Memory retrieval works with a deterministic fake embedder in tests.

### REQ-AGT-007: Reflection
Must · M2 · Proposed
- AC1: Once per in-game day (parameter), each adult performs a reflection call producing durable memories, opinion updates and goal revisions.
- AC2: Reflection outputs are validated and applied atomically. Invalid reflection is skipped and logged.

### REQ-AGT-008: Scripted behaviour
Must · M1 · Proposed
- AC1: A utility-AI behaviour exists that keeps a villager alive (eat when hungry, sleep when tired, work by skill otherwise).
- AC2: It is used for children, as the LLM fallback, and for an all-scripted baseline experiment.

### REQ-AGT-009: Personality
Should · M2 · Proposed
- AC1: Each villager has traits from the content pack, assigned per config or drawn with the seeded RNG, and they are included in prompts.
