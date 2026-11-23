# SIM: Simulation World

### REQ-SIM-001: Seeded map generation
Must · M1 · Implemented
The engine generates a tile map from a seed and map parameters (size, terrain proportions).
- AC1: The same seed and parameters produce an identical map (equal hash).
- AC2: Different seeds produce different maps (with overwhelming probability).
- AC3: The map contains every terrain type requested with a non-zero proportion, within ±5% of the target proportions.
- AC4: All walkable tiles of the starting area are mutually reachable.

### REQ-SIM-002: Deterministic tick loop
Must · M1 · Implemented
The engine advances by `step(state, intents, rng) → (state', events)`.
- AC1: Identical state, intents and RNG seed yield identical `state'` and events.
- AC2: Intents submitted in any order within a tick are resolved in a seeded order, so the outcome does not depend on submission order.
- AC3: Each tick advances in-game time by `tick_minutes` (parameter, default 1).

### REQ-SIM-003: Day/night and seasons
Must · M1 · Accepted
- AC1: The day length and season lengths are parameters. The current time of day and season can be derived from the tick.
- AC2: In winter, sowing actions are rejected and the food and warmth need rates are multiplied by the winter modifier.

### REQ-SIM-004: Pathfinding
Must · M1 · Implemented
- AC1: A* returns a shortest-cost path between reachable tiles, taking the movement cost per terrain into account.
- AC2: An unreachable target returns a "no path" result. It never raises an error or loops.
- AC3: Water and buildings without an entrance are not walkable.

### REQ-SIM-005: Content packs and registry
Must · M1 · Implemented
Resources, items, actions, recipes, buildings, technologies and traits are loaded from YAML content packs.
- AC1: A pack is validated against a schema. Invalid packs are rejected with a message naming the file, path and problem.
- AC2: Referential integrity: every referenced id exists. Dangling references are rejected.
- AC3: Several packs can be layered. Later packs may add or override ids, and the override is logged.
- AC4: The engine contains no hard-coded building, recipe or resource ids, except where the base pack is loaded in tests.

### REQ-SIM-006: Modifier system
Must · M1 · Implemented
A modifier is `(selector, attribute, op ∈ {add, mul, set}, value, scope, source)`.
- AC1: Modifiers apply to actions, recipes, buildings, needs or yields that match their selector.
- AC2: The stacking order is deterministic: all `set`, then all `add`, then all `mul`. This is documented and tested.
- AC3: Every effective value can be explained as its base value plus the list of contributing modifiers and their sources.
- AC4: Scoped modifiers (villager, building, global, time-limited) expire or apply correctly.

### REQ-SIM-007: Resource nodes
Must · M1 · Implemented
- AC1: Harvesting a node reduces its stock by the harvested amount and never goes below 0.
- AC2: A node regrows at its configured regrowth rate up to its maximum.
- AC3: A depleted node rejects harvest intents with the reason `depleted`.

### REQ-SIM-008: Actions
Must · M1 · Implemented
- AC1: An action takes `duration × modifiers` ticks. The outputs are produced only when it completes.
- AC2: An action is rejected if a required tool, skill, knowledge, input or location is missing, with a specific reason.
- AC3: An interrupted action produces no outputs and returns any inputs that were not consumed. Interruption can come from the actor, from the engine, or from another villager's `intervene` (REQ-SOC-022).

### REQ-SIM-009: Buildings and construction
Must · M1 · Implemented
- AC1: Placing a construction site requires valid terrain and a free footprint.
- AC2: Construction completes when all cost items have been delivered and all build work has been done.
- AC3: A completed building provides its declared capacity, storage, housing and hosted recipes.
- AC4: The v1 base pack includes: house, storehouse, farm, fishing hut, lumber camp, quarry, mine, smithy, mint, town hall, palisade and school.

### REQ-SIM-010: Recipes and tools
Must · M1 · Implemented
- AC1: A recipe at a building consumes its inputs and yields its outputs after its work time.
- AC2: Tools apply their modifiers while held, and lose durability per use. A tool at 0 durability is destroyed.

### REQ-SIM-011: Technologies and research
Should · M1 · Implemented
- AC1: A research recipe at a research building, once completed, unlocks the technology for the researcher, or for the village if `scope: village`.
- AC2: An unlocked technology adds its modifiers and/or unlocks recipes and buildings.
- AC3: The base pack ships at least 2 sample technologies researchable at the school.

### REQ-SIM-012: Villager needs
Must · M1 · Accepted
- AC1: Hunger, energy and warmth change per tick at their (modified) rates.
- AC2: A villager whose hunger reaches 100 loses health at the starvation rate. At health 0 they die with cause `starvation`. Cold works the same way (cause `cold`).
- AC3: Eating consumes food items and reduces hunger by each item's nutrition value. Sleeping in a house restores energy faster than sleeping outdoors.

### REQ-SIM-013: Inventory and carrying
Must · M1 · Implemented
- AC1: An inventory never holds a negative quantity of any item.
- AC2: Carried weight never exceeds the carry limit. An intent that would exceed it is rejected or capped, as specified per action.

### REQ-SIM-014: Skills
Should · M1 · Implemented
- AC1: Performing an action increases the matching skill by the practice rate, up to the maximum.
- AC2: Skill level applies a work-speed modifier for the matching actions.

### REQ-SIM-015: Couples and births
Must · M1 · Accepted
- AC1: Two adults can be recorded as a couple only through a mutual-consent outcome.
- AC2: A child is born after `gestation_days` if the couple has a house with free capacity and the village food stock is at or above the threshold. Otherwise pregnancy does not start.
- AC3: Birth-rate parameters allow population doubling within a configurable number of in-game days in good conditions (Timberborn-like growth).

### REQ-SIM-016: Children and coming of age
Must · M1 · Accepted
- AC1: Children run on scripted behaviour (stay near a parent, eat, light gathering) and never cause an LLM call.
- AC2: At `adult_age`, a child becomes an adult agent. Its model is assigned by the configured rule (default: one parent's model, chosen with the seeded RNG).
- AC3: The new adult's memory is seeded from the notable events it witnessed.

### REQ-SIM-017: Death
Must · M1 · Accepted
- AC1: Death causes include starvation, cold, old age, raid and epidemic, each recorded in the death event.
- AC2: Past `old_age`, the death probability per day follows the configured curve.
- AC3: A dead villager's inventory and property are handled by the inheritance rule (default: partner, then children, then communal).

### REQ-SIM-018: Engine invariants
Must · M1 · Accepted
- AC1: Items are conserved. Item totals change only through recipes, harvests, consumption, decay, god powers and interventions, each with an event.
- AC2: Invariant checks run in tests (property-based) and in debug mode on every tick.
