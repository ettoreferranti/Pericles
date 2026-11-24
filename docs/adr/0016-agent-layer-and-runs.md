# ADR-0016: Agent layer, scripted villagers and running villages

- **Status:** Accepted
- **Date:** 2026-11-24
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

M1d closes milestone M1: villages that run on their own (REQ-AGT-008, REQ-SIM-016 AC1, REQ-EXP-003, REQ-NFR-003, part of REQ-EXP-001). The spec (§3.1, §5.5) puts minds, the executor and the scripted child and fallback behaviour in `pericles.agents`. The engine only accepts intents. On 2026-11-24 the user chose a "village builder" scripted AI as the baseline for later LLM experiments, Parquet metrics, and an opt-in performance test.

## Decision

1. **Controller and minds.**
   - A `Controller` turns world state into intents once per tick, before `Engine.step`.
   - A *mind* has one method, `decide(view, villager) -> Decision | None`. A `Decision` holds the intent, the target it is about (a node, building, villager or placement claim) and the job (an action id) if any.
   - Children always use the child mind.
   - An adult uses the mind registered for its `model`. With no mind registered, or `model` unset, it uses the scripted mind.
   - A mind that raises `MindFailure` falls back to the scripted mind, and the controller counts the fallback (REQ-AGT-008 AC2). The M2 LLM mind plugs in here.
2. **Due villagers and memory.**
   - The controller asks for a decision only for a *due* villager: one with no activity, no path and no idle time left. A need level at its `urgent_at` level makes a villager due even while it has an activity or a path, but never inside its idle window. `idle_ticks` is short, and the rule stops an urgent villager from re-sending a rejected untargeted intent every tick.
   - The controller never sends an intent that repeats what the villager is already doing. Examples are a `MoveTo` to the end of its current path, or a `StartAction` for its current action and target. Such an intent would restart the work.
   - Per villager it remembers:
     - `target` and `job` of the last decision.
     - `idle_until`, set after a `Wait` or a rejection with no target.
     - `avoid`, mapping a target to a tick. A rejected intent or failed move adds the decision's target here for `avoid_ticks`.
   - This memory is part of every snapshot.
3. **Scripted decisions are stateless rules over a read-only `View`.**
   - Each rule looks at the world and the controller memory and returns a decision or nothing. The first rule that fires wins.
   - Adult order: eat → sleep → shelter → couple → home → deliver → deposit → build → work → wait.
   - Child order: eat (inventory or store, else forage near the parent) → sleep → shelter → follow a parent → deposit → forage near the parent → wait.
   - Needs are found by their `relief` kind. Thresholds are `act_at[relief]` and `urgent_at[relief]`.
   - The `View` keeps a grid index of nodes by kind, because nodes never move, and caches its per-tick queries.
4. **The village plan is derived, not stored.**
   - **Food demand** is the shortfall of the nutrition held in buildings' storage below `food_reserve_per_capita` × population, as a fraction. Each villager counts the food in the stores it can fetch from: complete buildings with storage that it may use and does not avoid. Food in villagers' inventories does not count, because children can only eat from hand or from a store.
   - **Material demand** is 1 for every item an unfinished site still needs.
   - **Choosing a job.** A villager takes the doable node action with the highest `demand / (1 + others on that output) × (1 + skill_weight × skill / max_skill)`. Ties go to the action id. The villager then goes to the nearest unavoided node with stock.
   - **Houses.** When the beds wanted outnumber free communal housing plus the housing of open house sites, one villager places a communal `house_building`. Beds wanted are the homeless villagers' beds plus one for each couple that does not share a complete home with a free bed, since conception needs one.
   - **Storehouse.** When communal storage is below `storage_per_capita` × population, one villager places a communal `store_building`.
   - At most one villager claims each placement, recorded as target `place:<kind>`.
   - Sites are supplied by whoever carries what they need. Up to `max_builders` villagers build each site once its materials are in.
   - **Couples.** Unpartnered adults of a compatible sex (exactly one of the pair has `bearing_sex`) propose to the nearest free candidate and accept proposals made to them.
   - **Homes.** Homeless villagers, and partners living apart, move into a house with room, preferring the partner's. A couple that shares a house with no spare bed moves together into the nearest other house with beds for both and one to spare (ties to the lower id). One partner moves first, and the other then follows as a partner living apart.
5. **Experiment file.**
   - `experiment.yaml` has the sections `seed`, `packs`, `map`, `population`, `run`, `engine` and `agents`.
   - `engine` and `agents` override the packaged `default_settings.yaml` key by key. A given `calendar` replaces the default calendar whole.
   - The run directory's `config.yaml` is the *resolved* experiment: every engine and agent value, with absolute pack paths. A run can be continued from its directory alone.
   - Villagers start on the walkable start-area tiles nearest the map centre, born `age_days` before tick 0.
6. **Metrics come from the config and the event log only** (ADR-0004).
   - `pericles.analysis.metrics.daily_survival` produces one row per day and metric: population, adults, children, births, deaths, deaths by cause, and food eaten.
   - The rows go to `metrics.parquet` in long format, with columns `day`, `metric` and `value`.
   - Metrics are recomputed from the whole log at the end of every run or resume, so they never drift from it.
   - They run through the current tick's day. The last row is the village at the start of the current day: the day the run stopped on, with that day's counts so far.
7. **Durable run directories.**
   - Snapshots are written to a temporary file, fsynced, renamed, and the directory fsynced.
   - A snapshot holds `{"world": …, "agents": …}`.
   - Resume walks snapshots newest first. It skips files that do not parse or whose tick does not match their name, and snapshots ahead of the event log. It restores the first usable one and truncates the log to it.
   - The run-directory schema version becomes 3.
8. **Performance.** REQ-NFR-003 is checked by `tests/pericles/test_perf.py`, marked `perf` and excluded by default like `slow`, and by `pericles_tools.bench`. Both run on the user's Mac, not in CI. Optimisations must leave the event digest of a pinned scripted run unchanged.

Amended on 2026-11-24, during the M1d baseline-village tuning (Task 10). Food demand counts stored food only, houses are wanted for couples without a free bed (and such a couple moves into one together), and a hungry child forages before it sleeps. Without these, the baseline village never had room for a child, and its children starved in winter.

## Consequences

- Scripted villagers make no random choices, so similar villagers in similar places choose alike. Demand-weighted job choice and the "others on this output" term spread them across jobs.
- Agent memory adds a small, versioned part to snapshots. Old run directories (schema 2) are rejected with a version error.
- `pericles.analysis` depends only on the event schema, so the M4 analysis can read any run directory without the engine.
- The scripted village does not farm, craft or research in M1d. Those rules can be added as more rules later without changing the controller.
