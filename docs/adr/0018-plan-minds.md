# ADR-0018: Plan minds

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md) §5
- **Builds on:** ADR-0003 (plan, execute, reflect), ADR-0016 (agent layer), ADR-0017 (gateway)

## Context

M2b gives villagers with a `model:` an LLM mind (REQ-AGT-001…005, 009, 010). The gateway batches requests by model (ADR-0017), so minds must ask for many villagers at once, not one villager at a time. Runs must replay bit-exactly and resume mid-plan. On 2026-11-26 the user decided two things. Urgent needs are a re-plan trigger rather than a scripted reflex. Plan steps use village-job actions, not tiles and node ids.

## Decision

1. **One `PlanMind` per model key, batched.** Before minds decide, `Controller.intents` passes each planner (a mind with `prepare`) all its due adults in id order. `prepare` advances their plans, collects triggers, and makes one `complete_all` call per retry round. `decide` returns the prepared decision. Children and adults without a model keep the scripted minds.
2. **Triggers** (REQ-AGT-001). These fire now:
   - `idle`: no plan, or the plan has finished.
   - `step_completed` and `step_failed`.
   - `need`: a relief's level rose to its `act_at`, or to its `urgent_at`, since the last check. The `urgent_at` crossing was added on 2026-11-27, after a live run in which a villager rested through critical hunger and starved.
   - `periodic`: `replan_hours` have passed since the plan was made.

   They are checked only for due villagers. `agents.triggers` enables a subset, which must include `idle`. The default is every trigger except `step_completed` (amended 2026-11-27, user decision). With it on, each finished step asked again and the new plan replaced the old one from its first step, so a six-step plan cost up to six calls and models tended to restart it. Off, a finished step starts the plan's next step, and the villager asks when the plan ends, a step fails, a need fires or `replan_hours` pass. The cost is that good news mid-plan, such as a neighbour finishing a store, waits for one of those. Conversation, meeting, law and god-event triggers arrive with those features (M3, M4).
3. **Actions** (REQ-AGT-003/004): `gather <item>`, `eat [food]`, `sleep`, `rest [hours]`, `go_home`, `move_in`, `court <villager>`, `store [item]`, `take <item>`, `build <building>`, `craft <recipe>`, `research <technology>`. `qty` is optional (a count, or hours for `rest`). The catalog lists each villager's valid targets now, and a plan whose step names another target is invalid. The executor turns a step into intents with the scripted helpers (nearest node, store, site, workplace). The step ends when its goal holds, or fails with a reason. Sites the executor places are communal, as in ADR-0016.
4. **Prompt** (REQ-AGT-002).
   - **Sections, in order:** identity and time, traits, needs, current plan and triggers, belongings, family, nearby, village stores, recipes and costs, actions.
   - **Perception:** limited to `perception_radius` Manhattan steps, plus the stores the villager may use.
   - **Token count:** estimated as `ceil(chars / chars_per_token)`.
   - **Trimming:** over `prompt_budget_tokens`, the builder removes the last line of the lowest-ranked trimmable section until the prompt fits or nothing trimmable remains. The order is recipes and costs, then nearby (farthest first), then stores, then family, then belongings.
   - **Never trimmed:** identity, traits, needs, plan and actions.
   - **`plan.v2`** (amended 2026-11-27, after the first live run). Identity gives a life stage (child, adult, elder) instead of calendar years, which made adults read as "6 years old". Each need line names what relieves it, and for eating the level it works from. `rest` says it relieves no need. In the live run on `plan.v1`, about half the plans rested to cure fatigue, and 36 eat steps failed as "not hungry". `plan.v1` stays loadable.
5. **Invalid output** (REQ-AGT-005). An output is invalid when it does not parse, breaks the schema, or names an action or target outside the catalog. It is retried up to `max_retries` times, with the error fed back in the versioned retry template. After that, or on a live-mode backend error (REQ-LLM-009 AC2, flagged), the villager uses the scripted mind for `fallback_hours`, then plans again. A plan that yields no action when adopted starts the same window.
   - **No-progress guard** (amended 2026-11-27). The engine can reject the first intent of a plan that is valid when adopted, for example with building_full or carry_limit. Each rejection fails the step on the next tick, the model tends to repeat the plan, and before this guard that meant one call every tick or two per villager. Now, when a villager is due to ask and its plan has a failed step, no completed step, and is younger than `agents.stall_hours`, the villager gets the same fallback window ("the plan made no progress") instead of asking. `pending` keeps `step_failed`, so the ask after the window gives the reason. A plan that completed a step, or that failed after `stall_hours`, asks as before. Steps done on the adoption tick don't count as progress, because they changed nothing in the world.
   - **Bound on calls.** A failure sooner than `stall_hours` costs a `fallback_hours` window, and a later failure took at least `stall_hours`. So each villager makes at most about one call per `min(stall_hours, fallback_hours)`. Its default is 1 hour, equal to `fallback_hours`, which caps a villager whose plans keep failing at about one call per in-game hour. A failure an hour or more after adoption reflects real work, so it may re-plan at once.
   - **Executor checks.** The executor also avoids the two rejections it can predict. `workplace` skips complete buildings that have no free worker slot. It counts workers as the engine does: activities of kind action, recipe or research targeting the building, at or above its `workers`. `craft` fails at once when the outputs would not fit `carry_limit` after the inputs are used. It uses the engine's `fits` check. `eat` fails with "not hungry" below its `act_at`, and a bare `rest` lasts `agents.rest_hours`.
6. **Agent events.** Minds report `plan_made`, `plan_invalid`, `plan_step` and `mind_fallback`. The runner appends them to the tick's events in the event log, after the engine's, with the sequence numbers continuing. They are part of the digest, so replays compare decisions as well as outcomes.
7. **Snapshots.** Planner state (plan, step index, step progress, pending triggers, need levels at the last check, fallback window) is saved in the agents blob under `minds.<model>`, so a resumed run continues the same step.
8. **Templates** (REQ-AGT-010). Templates are files `prompts/<version>.{system,user,retry}.txt`, using `string.Template`. `agents.plan_template` picks the version. The version is recorded in `meta.json` (`templates.plan`), in `plan_made` events and in the call log. A test rejects the phrases in `agents.steering_phrases`.
9. **Seeds.** Each request's seed is the first 32 bits of `sha256("<run seed>:<villager>:<tick>")`. Retries reuse the seed. Their messages differ, so their cache keys differ.
10. **Traits** (REQ-AGT-009). A population entry that leaves out `traits` gets `agents.drawn_traits` distinct traits, drawn with an RNG seeded from the run seed and recorded in the resolved config. The default is 0, which keeps today's experiments unchanged.

## Consequences

+ One call per model per retry round per tick. Replays and resumes are exact, and the decisions themselves are in the log.
+ Job-level actions keep prompts short and plans valid even with small models.
− The executor duplicates a little of the scripted rules' sequencing (fetch, deliver, construct).
− REQ-AGT-002 AC1 cannot be complete until memories, opinions (M2c), laws, sanctions and the board (M3) exist.
