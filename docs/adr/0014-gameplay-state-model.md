# ADR-0014: Gameplay state model

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

M1b gives villagers work: inventories, resource nodes, actions, tools, skills, buildings, stores, recipes and research (REQ-SIM-007…-014, REQ-SIM-018, REQ-ECO-001). Several mechanics are underspecified in the spec, and the item-conservation invariant (REQ-SIM-018) needs an exact contract for how items appear and disappear.

## Decision

1. **Work is an activity.** A villager has at most one `Activity`: an action, recipe, research or construction.
   - Inputs are *reserved* when the activity starts (moved out of the inventory), *consumed* when it completes, and *returned* if it is interrupted.
   - Work progresses in the tick it starts. It takes `ceil(work / speed)` ticks.
2. **Work speed** is the `work_speed` attribute resolved through the modifier system (base 1). The contributions are:
   - the world's modifiers;
   - the modifiers of each held tool that the work requires or that targets the work, using the first, most worn, instance of each tool item;
   - trait modifiers;
   - an `add` of `skill level × skill_speed_per_level` for the work's skill.
   - Tool wear uses the tools held when the work started or was used, computed before any outputs are added, so a tool produced by the work is never worn by that same work (`work.finish` takes the list of tools).
   - Building work counts as a tool use: on completion each builder's applicable tools lose 1 durability (breaking emits `tool_broken` with `destroyed`). Builders interrupted before completion wear nothing.
3. **Interruption.** Any new intent from a working villager first interrupts the current work (cause `actor`). The interruption happens before the new intent is validated, so an intent that is then rejected still ends the old work. The engine interrupts work it can no longer finish (cause `engine`). `Engine.interrupt` exists for interventions by other villagers (cause `intervened`, REQ-SOC-022).
4. **Item ledger.** Items are created or destroyed only by events that carry `created` and/or `destroyed` bundles. Transfers between containers (inventories, reserved inputs, delivered materials, stores) carry neither. The invariant checker compares container totals before and after each tick against these bundles.
5. **Resource nodes.**
   - A node's stock counts units of its yield item. A node action must output that item (registry rule).
   - Harvesting takes the action's yield output from the stock, capped by the remaining stock and by what the villager can carry. The action's other outputs are capped by what can be carried.
   - Regrowth is applied once per in-game day and accumulates fractions, up to the node's maximum.
6. **Locations.** "At" a node or building means within Manhattan distance 1 of the node's tile, or of any tile in the building's footprint.
7. **Buildings.**
   - A building occupies its footprint from the moment its site is placed.
   - The footprint of a building without an entrance is not walkable, and such a site cannot be placed on a villager.
   - Construction completes when every cost item has been delivered and every unit of build work is done. The delivered materials are then destroyed into the structure.
   - The pathfinding cost field is cached on the tilemap's identity plus the building layout, the (id, kind, origin) of every building, so the tilemap must be replaced rather than changed in place. Paths found on a cost field are remembered for the rest of the in-game day, keyed on (start, goal), and dropped when the cost field or the day changes. A cost field also keeps, per tile, its passable neighbours and their costs, worked out on first use; this is sound because a field's costs never change (the layout is part of its key). All of these are rebuilt from the world state alone, so a resumed run finds the same paths.
   - These caches rely on four invariants. A building's id, kind and origin never change after it is placed. Blocked tiles derive only from those. Cost fields are pure: a tile always costs the same. The tilemap is replaced, never changed in place.
   - Recipes and research at a building allow at most its `workers` simultaneous workers. Actions located at a building count against the same limit when its `workers` is above 0 (0 means no limit for actions; recipes and research at such a building are never possible). Construction has no limit; build speed is `work_speed` resolved against the target `building`.
   - Construction can start only once every cost item has been delivered.
8. **Ownership** is `personal(owner)`, `shared(owners)` or `communal`. Every take from a store emits `item_taken`. A take by a villager who is not an owner of a personal or shared store also emits `take_unowned`. A communal store is owned by every villager, so it never produces `take_unowned`; laws (M3) decide whether such takes are theft.
9. **Knowledge** is a set of content IDs held by each villager and by the village.
   - Completing research adds the technology's ID and the IDs it unlocks.
   - A recipe or building that some technology unlocks is locked until the villager, or the village, knows it.
   - An action with `requires.knowledge: true` needs its own ID in the villager's or the village's knowledge. Teaching (M2) is how that knowledge spreads.
   - Research with `scope: village` unlocks for everyone and adds its modifiers globally. Otherwise it unlocks for the researcher, with villager-scoped modifiers.
   - Research speed is the `research_speed` attribute, resolved against the target `building` and the research building's kind.
10. **Seasons and defaults.**
    - Seasons carry the action tags they block.
    - The core default calendar is a single neutral season. The playable default (four seasons, with winter blocking `sowing`) lives in `pericles.experiment.defaults`, so the engine holds no game knowledge.
11. **Farming in v1** is a single `farm_grain` action at a farm, not the sow/tend/harvest cycle sketched in spec §4.2. The cycle can be added later as content plus a crop-growth mechanic.

Amended on 2026-11-24, during the M1d performance work (Task 11, REQ-NFR-003). The cost field was keyed on the set of blocked tiles, and that set was rebuilt for every move. It is now keyed on the building layout, from which the blocked tiles derive, and paths are remembered per cost field and day. Neither change alters any result: the pinned scripted-run digests are unchanged.

Amended on 2026-11-25 (Task 11b, REQ-NFR-003): each cost field now also keeps every tile's passable neighbours for A*, filled lazily. It adds no key, since a field's costs are fixed. The pinned digests are unchanged.

## Consequences

+ One mechanism (activities plus modifiers) serves every kind of work. Interruption is uniform.
+ Conservation can be checked mechanically on every tick.
− Interrupting is lossless, so the cost of an interruption is only the time spent.
− Farming is simplified, and spec §4.2's sow/tend/harvest row is deferred (amended here).
