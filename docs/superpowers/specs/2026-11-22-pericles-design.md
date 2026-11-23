# Pericles — Design Specification

- **Date:** 2026-11-22
- **Status:** Draft for review
- **Owner:** Ettore Ferranti

## 1. Purpose

Pericles is a research sandbox for studying how a small society evolves under rules that the
experimenter sets and changes during a run. Every adult villager is controlled by a local LLM
(Ollama or MLX on macOS). Nobody issues orders: villagers decide for themselves what to do, whom
to trade with, what to build, and which laws to propose or break.

The primary research questions the system must support:

1. How do different LLMs compare as "minds" for a society (survival, productivity, social
   behaviour, agent reliability)?
2. How do societies respond to rules: engine parameters vs. natural-language laws, and laws that are
   enforced vs. laws that are only told?
3. What economic and political structures emerge (money adoption, inequality, leadership,
   monopolies on knowledge)?
4. How do groups driven by different models interact when they live together?

### 1.1 Scope assumptions

- Single user, running on their own machine (initially an Apple M4 Pro with 48 GB RAM). No multiplayer.
- The experiment comes first. Graphics serve observation, and at the start they are simple (AoE2-like
  low-poly 3D).
- Initial scale: 30–150 villagers. Only adults are LLM-driven.

## 2. Decisions summary

| # | Decision | ADR |
|---|----------|-----|
| 1 | Hybrid time model: fixed deterministic ticks. LLM consulted only at decision points; scripted low-level execution | ADR-0001 |
| 2 | Python simulation core + TypeScript/Three.js browser viewer over WebSocket | ADR-0002 |
| 3 | Agent architecture: plan + reactive execution + reflection (Generative-Agents style) | ADR-0003 |
| 4 | Append-only event log is the single source of truth | ADR-0004 |
| 5 | Data-driven content (YAML packs) + generic modifier system | ADR-0005 |
| 6 | LLM gateway with backend abstraction, schema validation and a response cache for reproducibility | ADR-0006 |
| 7 | Rules = engine parameters + natural-language laws with optional mechanical enforcement hooks | ADR-0007 |
| 8 | Requirements with stable IDs, test traceability, mutation testing | ADR-0008 |
| 9 | Communication: pairwise dialogue + town-square board + village meetings with voting, from v1 | ADR-0009 |
| 10 | Money = coin item minted from gold at a Mint; barter always available | ADR-0010 |
| 11 | Agency first: laws are not blocked by default; enforcement by detection; witnessing, hearsay, reputation, villager-imposed sanctions; survival-over-society always possible | ADR-0011 |
| 12 | Emergent institutions: generic offices, contracts, permissions, watch actions, intervention, treasury; default enforcement `by_villagers` | ADR-0012 |

## 3. Architecture

```
┌─────────────────────────── pericles (Python) ───────────────────────────┐
│  experiment.yaml ──► Experiment Runner ──► Sim Engine (seeded ticks)     │
│                          │                   │  world, resources,        │
│                          │                   │  buildings, needs,        │
│                          │                   │  lifecycle, economy, laws │
│                          │                   ▼                           │
│                          │            Event Log (append-only) ◄── interventions
│                          ▼                   │                           │
│                     Agent Layer ◄────────────┘ (perception queries)      │
│                     mind per adult: goals, plan, memory, opinions,       │
│                     knowledge; behaviour executor; dialogue & meetings   │
│                          ▼                                               │
│                     LLM Gateway ── Ollama / MLX backends                 │
│  Server (WebSocket) ── streams state/events, receives interventions      │
│  Analysis ── metrics from event log, comparison report (HTML)            │
└──────────────────────────────────────────────────────────────────────────┘
          ▲ WebSocket
┌─────────┴────────┐
│ Viewer (Three.js)│
└──────────────────┘
```

### 3.1 Packages

| Package | Responsibility | Depends on |
|---------|----------------|------------|
| `pericles.core` | Deterministic engine: world, tick loop, intents → validation → resolution → events, modifiers, content registry | nothing (stdlib + pydantic + PyYAML; ADR-0013) |
| `pericles.agents` | Minds, decision triggers, prompt building, executor, memory, opinions, dialogue, meetings, scripted child/fallback behaviour | `core` (read-only queries + intent submission), `llm` (interface only) |
| `pericles.llm` | Gateway, backends (Ollama, MLX, Fake), schema validation, retries, cache, call metrics | nothing domain-specific |
| `pericles.experiment` | Config loading, runner, interventions, god powers, run directory, sweeps | `core`, `agents`, `llm` |
| `pericles.server` | WebSocket API for live and replay sessions | `experiment` |
| `pericles.analysis` | Event-log readers, metric computation, comparison reports | event-log schema only |
| `viewer/` | Three.js + TypeScript (Vite) client | WebSocket protocol only |

### 3.2 Core principles

- **The engine is deterministic.** `step(state, intents)` mutates `state` in place and returns `(state, events)`; the seeded RNG is part of `state` (ADR-0013). It knows
  nothing about LLMs. Given the same seed, config, interventions and intents, it produces an identical state hash.
- **Intents, not mutations.** Agents submit intents. The engine validates them against the rules, content and
  the current state, and resolves conflicts in a seeded order. Every resolution emits events.
- **Speed-independent results.** Within a tick, the agent layer collects all due decisions before the
  engine advances. In *wait-for-LLM* mode (the default for experiments), the tick does not advance until all
  pending decisions return. In *live* mode, a villager without a fresh decision continues its previous
  plan. This mode is not reproducible and is flagged as such in the run metadata.
- **The event log is the source of truth.** Metrics, replay, viewer and reports all derive from it.
- **Reproducibility triple:** config + seed + intervention list + LLM response cache ⇒ bit-exact replay.

## 4. Simulation world

### 4.1 Map and time

- Seeded procedural tile grid (default 128×128). Terrain: grass, fertile soil, forest, rock, ore
  vein (iron/gold), water, with an elevation map for rendering.
- A* pathfinding over walkable tiles; movement cost per terrain.
- One tick = one in-game minute (parameter). Day/night cycle and seasons (parameters). Winter blocks
  sowing, increases food/warmth need.

### 4.2 Content (data-driven)

All content lives in YAML **content packs** loaded into a registry: resources, items, actions,
recipes, buildings, technologies, traits. The engine has no hard-coded knowledge of "smithy". It knows
generic concepts:

- **Resource node**: harvestable tile feature with stock and regrowth (trees, bushes, rock, ore, fish, game).
- **Action**: duration, required tool/skill/knowledge, inputs, outputs, location constraint.
- **Building**: cost, build work, capacity, the recipes it hosts, storage, housing slots.
- **Recipe**: inputs → outputs over work time, at a building.
- **Technology**: research cost (recipe at a research building) → unlocks recipes/buildings and/or adds modifiers.
- **Modifier**: `(target selector, attribute, op, value, scope, source)` e.g. `felling.work_speed × 1.2`.
  Tools, skills, techs, laws, god powers and seasons all apply effects through modifiers.

v1 base pack:

| Source | Action | Output |
|---|---|---|
| Berry bush | gather | food |
| Field (at farm) | `farm_grain` (v1, ADR-0014; sow/tend/harvest deferred) | grain (food) |
| Game animals | hunt | meat, hides |
| Water | fish | fish |
| Forest | fell | wood (trees regrow) |
| Rock | quarry | stone |
| Ore vein | mine | iron ore, gold ore |
| Smithy | smelt + forge | tools (speed up work, wear out) |
| Mint | mint | coins (from gold ore) |

Buildings v1: house, storehouse, farm, fishing hut, lumber camp, quarry, mine, smithy, mint, town
hall, palisade, plus a sample **school/engineer's hut** hosting research recipes for 2 sample techs.
This demonstrates the tech mechanism. The tree itself grows via backlog.

### 4.3 Villagers

State: name, age, sex, traits (personality seed), hunger, energy, health, warmth, inventory (carry
limit), owned property, skills (proficiency grows with practice), knowledge (known recipe/building/tech
ids), relationships (partner, parents, children), model assignment (adults).

Ownership of buildings and stock: `personal | shared(list) | communal`. Taking from a store you
do not own is a recorded event, which may be classified as theft under active laws.

### 4.4 Lifecycle

- Two adults may form a couple (an LLM decision for both, via dialogue).
- With a house that has free capacity and sufficient food stock, a child is born after
  `gestation_days`. Rate parameters allow Timberborn-like quick growth.
- Children run on a **scripted behaviour** (stay near a parent, eat, light gathering) and make no LLM calls.
- At `adult_age`, a child becomes an LLM agent. Model = inherit a parent's (default) or a config rule. Seeded with
  childhood memories derived from events they witnessed (parents, notable events).
- Death: starvation, cold, old age (probabilistic past `old_age`), raids, epidemic.

### 4.5 Economy

- **Barter:** a trade is an atomic exchange of item bundles between two villagers who agreed in dialogue.
  The engine verifies both sides hold the goods. Implied exchange rates are recorded.
- **Coins:** an ordinary item minted from gold ore at a Mint. Coins are optional. Prices, wages and taxes are
  emergent conventions or enforced law hooks.
- Whether a Mint exists at the start, and who knows minting, are run parameters.

### 4.6 Laws

A law = `{id, text, author (experimenter|villagers), enacted_tick, enforcement_mode, penalty?, hook?, violation_predicate?}`
(see ADR-0007, amended by ADR-0011).

- **Agency first:** by default the engine never blocks an action only because it is illegal. Villagers can
  always choose to break a law, e.g. steal food when they or their child are starving.
- **Hooks** come from a fixed declarative vocabulary: `tax(source_event, pct, beneficiary)` applies automatically.
  `forbid(action, condition)` and `quota(store, item, per_day)` define what counts as a violation.
  `penalty(effect)` defines the punishment.
- **Enforcement modes** per law: `by_villagers` (**default**: the engine applies no penalty; only villagers can
  sanction, through meetings, permitted office holders or informal refusal), `on_detection` (automatic penalty only if
  witnessed or reported), `certain` (penalty always, violation made public, the act still happens), and `block`
  (opt-in experimenter setting: the intent is rejected and logged as `attempted_violation`; the run is flagged as
  removing agency).
- **Law awareness** spreads socially by default: villagers know a law if they attended the meeting that passed
  it, read it on the board, or were told. Experimenter laws are announced on the board.
  `law_awareness: universal` puts every law into every prompt.
- **Ground truth vs. belief:** the engine records every violation (`law_violation`, tagged `under_duress` and/or
  `unaware`) for the analyst only. Villagers learn of acts only through **witnessing** and **hearsay**
  (§4.7). Laws without a predicate can be classified by an optional LLM-judge pass, logged separately, that never
  affects the simulation.

### 4.7 Detection, reputation and sanctions

- **Witnessing:** when an action completes, awake adults within `witness_radius` remember the plain fact
  ("Marco took 5 grain from the communal store"), not a "violation" label. Their own model decides
  whether it breaks a law. Actors see who is nearby, so they can choose to act unseen.
- **Hearsay:** `report` and `accuse` dialogue intents and accusation board posts pass information on, and the
  chain of sources is kept. Lies are possible. The analysis scores accusations true, false or unverifiable.
- **Reputation:** trust moves with witnessed acts and with hearsay, weighted by trust in the source.
- **Sanctions:** informal (refusing dialogue, trade or help: ostracism) and formal, through a `sanction`
  meeting or a law penalty: `fine`, `confiscate`, `ban(building|store)`, `exile(duration)`. Exiles can still
  forage, hunt and fish outside the village core. The accused may speak at their sanction meeting.
- **Loss discovery:** owners (and holders of an office responsible for a communal store) notice unexplained decreases
  when they use or inspect a store ("12 grain missing since yesterday"), without learning the culprit.

### 4.8 Emergent institutions (ADR-0012)

The engine defines **no named institutions**. Police, judges, tax collectors or a protection racket must be invented
by the villagers from generic building blocks:

- **Offices**, created, amended and abolished by meeting vote: name, duties (free text), holders, pay per period
  (from the communal store or a named source), term, granted permissions, removal rule. Duties are in the holder's
  prompt but never enforced by the engine. Neglect and abuse are possible and measured.
- **Contracts**: recurring agreements (e.g. a wage for guarding), made in dialogue or with the village in a meeting.
  The engine evaluates fulfilment or breach per period.
- **Permissions** granted to offices from a fixed vocabulary: `confiscate`, `fine`, `ban`, `detain`,
  `spend_communal`. These are capabilities, not laws: without one, the mechanic is unavailable.
- **Watch actions**: `guard(building)`, `patrol(area)`, `follow(villager)`, `keep_watch` (stay awake at night).
  Watchers get an extended witness radius. Sleepers witness nothing.
- **Intervention**: any adult in reach can interrupt another's multi-tick action. There is no combat in v1.
- **Treasury**: the communal store, filled by gifts or `tax` laws and paid out through office pay or
  `spend_communal`.

### 4.9 God powers

Drought (yield modifiers), raid (raider band spawns at the map edge, targets stores; palisades and
defending villagers reduce losses; raiders leave after N ticks), epidemic (health drain, proximity
spread), windfall/removal of resources. Each is a parameterised intervention event.

## 5. Agent layer

### 5.1 Decision triggers

Plan step completed or failed; need over threshold; conversation request; meeting called; law
change; god event nearby; idle; periodic re-plan (every `replan_hours`).

### 5.2 Prompt context (target ≤ 2k tokens)

Identity and traits; needs; the critical state of partner and children when known; inventory and property;
perception (radius-limited tiles, villagers who could witness them, buildings, village store summary); known
recipes and costs; the laws this villager knows, with their penalties; active sanctions against them; top-K
memories including hearsay (scored by recency × importance × relevance, using `nomic-embed-text` embeddings,
with reputation memories about the villagers involved prioritised); opinions of the villagers involved; current goals and
plan; recent town-square posts.

**Neutral framing:** templates never tell villagers to obey or to break laws. Laws are stated as facts
about the village, with their known penalties. Motive for violations comes from need pressure and traits
(greedy, rebellious, dutiful, altruistic, fearful, …). Templates are versioned, and a test rejects steering
phrases. Instruction-tuned models' bias towards obedience is a finding to measure, not something to tune away.

### 5.3 LLM call kinds and output schemas

| Kind | Output (JSON, schema-validated) |
|------|-------------------------------|
| plan | `{goal, steps:[{action, target, qty}], reason}`. Actions come from the valid-action catalog |
| dialogue turn | `{say, intent: offer\|accept\|reject\|promise\|inform\|ask\|threaten\|teach\|report\|accuse\|refuse_help\|leave, terms?, about?}` |
| meeting speech | `{say, proposal?}` |
| vote | `{choice, reason}` |
| board post | `{text}` |
| reflection | `{memories:[{text, importance}], opinion_updates:[{villager, trust_delta, note}], goals:[...]}` |

### 5.4 Communication

- **Dialogue:** initiated between villagers in proximity, ≤ `max_dialogue_turns` turns. It ends in a list of
  structured outcomes, possibly empty: trade executed, promise recorded (with due tick and terms), knowledge
  taught, couple formed, report or accusation made, help refused. Promises are tracked, and fulfilment or breach is an event.
- **Town-square board:** any adult may post. Recent posts form part of perception.
- **Meetings:** any adult may call a meeting at the town hall with a topic (proposal, law, election, communal
  build, sanction, office, contract). Attendees who choose to come speak in turns (capped), then vote. The engine resolves results:
  pass a law (author = villagers, hook only if the proposal maps onto the hook vocabulary),
  create or abolish an office, elect or remove a holder, approve a communal project or a contract with the village,
  apply a sanction (§4.7–4.8).

### 5.5 Executor and robustness

- Plain code turns plan steps into multi-tick engine intents (pathfind, act, haul). Failures
  (blocked, depleted, refused) trigger a re-plan.
- Invalid JSON or an invalid action triggers ≤ 2 retries with the error fed back. After that, a utility-AI fallback (eat if
  hungry, else work by skill) takes over, and the failure is logged.

### 5.6 Model assignment

`experiment.yaml` pins villagers to models or splits groups by ratio, with per-model sampling
parameters. The gateway knows how many models can be resident at once and batches requests by model to avoid
swapping models in and out of memory.

## 6. LLM gateway

- Backend interface: `complete(request) → response` with `OllamaBackend`, `MLXBackend`, `FakeBackend`
  (scripted/recorded).
- JSON-schema-constrained output where the backend supports it (Ollama `format`), plus validation in all cases.
- Response cache keyed by `hash(model, params, prompt, seed)`. Modes: `off | record | replay`.
- Per-call metrics: model, prompt hash, tokens in/out, latency, validity, retry count, raw output.

## 7. Experiments, interventions, run directory

- `experiments/*.yaml`: seed, map params, content packs, initial population (names, traits,
  knowledge, models), engine params, initial laws, scheduled interventions.
- Live interventions (from the viewer) are recorded as timestamped events. The intervention list of a run
  can be exported and reused as a schedule, so improvised experiments become reproducible.
- `pericles run <exp.yaml> [--headless] [--mode wait|live] [--cache record|replay|off]`
- Run directory: `config.yaml` snapshot, `events.sqlite`, periodic state snapshots, `llm_cache/`,
  `metrics.parquet`, `meta.json` (versions, seed, mode, reproducibility flag).
- `pericles sweep <exp.yaml> --seeds N --models a,b,c` runs the experiments one after another, then writes a combined report.

## 8. Metrics and analysis

Five metric families, all derived from the event log:

1. **Survival and growth:** population, births, deaths by cause, lifespan.
2. **Productivity and economy:** resources gathered per capita, buildings completed, Gini of wealth, trade
   volume, implied prices, coin adoption (share of trades involving coins).
3. **Social and legal:** per law and enforcement mode: ground-truth violations (all / `under_duress` /
   `unaware`), violations witnessed, reports and accusations (true / false / unverifiable), penalties and sanctions applied,
   attempted violations (block mode), ostracism (the change in a violator's interactions before vs. after a
   witnessed violation or accusation); promises kept/broken, cooperation acts, meetings held, laws passed,
   leadership (elections, centrality); institutions: offices and their tenure, contracts and breaches, watch coverage,
   theft rate before vs. after an office or watch appears, discovered vs. undiscovered losses, abuse of office.
4. **Agent quality:** invalid-output rate, retries, fallback rate, plan completion rate,
   goal-action consistency, latency and tokens per decision.
5. **Model-group dynamics:** all of the above broken down by model group in mixed runs, plus cross-group
   trade, trust and violation matrices.

`pericles report <run>...` produces a self-contained HTML comparison report. `pericles.analysis.load_run()`
returns pandas DataFrames for notebooks.

## 9. Viewer

Three.js + TypeScript (Vite). Modes: **live** (attached to a running sim: pause, step, speed,
wait-for-LLM toggle) and **replay** (a run directory; timeline scrubber; state = nearest snapshot + events).
Panels: villager inspector (needs, inventory, plan, memories, opinions, model, recent prompts and responses),
town-square board, meeting transcripts and votes, conversation log, control panel (parameters, laws,
god powers → intervention events), light dashboards. Villagers are colour-coded by model group (toggle).

## 10. Error handling

- An LLM backend that is unavailable at startup → fail fast with a clear message. Unavailable mid-run → the run pauses and
  retries with backoff. In live mode, fallback behaviour is used and flagged.
- Content-pack validation at load (schema + referential integrity). A run refuses to start with
  invalid content.
- Engine invariants (no negative stocks, conservation of items except through recipes and decay) are asserted
  in debug and test builds.
- Event-log writes are transactional per tick. A crash loses at most the current tick. Runs are resumable
  from the last snapshot.

## 11. Engineering process

- **Requirements:** `docs/requirements/` with stable IDs (`REQ-<AREA>-NNN`), areas SIM, AGT, LLM,
  ECO, SOC, EXP, VIEW, NFR, and acceptance criteria.
- **Traceability:** tests are marked `@pytest.mark.req("REQ-…")`. A script builds the
  requirement → tests matrix, and CI fails if an *accepted* requirement has no tests.
- **ADRs:** `docs/adr/NNNN-title.md`, Nygard format.
- **Tests:** pytest + Hypothesis (unit and property), FakeLLM-based agent tests, golden-run replay
  tests, Ollama contract tests (marked `slow`, local only). Viewer: Vitest + Playwright.
- **Mutation testing:** `mutmut` (Python) and Stryker (viewer). Targets: ≥ 80% `core`, ≥ 70% others initially.
  Incremental on changed modules for each PR, full run nightly or on demand.
- **Tooling:** `uv`, `ruff`, `mypy --strict`, `pnpm`, GitHub Actions.
- **Backlog:** GitHub issues, milestones per sub-project, labels `area:*`, `type:*`. Issues reference
  requirement IDs.

## 12. Milestones

| Milestone | Content |
|-----------|---------|
| M0 Foundations | Repo scaffold, CI, ADRs, requirements, traceability tooling, mutation-testing setup |
| M1 Headless sim | Map, content registry, modifiers, resources, buildings, needs, lifecycle, scripted villagers, event log, snapshots |
| M2 LLM minds | Gateway (Ollama, MLX, Fake, cache), triggers, prompt builder, plan/executor, memory, reflection, fallback |
| M3 Society | Dialogue, barter, mint and coins, promises, board, meetings and voting, laws and enforcement hooks, violation detection |
| M4 Experiments | Config, runner modes, interventions, god powers, metrics, reports, sweeps |
| M5 Viewer | 3D live and replay, inspector, social panels, control panel, dashboards |

**v1 = M0–M4 + minimal viewer** (map + villagers + inspector, live and replay). Viewer work can start after M1.

## 13. Out of scope for v1 (backlog candidates)

Full combat; multiple villages and diplomacy; deep tech tree; disease model beyond simple epidemic;
richer graphics and animation; cloud LLM backends; multiplayer.
