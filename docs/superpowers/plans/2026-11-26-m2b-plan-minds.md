# M2b Plan Minds Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Villagers with a `model:` are run by an LLM. When a trigger fires, they ask the gateway for a plan, and plain code carries the plan out step by step. Invalid plans are retried. If they stay invalid, the scripted mind takes over for a while. Every decision is recorded in the event log, and replayed runs match their recorded originals exactly.

**Architecture:** There is one `PlanMind` per model key. Each tick, `Controller` hands each `PlanMind` all its due villagers at once (`prepare`). The mind advances their current plans with the executor, collects the triggers that fired, makes one batched `gateway.complete_all` call (plus retry rounds), and adopts the valid plans. `decide` then returns each villager's prepared decision.

Agent-side facts, such as plans, invalid outputs, step results and fallbacks, become agent events. The runner appends them to the tick's events in the event log. Plan state lives in the controller's snapshot blob, so a resumed run continues the same step without a new call.

**Tech Stack:**
- Python ≥ 3.12
- pydantic 2 (plan schema, also sent to Ollama as `format`)
- `string.Template` prompt files under `src/pericles/agents/prompts/`
- pytest, mypy --strict, ruff, mutmut

**Spec:** `docs/superpowers/specs/2026-11-22-pericles-design.md`. §5 is the agent layer and §6 is the gateway. The gateway is already built (ADR-0017).

**Requirements in scope:**
- To Implemented:
  - REQ-AGT-001 (triggers that exist now)
  - REQ-AGT-003 (plan output)
  - REQ-AGT-004 (executor)
  - REQ-AGT-005 (invalid output)
  - REQ-AGT-009 (personality)
  - REQ-AGT-010 (neutral framing)
  - REQ-LLM-009 AC2 (live-mode fallback flag)
  - REQ-NFR-001 (golden replay run)
- Progressed but not finished:
  - REQ-AGT-002: AC2–AC4 are done here. AC1's memories, opinions, laws, sanctions and board posts arrive with M2c and M3, so the requirement stays Accepted.
- Left for M2c: REQ-AGT-006/007, REQ-SOC-010, REQ-NFR-004.

**User decisions (2026-11-26):**
1. An urgent need is a re-plan trigger. The LLM decides and there is no scripted survival reflex. Only invalid or failed planning falls back to the scripted mind.
2. Plan steps use about 12 village-job actions, and the executor resolves concrete nodes, sites and stores.

## Global Constraints

- Python ≥ 3.12, `mypy --strict` clean, `ruff check` and `ruff format --check` clean.
- `pericles.core` never imports `agents`, `llm`, `experiment`, `server` or `analysis`. The engine stays deterministic: no wall clock and no unseeded randomness.
- No magic values. Every tunable parameter is a field of a config dataclass (here `AgentConfig`) and appears in `src/pericles/experiment/default_settings.yaml`. Unit definitions such as minutes per hour are named module constants with a comment.
- TDD. Every test that verifies a requirement carries `@pytest.mark.req("REQ-…")`, with literal IDs, and names the AC in its docstring. Product tests live in `tests/pericles/`.
- Mutation thresholds: core ≥ 80%, agents ≥ 70%, llm ≥ 70%. `pericles.experiment` is not mutation-gated, so its tests must fail on a broken implementation (check with a deliberate break).
- Significant design decisions get an ADR. ADR-0018 is written in Task 1, and ADRs are amended, never deleted.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa
  ```
- Gates before each commit, in order:
  1. `uv run ruff format .`
  2. `uv run pytest -q`
  3. `uv run mypy`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `PYTHONPATH=tools uv run python -m pericles_tools.traceability check`
  7. `PYTHONPATH=tools uv run python -m pericles_tools.adr check`
- Mutation gate for tasks that touch `src/pericles/agents` or `src/pericles/llm`. Delete a stale `mutants/` directory first, then run `PYTHONPATH=$PWD/tools uv run python -m pericles_tools.mutation_gate run --changed-since main`.
- Prompts are deterministic: the same state gives the same prompt bytes. Request seeds derive from the run seed, villager id and tick.
- The gateway catches only `BackendError`. Minds never call a backend directly. All LLM access goes through `Gateway.complete_all` (REQ-LLM-001).
- Templates neither tell villagers to obey laws nor invite them to break them (REQ-AGT-010).

## Review Focus

1. **Call storms.**
   - **Input:** a model whose plans fail at once (for example `build house` with no materials), or end at once.
   - **Expected:** the villager must not trigger a new LLM call every tick. A freshly adopted plan that yields no action starts the fallback window, just as an invalid plan does.
   - **Pinned by:** Task 7, `test_plan_that_cannot_start_falls_back_instead_of_asking_every_tick`.
2. **Resume mid-plan.**
   - **Input:** a run stopped and resumed in the middle of a multi-step plan.
   - **Expected:** it continues the same step with no extra LLM call, and the event log matches an uninterrupted run.
   - **Pinned by:** Task 8, `test_resume_mid_plan_continues_without_a_new_call`.
3. **Dead villagers.**
   - **Input:** a planned villager dies, or a `court` target dies.
   - **Expected:** records are pruned, the target step fails with a reason, and nothing crashes.
   - **Pinned by:** Task 4, `test_court_a_dead_villager_fails`, and Task 7, `test_records_of_dead_villagers_are_dropped`.
4. **Crowded perception.**
   - **Input:** dozens of villagers, buildings and nodes within the perception radius.
   - **Expected:** the prompt is trimmed to the token budget, farthest entries first, and the actions, needs and identity sections are never cut.
   - **Pinned by:** Task 6, `test_crowded_village_is_trimmed_to_budget_farthest_first`.
5. **Replaying retries.**
   - **Input:** a recorded run in which some plans were invalid and retried.
   - **Expected:** a replay serves the retries from the cache too, and gives the same digest.
   - **Pinned by:** Task 9's golden run, which includes an invalid reply.

---

## File Structure

| File | Responsibility |
|------|----------------|
| `docs/adr/0018-plan-minds.md` (create) | Design record for this plan |
| `src/pericles/agents/config.py` (modify) | New plan-mind fields of `AgentConfig`; `TRIGGERS`, `STEERING` |
| `src/pericles/experiment/default_settings.yaml` (modify) | The new `agents:` keys |
| `src/pericles/agents/controller.py` (modify) | `Planner` protocol, batched `prepare` pass, agent events, planner state in snapshots |
| `src/pericles/experiment/runner.py` (modify) | `Agents.events()`; agent events appended to each tick's log |
| `src/pericles/agents/plan.py` (create) | `Plan`/`Step` schema, `Catalog`, `catalog_for`, `check_plan` |
| `src/pericles/agents/executor.py` (create) | `Progress`, `Outcome`, `begin`, `advance`, one handler per action |
| `src/pericles/agents/prompts/plan.v1.{system,user,retry}.txt` (create) | Versioned templates |
| `src/pericles/agents/prompt.py` (create) | `Template`, `load_template`, sections, trimming, `plan_messages` |
| `src/pericles/agents/planmind.py` (create) | `Record`, `PlanMind`, `plan_minds` |
| `src/pericles/experiment/traits.py` (create) | `draw_traits` (REQ-AGT-009 AC1) |
| `src/pericles/experiment/config.py` (modify) | `traits` may be omitted; drawn traits; template check |
| `src/pericles/experiment/launch.py` (modify) | Build plan minds from the gateway; template version in `meta.json` |
| `experiments/llm-village.yaml` (create) | Example LLM experiment (Ollama) |
| `tests/golden/` (create) | Golden-run experiment, fake replies, digest |
| `README.md`, `docs/requirements/*.md`, `docs/requirements/traceability.md` (modify) | Docs and statuses |

---

### Task 1: ADR-0018 and plan-mind settings

**Files:**
- Create: `docs/adr/0018-plan-minds.md`
- Modify: `docs/adr/README.md` (index row)
- Modify: `src/pericles/agents/config.py`
- Modify: `src/pericles/experiment/default_settings.yaml` (the `agents:` section)
- Test: `tests/pericles/test_agent_config.py`, `tests/pericles/test_settings.py`

**Interfaces:**
- Produces:
  - `pericles.agents.config.TRIGGERS: tuple[str, ...] = ("idle", "step_completed", "step_failed", "need", "periodic")`
  - `pericles.agents.config.STEERING: tuple[str, ...]`
  - `pericles.agents.config.MINUTES_PER_HOUR = 60`
  - `ticks_for_hours(tick_minutes: int, hours: float) -> int`
  - New `AgentConfig` fields:
    - `perception_radius: int = 12`
    - `replan_hours: float = 6.0`
    - `fallback_hours: float = 1.0`
    - `max_retries: int = 2`
    - `max_plan_steps: int = 6`
    - `prompt_budget_tokens: int = 2000`
    - `chars_per_token: float = 4.0`
    - `triggers: tuple[str, ...] = TRIGGERS`
    - `plan_template: str = "plan.v1"`
    - `steering_phrases: tuple[str, ...] = STEERING`
    - `drawn_traits: int = 0`

- [ ] **Step 1: Write the ADR**

Create `docs/adr/0018-plan-minds.md`:

```markdown
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
   - `need`: a relief's level rose to its `act_at` since the last check.
   - `periodic`: `replan_hours` have passed since the plan was made.

   They are checked only for due villagers. `agents.triggers` enables a subset, which must include `idle`. Conversation, meeting, law and god-event triggers arrive with those features (M3, M4).
3. **Actions** (REQ-AGT-003/004): `gather <item>`, `eat [food]`, `sleep`, `rest [hours]`, `go_home`, `move_in`, `court <villager>`, `store [item]`, `take <item>`, `build <building>`, `craft <recipe>`, `research <technology>`. `qty` is optional (a count, or hours for `rest`). The catalog lists each villager's valid targets now, and a plan whose step names another target is invalid. The executor turns a step into intents with the scripted helpers (nearest node, store, site, workplace). The step ends when its goal holds, or fails with a reason. Sites the executor places are communal, as in ADR-0016.
4. **Prompt** (REQ-AGT-002).
   - **Sections, in order:** identity and time, traits, needs, current plan and triggers, belongings, family, nearby, village stores, recipes and costs, actions.
   - **Perception:** limited to `perception_radius` Manhattan steps, plus the stores the villager may use.
   - **Token count:** estimated as `ceil(chars / chars_per_token)`.
   - **Trimming:** over `prompt_budget_tokens`, the builder removes the last line of the lowest-ranked trimmable section until the prompt fits or nothing trimmable remains. The order is recipes and costs, then nearby (farthest first), then stores, then family, then belongings.
   - **Never trimmed:** identity, traits, needs, plan and actions.
5. **Invalid output** (REQ-AGT-005). An output is invalid when it does not parse, breaks the schema, or names an action or target outside the catalog. It is retried up to `max_retries` times, with the error fed back in the versioned retry template. After that, or on a live-mode backend error (REQ-LLM-009 AC2, flagged), the villager uses the scripted mind for `fallback_hours`, then plans again. A plan that yields no action when adopted starts the same window, so the villager cannot call the LLM every tick.
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
```

Add the row to `docs/adr/README.md`'s index table after ADR-0017, in the same format as the existing rows: `| [0018](0018-plan-minds.md) | Plan minds | Accepted |`. Check the existing rows for the exact columns.

- [ ] **Step 2: Write the failing config tests**

Append to `tests/pericles/test_agent_config.py`:

```python
import math

import pytest

from pericles.agents.config import STEERING, TRIGGERS, AgentConfig, ticks_for_hours


def test_plan_mind_defaults() -> None:
    c = AgentConfig()
    assert (c.perception_radius, c.replan_hours, c.fallback_hours) == (12, 6.0, 1.0)
    assert (c.max_retries, c.max_plan_steps, c.prompt_budget_tokens) == (2, 6, 2000)
    assert (c.chars_per_token, c.plan_template, c.drawn_traits) == (4.0, "plan.v1", 0)
    assert c.triggers == TRIGGERS == ("idle", "step_completed", "step_failed", "need", "periodic")
    assert c.steering_phrases == STEERING
    assert "you must obey" in STEERING and "you may break" in STEERING


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("perception_radius", 0, "cells, tick counts and builder limits must be positive"),
        ("max_plan_steps", 0, "cells, tick counts and builder limits must be positive"),
        ("prompt_budget_tokens", 0, "cells, tick counts and builder limits must be positive"),
        ("replan_hours", 0.0, "hours and chars_per_token must be positive"),
        ("fallback_hours", -1.0, "hours and chars_per_token must be positive"),
        ("chars_per_token", 0.0, "hours and chars_per_token must be positive"),
        ("replan_hours", math.nan, "numeric parameters must be finite"),
        ("chars_per_token", math.inf, "numeric parameters must be finite"),
        ("max_retries", -1, "max_retries and drawn_traits must be non-negative"),
        ("drawn_traits", -1, "max_retries and drawn_traits must be non-negative"),
        ("triggers", ("need",), "triggers must be distinct names from"),
        ("triggers", ("idle", "idle"), "triggers must be distinct names from"),
        ("triggers", ("idle", "meeting"), "triggers must be distinct names from"),
        ("plan_template", "", "plan_template and steering phrases must be non-empty"),
        ("steering_phrases", ("ok", ""), "plan_template and steering phrases must be non-empty"),
    ],
)
def test_plan_mind_fields_are_checked(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AgentConfig(**{field: value})  # type: ignore[arg-type]


def test_ticks_for_hours_rounds_and_is_at_least_one() -> None:
    assert ticks_for_hours(10, 6.0) == 36
    assert ticks_for_hours(10, 0.25) == 2  # 1.5 rounds to 2
    assert ticks_for_hours(60, 0.1) == 1
```

Append to `tests/pericles/test_settings.py` a test that the packaged settings file holds the new keys with the dataclass defaults:

```python
def test_default_settings_hold_the_plan_mind_fields() -> None:
    from pericles.agents.config import AgentConfig
    from pericles.experiment.defaults import default_agent_config

    assert default_agent_config() == AgentConfig()
```

(If an equivalent "settings file equals dataclass defaults" test already exists, extend it instead of adding this one.)

- [ ] **Step 3: Run the tests to watch them fail**

Run: `uv run pytest tests/pericles/test_agent_config.py tests/pericles/test_settings.py -q`
Expected: FAIL. The new names do not exist (`ImportError: cannot import name 'STEERING'`).

- [ ] **Step 4: Implement**

In `src/pericles/agents/config.py`, add after `MAX_LEVEL`:

```python
TRIGGERS = ("idle", "step_completed", "step_failed", "need", "periodic")  # ADR-0018 §2
STEERING = (
    "you must obey",
    "you must follow the law",
    "obey the law",
    "you may break",
    "break the law",
    "rules are meant to be broken",
)
MINUTES_PER_HOUR = 60  # a unit, not a parameter


def ticks_for_hours(tick_minutes: int, hours: float) -> int:
    """Whole ticks in `hours`, rounded, and at least one."""
    return max(1, round(hours * MINUTES_PER_HOUR / tick_minutes))
```

Add the fields at the end of `AgentConfig`, before `__post_init__`:

```python
    # Plan minds (ADR-0018)
    perception_radius: int = 12
    replan_hours: float = 6.0
    fallback_hours: float = 1.0
    max_retries: int = 2
    max_plan_steps: int = 6
    prompt_budget_tokens: int = 2000
    chars_per_token: float = 4.0
    triggers: tuple[str, ...] = TRIGGERS
    plan_template: str = "plan.v1"
    steering_phrases: tuple[str, ...] = STEERING
    drawn_traits: int = 0
```

In `_problems`, add `c.replan_hours, c.fallback_hours, c.chars_per_token` to `reals`. Add `c.perception_radius, c.max_plan_steps, c.prompt_budget_tokens` to `positive`. Then append these checks to `checks`:

```python
        (
            c.replan_hours > 0 and c.fallback_hours > 0 and c.chars_per_token > 0,
            "hours and chars_per_token must be positive",
        ),
        (c.max_retries >= 0 and c.drawn_traits >= 0, "max_retries and drawn_traits must be non-negative"),
        (
            len(set(c.triggers)) == len(c.triggers)
            and set(c.triggers) <= set(TRIGGERS)
            and "idle" in c.triggers,
            f"triggers must be distinct names from {TRIGGERS} and include idle",
        ),
        (
            bool(c.plan_template) and all(c.steering_phrases),
            "plan_template and steering phrases must be non-empty",
        ),
```

In `default_settings.yaml`, append to the `agents:` section:

```yaml
  # Plan minds (ADR-0018)
  perception_radius: 12
  replan_hours: 6.0
  fallback_hours: 1.0
  max_retries: 2
  max_plan_steps: 6
  prompt_budget_tokens: 2000
  chars_per_token: 4.0
  triggers: [idle, step_completed, step_failed, need, periodic]
  plan_template: plan.v1
  steering_phrases:
    - you must obey
    - you must follow the law
    - obey the law
    - you may break
    - break the law
    - rules are meant to be broken
  drawn_traits: 0
```

`values_for` converts YAML lists to tuples before strict validation, so `tuple[str, ...]` fields need no settings code.

- [ ] **Step 5: Run the gates, then commit**

Run the gate commands from Global Constraints. Expected: all pass.

```bash
git add docs/adr/0018-plan-minds.md docs/adr/README.md src/pericles/agents/config.py src/pericles/experiment/default_settings.yaml tests/pericles/test_agent_config.py tests/pericles/test_settings.py
git commit -m "docs(adr): ADR-0018 plan minds; plan-mind settings

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 2: Planners in the controller, and agent events in the event log

**Files:**
- Modify: `src/pericles/agents/controller.py`
- Modify: `src/pericles/experiment/runner.py`
- Modify: every `Agents` implementation in the tests (`tests/pericles/test_llm_runs.py:64`, `tests/pericles/test_llm_launch.py:80`, and any other test class with `def observe`). Each gets `def events(self) -> list[tuple[str, dict[str, Any]]]: return []`.
- Test: `tests/pericles/test_controller_planners.py` (create), `tests/pericles/test_runner.py`

**Interfaces:**
- Produces, in `pericles.agents.controller`:
  - `failed_event(event: Event) -> bool`, the renamed public `_failed`. Keep `_failed = failed_event` only if other modules import `_failed`; grep first.
  - `Planner`, a `@runtime_checkable` Protocol with:
    - `prepare(view: View, villagers: Sequence[Villager]) -> None`
    - `decide(view: View, villager: Villager) -> Decision | None`
    - `observe(state: WorldState, events: Sequence[Event]) -> None`
    - `take_events() -> list[tuple[str, dict[str, Any]]]`
    - `to_dict() -> dict[str, Any]`
    - `parse(data: Mapping[str, Any]) -> object`
    - `restore(parsed: object) -> None`
  - `Controller.events() -> list[tuple[str, dict[str, Any]]]`
- Produces, in `pericles.experiment.runner`:
  - `Agents.events() -> Sequence[tuple[str, Mapping[str, Any]]]`
  - `agent_events(tick: int, start: int, notes: Sequence[tuple[str, Mapping[str, Any]]]) -> list[Event]`

- [ ] **Step 1: Write the failing controller tests**

Create `tests/pericles/test_controller_planners.py`:

```python
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller, Planner
from pericles.agents.scripted import ChildMind, ScriptedMind
from pericles.agents.view import Decision, View
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import MoveTo
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

MakeWorld = Callable[..., WorldState]
ROWS = ["." * 8] * 8


class Stub:
    """A planner that walks every villager it prepared to (5, 5) and reports it."""

    def __init__(self) -> None:
        self.groups: list[list[str]] = []
        self.seen: list[str] = []
        self.notes: list[tuple[str, dict[str, Any]]] = []
        self.state: dict[str, Any] = {"n": 0}

    def prepare(self, view: View, villagers: Sequence[Villager]) -> None:
        self.groups.append([v.id for v in villagers])
        self.notes.append(("plan_made", {"actor": villagers[0].id}))
        self.state["n"] += 1

    def decide(self, view: View, villager: Villager) -> Decision | None:
        return Decision(MoveTo(villager.id, Coord(5, 5)))

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        self.seen.extend(e.kind for e in events)

    def take_events(self) -> list[tuple[str, dict[str, Any]]]:
        out, self.notes = self.notes, []
        return out

    def to_dict(self) -> dict[str, Any]:
        return dict(self.state)

    def parse(self, data: Mapping[str, Any]) -> object:
        return {"n": int(data["n"])}

    def restore(self, parsed: object) -> None:
        assert isinstance(parsed, dict)
        self.state = parsed


def make(registry: Registry, minds: Mapping[str, object]) -> Controller:
    ctx = Context.build(registry, default_config())
    return Controller(ctx, AgentConfig(), ScriptedMind(), ChildMind(), minds)  # type: ignore[arg-type]


def test_stub_is_a_planner() -> None:
    assert isinstance(Stub(), Planner)
    assert not isinstance(ScriptedMind(), Planner)


@pytest.mark.req("REQ-AGT-001")
def test_prepare_gets_due_adults_of_its_model_once_a_tick_in_id_order(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: the planner is asked once a tick, for its own due adults only."""
    stub = Stub()
    state = make_world(
        ROWS,
        [
            Villager("b", "B", Coord(1, 1), model="m"),
            Villager("a", "A", Coord(2, 2), model="m"),
            Villager("c", "C", Coord(3, 3), model="other"),
            Villager("k", "K", Coord(4, 4), adult=False, model="m"),
            Villager("s", "S", Coord(1, 2)),
        ],
    )
    controller = make(registry, {"m": stub})
    intents = controller.intents(state)
    assert stub.groups == [["a", "b"]]
    assert {i.actor for i in intents if isinstance(i, MoveTo) and i.target == Coord(5, 5)} == {"a", "b"}


def test_planner_not_prepared_when_none_of_its_villagers_is_due(
    registry: Registry, make_world: MakeWorld
) -> None:
    stub = Stub()
    walker = Villager("a", "A", Coord(1, 1), model="m", path=[Coord(1, 2)])
    controller = make(registry, {"m": stub})
    controller.intents(make_world(ROWS, [walker]))
    assert stub.groups == []


def test_events_and_observe_reach_planners(registry: Registry, make_world: MakeWorld) -> None:
    stub = Stub()
    state = make_world(ROWS, [Villager("a", "A", Coord(1, 1), model="m")])
    controller = make(registry, {"m": stub})
    controller.intents(state)
    assert controller.events() == [("plan_made", {"actor": "a"})]
    assert controller.events() == []
    controller.observe(state, [Event(0, 0, "moved", {"actor": "a"})])
    assert stub.seen == ["moved"]


def test_planner_state_round_trips_through_snapshots(
    registry: Registry, make_world: MakeWorld
) -> None:
    stub = Stub()
    state = make_world(ROWS, [Villager("a", "A", Coord(1, 1), model="m")])
    controller = make(registry, {"m": stub})
    controller.intents(state)
    blob = controller.to_dict()
    assert blob["minds"] == {"m": {"n": 1}}
    fresh_stub = Stub()
    fresh = make(registry, {"m": fresh_stub})
    fresh.load(blob)
    assert fresh_stub.state == {"n": 1}


def test_scripted_only_snapshots_have_no_minds_key(registry: Registry) -> None:
    assert "minds" not in make(registry, {}).to_dict()


def test_bad_planner_data_leaves_the_controller_unchanged(
    registry: Registry, make_world: MakeWorld
) -> None:
    stub = Stub()
    controller = make(registry, {"m": stub})
    controller.intents(make_world(ROWS, [Villager("a", "A", Coord(1, 1), model="m")]))
    before = controller.to_dict()
    with pytest.raises(KeyError):
        controller.load({"fallbacks": 7, "memory": {}, "minds": {"m": {}}})
    assert controller.to_dict() == before
```

Append to `tests/pericles/test_runner.py`, using the file's existing helpers for a run directory and engine. Read the file first and reuse its fixtures.

```python
@pytest.mark.req("REQ-NFR-001")
def test_agent_events_follow_the_engine_events_of_their_tick(...) -> None:
    """AC1: agent decisions are part of the logged, digested history."""
    # An Agents implementation whose events() returns [("plan_made", {"actor": "a", "tick": t})]
    # on every tick. Run 3 ticks with run(...).
    # Assert: for every tick, the events are the engine events followed by the plan_made note,
    # with seq numbers 0..n-1 without gaps, and event.tick equal to the logged tick.
```

Write the test body with the runner tests' existing fixtures. The assertions are the ones in the comments.

- [ ] **Step 2: Run the tests to watch them fail**

Run: `uv run pytest tests/pericles/test_controller_planners.py tests/pericles/test_runner.py -q`
Expected: FAIL with `ImportError: cannot import name 'Planner'`. The runner test fails because no notes are logged.

- [ ] **Step 3: Implement the controller changes**

In `src/pericles/agents/controller.py`:

```python
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Planner(Protocol):
    """A mind that prepares decisions for many villagers at once (ADR-0018 §1)."""

    def prepare(self, view: View, villagers: Sequence[Villager]) -> None: ...

    def decide(self, view: View, villager: Villager) -> Decision | None: ...

    def observe(self, state: WorldState, events: Sequence[Event]) -> None: ...

    def take_events(self) -> list[tuple[str, dict[str, Any]]]: ...

    def to_dict(self) -> dict[str, Any]: ...

    def parse(self, data: Mapping[str, Any]) -> object: ...

    def restore(self, parsed: object) -> None: ...
```

Rename `_failed` to `failed_event` (public, because Task 7 uses it), and update its use in `observe`.

Replace `intents` with a two-pass version:

```python
    def intents(self, state: WorldState) -> list[Intent]:
        self.memory = {vid: m for vid, m in self.memory.items() if vid in state.villagers}
        view = self.view(state)
        due: list[Villager] = []
        for vid in sorted(state.villagers):
            villager = state.villagers[vid]
            memory = self.memory.get(vid)
            if memory is None:
                memory = self.memory[vid] = Memory()
            # Due: idle time over, and either free (no path, no activity) or urgent.
            if state.tick < memory.idle_until:
                continue
            if (villager.path or villager.activity is not None) and not view.urgent(villager):
                continue
            due.append(villager)
        for key, planner in self._planners():
            group = [v for v in due if v.adult and v.model == key]
            if group:
                planner.prepare(view, group)
        intents: list[Intent] = []
        for villager in due:
            memory = self.memory[villager.id]
            decision = self._decide(view, villager)
            if decision is None:
                memory.idle_until = state.tick + self.config.idle_ticks
                continue
            if _redundant(villager, decision.intent):
                continue
            view.remember(villager.id, memory, decision.target, decision.job)
            if isinstance(decision.intent, Wait):
                memory.idle_until = state.tick + self.config.idle_ticks
                continue
            intents.append(decision.intent)
        return intents

    def _planners(self) -> list[tuple[str, Planner]]:
        return [(k, m) for k, m in sorted(self.minds.items()) if isinstance(m, Planner)]

    def events(self) -> list[tuple[str, dict[str, Any]]]:
        """Agent events since the last call, planner by planner in model-key order."""
        out: list[tuple[str, dict[str, Any]]] = []
        for _, planner in self._planners():
            out.extend(planner.take_events())
        return out
```

At the end of `observe`, add:

```python
        for _, planner in self._planners():
            planner.observe(state, events)
```

Then update `to_dict` and `load`:

```python
    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "fallbacks": self.fallbacks,
            "memory": {vid: self.memory[vid].to_dict() for vid in sorted(self.memory)},
        }
        planners = self._planners()
        if planners:
            out["minds"] = {key: planner.to_dict() for key, planner in planners}
        return out

    def load(self, data: Mapping[str, Any]) -> None:
        """Restore from `to_dict` output. On error the controller is left unchanged."""
        fallbacks = int(data.get("fallbacks", 0))
        memory = {str(k): Memory.from_dict(v) for k, v in data.get("memory", {}).items()}
        minds = data.get("minds", {})
        parsed = [(p, p.parse(minds[key])) for key, p in self._planners() if key in minds]
        self.fallbacks, self.memory = fallbacks, memory
        for planner, value in parsed:
            planner.restore(value)
```

- [ ] **Step 4: Implement the runner changes**

In `src/pericles/experiment/runner.py`, add `events` to the `Agents` protocol and `SourceAgents`:

```python
class Agents(Protocol):
    def intents(self, state: WorldState) -> Sequence[Intent]: ...

    def observe(self, state: WorldState, events: Sequence[Event]) -> None: ...

    def events(self) -> Sequence[tuple[str, Mapping[str, Any]]]: ...

    def to_dict(self) -> dict[str, Any]: ...
```

```python
    def events(self) -> Sequence[tuple[str, Mapping[str, Any]]]:
        return ()
```

```python
def agent_events(
    tick: int, start: int, notes: Sequence[tuple[str, Mapping[str, Any]]]
) -> list[Event]:
    """Agent notes as events of `tick`, numbered on from the engine's (ADR-0018 §6)."""
    return [Event(tick, start + i, kind, dict(data)) for i, (kind, data) in enumerate(notes)]
```

In `run`, replace the step and append lines:

```python
        tick = state.tick
        state, events = engine.step(state, agents.intents(state))
        agents.observe(state, events)
        log.append_tick(tick, [*events, *agent_events(tick, len(events), agents.events())])
```

Import `Mapping` from `collections.abc`. Then add `events` returning `[]` to every test class that implements the `Agents` protocol (see Files).

- [ ] **Step 5: Run the tests to watch them pass**

Run: `uv run pytest tests/pericles/test_controller_planners.py tests/pericles/test_runner.py tests/pericles/test_controller.py tests/pericles/test_determinism_pin.py -q`
Expected: PASS. Runs with only scripted minds produce no notes, so the pinned digests do not change.

- [ ] **Step 6: Run the gates and the mutation gate, then commit**

```bash
git add src/pericles/agents/controller.py src/pericles/experiment/runner.py tests/pericles/
git commit -m "feat(agents): planners prepare due villagers in one batch; agent events go to the event log

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 3: Plan schema and the valid-action catalog

**Files:**
- Create: `src/pericles/agents/plan.py`
- Test: `tests/pericles/test_plan.py`

**Interfaces:**
- Consumes:
  - `pericles.agents.rules.jobs`, `rules.compatible`
  - `View.stores`, `View.held`, `View.foods`
  - `Context.available`
  - `pericles.llm.validate.validate`, `schema_of`
- Produces, in `pericles.agents.plan`:
  - `Action`, a `Literal` of the 12 action names
  - `ACTIONS: tuple[str, ...]`
  - `NO_TARGET: frozenset[str]` = `{"sleep", "rest", "go_home", "move_in"}`
  - `OPTIONAL_TARGET: frozenset[str]` = `{"eat", "store"}`
  - `Step(action, target: str | None = None, qty: int | None = None)` (pydantic, frozen)
  - `Plan(goal: str, steps: tuple[Step, ...], reason: str)` (pydantic, frozen)
  - `Catalog(targets: Mapping[str, tuple[str, ...]])` with `lines() -> list[str]`
  - `catalog_for(view: View, villager: Villager) -> Catalog`
  - `check_plan(plan: Plan, catalog: Catalog, max_steps: int) -> str | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_plan.py`:

```python
from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.plan import ACTIONS, Catalog, Plan, Step, catalog_for, check_plan
from pericles.agents.view import NodeIndex, View
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config
from pericles.llm.validate import schema_of, validate

MakeWorld = Callable[..., WorldState]
ROWS = ["." * 12] * 12


def view_of(registry: Registry, state: WorldState) -> View:
    config = AgentConfig()
    ctx = Context.build(registry, default_config())
    return View(ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), {})


def test_actions_are_the_twelve_village_jobs() -> None:
    assert ACTIONS == (
        "gather", "eat", "sleep", "rest", "go_home", "move_in",
        "court", "store", "take", "build", "craft", "research",
    )


@pytest.mark.req("REQ-AGT-003")
def test_plan_parses_and_its_schema_lists_the_actions() -> None:
    """AC1: a plan is {goal, steps:[{action, target, qty}], reason}, schema-validated."""
    text = '{"goal": "eat", "steps": [{"action": "gather", "target": "berries", "qty": 4}], "reason": "hungry"}'
    value, error = validate(Plan, text)
    assert error is None and isinstance(value, Plan)
    assert value.steps == (Step(action="gather", target="berries", qty=4),)
    schema = schema_of(Plan)
    assert set(schema["$defs"]["Step"]["properties"]["action"]["enum"]) == set(ACTIONS)


@pytest.mark.req("REQ-AGT-003")
@pytest.mark.parametrize(
    "text",
    [
        '{"goal": "x", "steps": [{"action": "dance"}], "reason": "r"}',
        '{"goal": "x", "steps": [], "reason": "r"}',
        '{"goal": "", "steps": [{"action": "sleep"}], "reason": "r"}',
        '{"goal": "x", "steps": [{"action": "rest", "qty": 0}], "reason": "r"}',
        '{"goal": "x", "steps": [{"action": "sleep"}], "reason": "r", "mood": "ok"}',
    ],
)
def test_schema_invalid_plans_are_rejected(text: str) -> None:
    """AC1: unknown actions, empty steps, blank goals, zero qty and extra keys are invalid."""
    value, error = validate(Plan, text)
    assert value is None and error


@pytest.mark.req("REQ-AGT-003")
def test_catalog_lists_what_this_villager_can_target_now(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: the catalog given in the prompt holds this villager's valid targets."""
    ada = Villager("ada", "Ada", Coord(1, 1), sex="female", inventory=Inventory({"wood": 2}))
    bram = Villager("bram", "Bram", Coord(3, 1), sex="male")
    state = make_world(ROWS, [ada, bram], nodes=[Node("n0", "berry_bush", Coord(5, 5), 10)])
    catalog = catalog_for(view_of(registry, state), ada)
    assert "berries" in catalog.targets["gather"]
    assert catalog.targets["court"] == ("bram",)
    assert "house" in catalog.targets["build"]
    assert catalog.targets["sleep"] == ()
    assert "wood" in catalog.targets["store"]
    assert "metallurgy" in catalog.targets["research"]


@pytest.mark.req("REQ-AGT-003")
def test_check_plan_rejects_targets_outside_the_catalog() -> None:
    """AC2: a step whose target is not in the catalog makes the output invalid."""
    catalog = Catalog(
        {a: () for a in ACTIONS} | {"gather": ("berries", "wood"), "eat": ("berries",)}
    )

    def plan(*steps: Step) -> Plan:
        return Plan(goal="g", steps=steps, reason="r")

    assert check_plan(plan(Step(action="gather", target="wood")), catalog, 6) is None
    assert check_plan(plan(Step(action="eat")), catalog, 6) is None
    assert check_plan(plan(Step(action="gather", target="iron_ore")), catalog, 6) == (
        "steps[0].target: 'iron_ore' is not a valid target for gather; valid: berries, wood"
    )
    assert check_plan(plan(Step(action="gather")), catalog, 6) == (
        "steps[0].target: gather needs a target; valid: berries, wood"
    )
    assert check_plan(plan(Step(action="sleep", target="bed")), catalog, 6) == (
        "steps[0].target: sleep takes no target"
    )
    assert check_plan(plan(Step(action="build", target="house")), catalog, 6) == (
        "steps[0].target: 'house' is not a valid target for build; valid: none right now"
    )
    too_long = plan(*[Step(action="sleep")] * 3)
    assert check_plan(too_long, catalog, 2) == "steps: at most 2 steps, got 3"


def test_catalog_lines_skip_actions_without_targets_and_never_list_store_items() -> None:
    catalog = Catalog({a: () for a in ACTIONS} | {"gather": ("wood",), "store": ("wood", "x")})
    lines = catalog.lines()
    assert any(line.startswith("- gather <item> [qty]") and line.endswith("targets: wood") for line in lines)
    assert not any(line.startswith("- build") for line in lines)
    assert any(line.startswith("- sleep") for line in lines)
    store = next(line for line in lines if line.startswith("- store"))
    assert "targets" not in store
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `uv run pytest tests/pericles/test_plan.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.agents.plan'`.

- [ ] **Step 3: Implement `src/pericles/agents/plan.py`**

```python
"""Plan output and the valid-action catalog (REQ-AGT-003; ADR-0018 §3)."""

from __future__ import annotations

import typing
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pericles.agents import rules
from pericles.agents.view import View
from pericles.core.state import Villager

Action = Literal[
    "gather", "eat", "sleep", "rest", "go_home", "move_in",
    "court", "store", "take", "build", "craft", "research",
]
ACTIONS: tuple[str, ...] = typing.get_args(Action)
NO_TARGET = frozenset({"sleep", "rest", "go_home", "move_in"})
OPTIONAL_TARGET = frozenset({"eat", "store"})
UNLISTED = frozenset({"store"})  # any carried item; the list would only repeat belongings
USAGE = {
    "gather": "gather <item> [qty]: collect a raw item from the land nearby",
    "eat": "eat [food]: eat food you carry, or fetch it from a store you may use",
    "sleep": "sleep: go home if you have one, and sleep until rested",
    "rest": "rest [hours]: stay where you are",
    "go_home": "go_home: walk home",
    "move_in": "move_in: take a bed in a house with room",
    "court": "court <villager>: ask to become partners, or accept their proposal",
    "store": "store [item] [qty]: put items you carry into a store you may use",
    "take": "take <item> [qty]: take items from a store you may use",
    "build": "build <building>: start or continue a building; carry its materials to it",
    "craft": "craft <recipe> [qty]: make a recipe at its workplace, qty times",
    "research": "research <technology>: study a technology at its workplace",
}


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Action
    target: str | None = None
    qty: int | None = Field(default=None, ge=1)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: str = Field(min_length=1)
    steps: tuple[Step, ...] = Field(min_length=1)
    reason: str


@dataclass(frozen=True)
class Catalog:
    """Each action's valid targets for one villager now; `NO_TARGET` actions take none."""

    targets: Mapping[str, tuple[str, ...]]

    def lines(self) -> list[str]:
        out = []
        for action in ACTIONS:
            valid = self.targets.get(action, ())
            needs_target = action not in NO_TARGET and action not in OPTIONAL_TARGET
            if needs_target and not valid:
                continue
            line = f"- {USAGE[action]}"
            if valid and action not in UNLISTED:
                line += f"; targets: {', '.join(valid)}"
            out.append(line)
        return out


def catalog_for(view: View, villager: Villager) -> Catalog:
    state, ctx = view.state, view.ctx
    registry = ctx.registry
    radius = view.config.perception_radius
    gatherable = sorted(
        {item for action in rules.jobs(view, villager, registry.items) for item in action.outputs}
    )
    stocked = sorted(
        {
            item
            for building in view.stores(villager)
            for item, qty in view.held(building).items()
            if qty > 0
        }
    )
    partners: tuple[str, ...] = ()
    if villager.partner is None:
        partners = tuple(
            sorted(
                other.id
                for other in state.villagers.values()
                if other.id != villager.id
                and other.adult
                and other.partner is None
                and villager.pos.manhattan(other.pos) <= radius
                and rules.compatible(view, villager, other)
            )
        )
    researchable = sorted(
        tech.id
        for tech in registry.technologies.values()
        if tech.id not in (state.village_knowledge if tech.scope == "village" else villager.knowledge)
    )
    targets: dict[str, tuple[str, ...]] = {action: () for action in NO_TARGET}
    targets |= {
        "gather": tuple(gatherable),
        "eat": tuple(view.foods),
        "store": tuple(sorted(registry.items)),
        "take": tuple(stocked),
        "court": partners,
        "build": tuple(sorted(k for k in registry.buildings if ctx.available(state, villager, k))),
        "craft": tuple(sorted(r for r in registry.recipes if ctx.available(state, villager, r))),
        "research": tuple(researchable),
    }
    return Catalog(targets)


def _listing(valid: tuple[str, ...]) -> str:
    return ", ".join(valid) if valid else "none right now"


def check_plan(plan: Plan, catalog: Catalog, max_steps: int) -> str | None:
    """None if every step's action and target is in `catalog`; else the first problem."""
    if len(plan.steps) > max_steps:
        return f"steps: at most {max_steps} steps, got {len(plan.steps)}"
    for i, step in enumerate(plan.steps):
        where = f"steps[{i}].target"
        valid = catalog.targets.get(step.action, ())
        if step.action in NO_TARGET:
            if step.target is not None:
                return f"{where}: {step.action} takes no target"
            continue
        if step.target is None:
            if step.action in OPTIONAL_TARGET:
                continue
            return f"{where}: {step.action} needs a target; valid: {_listing(valid)}"
        if step.target not in valid:
            return (
                f"{where}: {step.target!r} is not a valid target for {step.action}; "
                f"valid: {_listing(valid)}"
            )
    return None
```

If the content schema has no `scope` field on `TechnologyDef`, use `getattr`. It does have one (`schema.py:140`).

- [ ] **Step 4: Run the tests to watch them pass**

Run: `uv run pytest tests/pericles/test_plan.py -q`
Expected: PASS.

- [ ] **Step 5: Run the gates and the mutation gate, then commit**

```bash
git add src/pericles/agents/plan.py tests/pericles/test_plan.py
git commit -m "feat(agents): plan schema and the valid-action catalog

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 4: Executor — everyday actions

**Files:**
- Create: `src/pericles/agents/executor.py`
- Test: `tests/pericles/test_executor.py`

**Interfaces:**
- Consumes:
  - `Plan`, `Step` (Task 3)
  - `rules.jobs`, `rules.skill_score`, `rules.fits_output`, `rules.first_reachable`, `rules.portion`, `rules.surplus`, `rules.compatible`
  - `ticks_for_hours` (Task 1)
- Produces, in `pericles.agents.executor`:
  - `Progress`, a mutable dataclass with `start: int = 0`, `base: int = 0`, `issued: bool = False`, `count: int = 0`, `site: str | None = None`, `origin: tuple[int, int] | None = None`, plus `to_dict()` and `from_dict()`
  - `Outcome`, a frozen dataclass with `decision: Decision | None = None`, `done: bool = False`, `failed: str | None = None`
  - `begin(tick: int, villager: Villager, step: Step) -> Progress`
  - `advance(view: View, villager: Villager, step: Step, progress: Progress) -> Outcome`. An `Outcome()` with no decision means carry on: the villager keeps its current activity.
  - `HANDLERS: dict[str, Handler]`. Task 5 adds `build`, `craft` and `research`.

Step semantics (ADR-0018 §3):
- **`gather <item> [qty]`:** done when `qty` more are held, or, with no `qty`, when no producing action fits the carry limit. Fails with `no way to gather X now`, `no X source within reach`, or `no room to carry more X` when a `qty` is unmet.
- **`eat [food]`:** eats food it carries, or fetches it from a usable store. Done once the eat intent is sent. Fails with `no food to eat` or `no X to eat`.
- **`sleep`:** walks home if it has one and does not avoid it, then sleeps. Carries on while asleep, and is done when next due after sleeping.
- **`rest [hours]`:** sends `Wait` until `hours` (default 1) have passed since the step began.
- **`go_home`:** done at home. Fails with `no home`.
- **`move_in`:** sends `SetHome` for the couple house, else the best house with room. Done when `home` is set. Fails with `no house with a free bed` or `could not move in`.
- **`court <villager>`:** accepts their open proposal, else proposes once. Done when partnered or after proposing. Fails with `X is not a possible partner`.
- **`store [item] [qty]`:** deposits into usable stores with room. Done when `qty` are stored, nothing of the item is held, or (with no item) nothing is surplus. Fails with `no store with room`.
- **`take <item> [qty]`:** takes from usable stores. Done when `qty` are taken, or, with no `qty`, when the carry is full or the stores are empty after some taking. Fails with `no room to carry X` or `no X in a store you may use`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_executor.py`:

```python
from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.executor import Outcome, Progress, advance, begin
from pericles.agents.plan import Step
from pericles.agents.view import NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.intents import (
    AcceptCouple, Deposit, Eat, MoveTo, ProposeCouple, SetHome, Sleep, StartAction, Take, Wait,
)
from pericles.core.inventory import Inventory
from pericles.core.life import SLEEP
from pericles.core.nodes import Node
from pericles.core.state import Activity, Proposal, Villager, WorldState
from pericles.experiment.defaults import default_config

MakeWorld = Callable[..., WorldState]
ROWS = ["." * 16] * 16


def view_of(registry: Registry, state: WorldState) -> View:
    config = AgentConfig()
    ctx = Context.build(registry, default_config())
    return View(ctx, state, config, NodeIndex(state.nodes.values(), config.index_cell), {})


def run(registry: Registry, state: WorldState, vid: str, step: Step, p: Progress | None = None) -> tuple[Outcome, Progress]:
    villager = state.villagers[vid]
    progress = p if p is not None else begin(state.tick, villager, step)
    return advance(view_of(registry, state), villager, step, progress), progress


def store(bid: str, at: Coord, items: dict[str, int] | None = None) -> Building:
    b = Building(bid, "storehouse", at, Ownership("communal"), complete=True)
    for item, qty in (items or {}).items():
        b.storage.add(item, qty)
    return b


@pytest.mark.req("REQ-AGT-004")
def test_gather_walks_to_the_node_then_starts_the_action(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a plan step becomes engine intents (pathfind, act) without LLM calls."""
    ada = Villager("ada", "Ada", Coord(1, 1))
    state = make_world(ROWS, [ada], nodes=[Node("n0", "berry_bush", Coord(6, 1), 10)])
    out, _ = run(registry, state, "ada", Step(action="gather", target="berries", qty=3))
    assert isinstance(out.decision.intent, MoveTo)  # type: ignore[union-attr]
    ada.pos = Coord(5, 1)
    out, _ = run(registry, state, "ada", Step(action="gather", target="berries", qty=3))
    assert out.decision is not None and out.decision.intent == StartAction("ada", "gather_berries", "n0")


@pytest.mark.req("REQ-AGT-004")
def test_gather_is_done_once_qty_more_are_held(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: the step ends when its goal holds."""
    ada = Villager("ada", "Ada", Coord(1, 1), inventory=Inventory({"berries": 1}))
    state = make_world(ROWS, [ada], nodes=[Node("n0", "berry_bush", Coord(2, 1), 10)])
    step = Step(action="gather", target="berries", qty=3)
    progress = begin(0, ada, step)
    assert progress.base == 1
    ada.inventory.add("berries", 3)
    out, _ = run(registry, state, "ada", step, progress)
    assert out.done


@pytest.mark.req("REQ-AGT-004")
def test_gather_with_no_source_fails_with_a_reason(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: a step that becomes impossible fails with a reason."""
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(1, 1))])
    out, _ = run(registry, state, "ada", Step(action="gather", target="berries"))
    assert out.failed == "no berries source within reach"
    out, _ = run(registry, state, "ada", Step(action="gather", target="plank"))
    assert out.failed == "no way to gather plank now"


@pytest.mark.req("REQ-AGT-004")
def test_eat_carried_food_then_done(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: eat sends one Eat intent; the step is done afterwards."""
    ada = Villager("ada", "Ada", Coord(1, 1), inventory=Inventory({"berries": 5}), needs={"hunger": 60.0})
    state = make_world(ROWS, [ada])
    out, progress = run(registry, state, "ada", Step(action="eat"))
    assert out.decision is not None and isinstance(out.decision.intent, Eat)
    assert out.decision.intent.item == "berries" and out.decision.intent.qty >= 1
    assert run(registry, state, "ada", Step(action="eat"), progress)[0].done


@pytest.mark.req("REQ-AGT-004")
def test_eat_fetches_from_a_store_or_fails(registry: Registry, make_world: MakeWorld) -> None:
    """AC1/AC2: eat fetches stored food; with none anywhere it fails."""
    ada = Villager("ada", "Ada", Coord(1, 1))
    state = make_world(ROWS, [ada])
    assert run(registry, state, "ada", Step(action="eat"))[0].failed == "no food to eat"
    assert run(registry, state, "ada", Step(action="eat", target="fish"))[0].failed == "no fish to eat"
    state.buildings["s1"] = store("s1", Coord(2, 2), {"berries": 10})
    out, _ = run(registry, state, "ada", Step(action="eat"))
    assert out.decision is not None and isinstance(out.decision.intent, (MoveTo, Take))


@pytest.mark.req("REQ-AGT-004")
def test_sleep_sleeps_then_carries_on_then_is_done(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: sleep sends Sleep; while asleep it carries on; next due after waking it is done."""
    ada = Villager("ada", "Ada", Coord(1, 1))
    state = make_world(ROWS, [ada])
    out, progress = run(registry, state, "ada", Step(action="sleep"))
    assert out.decision is not None and out.decision.intent == Sleep("ada")
    ada.activity = Activity(SLEEP, SLEEP, None, 0.0, 0.0, 0.0)
    assert run(registry, state, "ada", Step(action="sleep"), progress)[0] == Outcome()
    ada.activity = None
    assert run(registry, state, "ada", Step(action="sleep"), progress)[0].done


@pytest.mark.req("REQ-AGT-004")
def test_rest_waits_for_its_hours(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: rest [hours] waits until that many hours have passed."""
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(1, 1))])
    step = Step(action="rest", qty=2)
    out, progress = run(registry, state, "ada", step)
    assert out.decision is not None and out.decision.intent == Wait("ada")
    per_hour = 60 // default_config().calendar.tick_minutes
    state.tick = 2 * per_hour - 1
    assert not run(registry, state, "ada", step, progress)[0].done
    state.tick = 2 * per_hour
    assert run(registry, state, "ada", step, progress)[0].done


@pytest.mark.req("REQ-AGT-004")
def test_go_home_and_move_in(registry: Registry, make_world: MakeWorld) -> None:
    """AC1/AC2: go_home without a home fails; move_in takes a free bed."""
    ada = Villager("ada", "Ada", Coord(1, 1))
    state = make_world(ROWS, [ada])
    assert run(registry, state, "ada", Step(action="go_home"))[0].failed == "no home"
    assert run(registry, state, "ada", Step(action="move_in"))[0].failed == "no house with a free bed"
    state.buildings["h1"] = Building("h1", "house", Coord(6, 6), Ownership("communal"), complete=True)
    out, progress = run(registry, state, "ada", Step(action="move_in"))
    assert out.decision is not None and out.decision.intent == SetHome("ada", "h1")
    ada.home = "h1"
    assert run(registry, state, "ada", Step(action="move_in"), progress)[0].done
    assert isinstance(run(registry, state, "ada", Step(action="go_home"))[0].decision.intent, MoveTo)  # type: ignore[union-attr]


@pytest.mark.req("REQ-AGT-004")
def test_court_proposes_once_or_accepts(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: court proposes, or accepts an open proposal from the target."""
    ada = Villager("ada", "Ada", Coord(1, 1), sex="female")
    bram = Villager("bram", "Bram", Coord(2, 1), sex="male")
    state = make_world(ROWS, [ada, bram])
    step = Step(action="court", target="bram")
    out, progress = run(registry, state, "ada", step)
    assert out.decision is not None and out.decision.intent == ProposeCouple("ada", "bram")
    assert run(registry, state, "ada", step, progress)[0].done
    state.proposals["bram"] = Proposal("ada", state.tick + 100)
    out, _ = run(registry, state, "ada", step)
    assert out.decision is not None and out.decision.intent == AcceptCouple("ada", "bram")


@pytest.mark.req("REQ-AGT-004")
def test_court_a_dead_villager_fails(registry: Registry, make_world: MakeWorld) -> None:
    """AC2 (Review Focus 3): a target who died fails the step; nothing crashes."""
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(1, 1), sex="female")])
    assert run(registry, state, "ada", Step(action="court", target="bram"))[0].failed == (
        "bram is not a possible partner"
    )


@pytest.mark.req("REQ-AGT-004")
def test_store_and_take(registry: Registry, make_world: MakeWorld) -> None:
    """AC1/AC2: store deposits carried items; take fetches; no store fails."""
    ada = Villager("ada", "Ada", Coord(1, 1), inventory=Inventory({"wood": 4}))
    state = make_world(ROWS, [ada])
    assert run(registry, state, "ada", Step(action="store", target="wood"))[0].failed == "no store with room"
    assert run(registry, state, "ada", Step(action="take", target="stone"))[0].failed == (
        "no stone in a store you may use"
    )
    state.buildings["s1"] = store("s1", Coord(1, 2), {"stone": 5})
    out, progress = run(registry, state, "ada", Step(action="store", target="wood", qty=3))
    assert out.decision is not None and out.decision.intent == Deposit("ada", "s1", "wood", 3)
    ada.inventory.remove("wood", 3)
    assert run(registry, state, "ada", Step(action="store", target="wood", qty=3), progress)[0].done
    out, _ = run(registry, state, "ada", Step(action="take", target="stone", qty=2))
    assert out.decision is not None and out.decision.intent == Take("ada", "s1", "stone", 2)


def test_progress_round_trips() -> None:
    p = Progress(start=3, base=2, issued=True, count=1, site="b4", origin=(5, 6))
    assert Progress.from_dict(p.to_dict()) == p
```

The store and house helpers above build `Building` objects. Check the `Building` constructor and the `Inventory.add` and `remove` names against `core/buildings.py` and `core/inventory.py`, and adapt the helper calls if they differ. Do not change the assertions. If the house's position makes `view.go` return a `MoveTo` rather than `None`, keep the test as written: it accepts a `MoveTo` for `go_home`.

- [ ] **Step 2: Run the tests to watch them fail**

Run: `uv run pytest tests/pericles/test_executor.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.agents.executor'`.

- [ ] **Step 3: Implement `src/pericles/agents/executor.py`**

```python
"""Turns plan steps into engine intents, without LLM calls (REQ-AGT-004; ADR-0018 §3)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from pericles.agents import rules
from pericles.agents.config import ticks_for_hours
from pericles.agents.plan import Step
from pericles.agents.view import Decision, View
from pericles.core.intents import (
    AcceptCouple, Deposit, Eat, ProposeCouple, SetHome, Sleep, Take, Wait,
)
from pericles.core.inventory import capacity_for
from pericles.core.life import SLEEP
from pericles.core.state import Villager

EAT = "eat"
COUNTED = ("gather", "take", "store")  # steps measured against the held count at their start


@dataclass
class Progress:
    """How far the current step got; saved in snapshots (ADR-0018 §7)."""

    start: int = 0
    base: int = 0
    issued: bool = False
    count: int = 0
    site: str | None = None
    origin: tuple[int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["origin"] = None if self.origin is None else list(self.origin)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Progress:
        origin = data["origin"]
        site = data["site"]
        return cls(
            start=int(data["start"]),
            base=int(data["base"]),
            issued=bool(data["issued"]),
            count=int(data["count"]),
            site=None if site is None else str(site),
            origin=None if origin is None else (int(origin[0]), int(origin[1])),
        )


@dataclass(frozen=True)
class Outcome:
    """A decision to send now, the step done, the step failed, or (all empty) carry on."""

    decision: Decision | None = None
    done: bool = False
    failed: str | None = None


DONE = Outcome(done=True)
CARRY_ON = Outcome()
Handler = Callable[[View, Villager, Step, Progress], Outcome]


def act(decision: Decision) -> Outcome:
    return Outcome(decision=decision)


def fail(reason: str) -> Outcome:
    return Outcome(failed=reason)


def begin(tick: int, villager: Villager, step: Step) -> Progress:
    counted = step.action in COUNTED and step.target is not None
    base = villager.inventory.count(step.target) if counted and step.target else 0
    return Progress(start=tick, base=base)


def advance(view: View, villager: Villager, step: Step, progress: Progress) -> Outcome:
    return HANDLERS[step.action](view, villager, step, progress)


def _gather(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    item = str(step.target)
    if step.qty is not None and villager.inventory.count(item) - p.base >= step.qty:
        return DONE
    ranked = sorted(
        rules.jobs(view, villager, [item]),
        key=lambda a: (-rules.skill_score(view, villager, a), a.id),
    )
    if not ranked:
        return fail(f"no way to gather {item} now")
    if not any(rules.fits_output(view, villager, a) for a in ranked):
        return DONE if step.qty is None else fail(f"no room to carry more {item}")
    decision = rules.first_reachable(view, villager, ranked)
    return act(decision) if decision is not None else fail(f"no {item} source within reach")


def _fetch(view: View, villager: Villager, foods: Sequence[str]) -> Decision | None:
    for building in view.stores(villager):
        stock = view.held(building)
        for food in foods:
            qty = min(stock.get(food, 0), rules.portion(view, villager, food))
            if qty <= 0:
                continue
            move = view.go(villager, view.tiles(building))
            if move is not None:
                return Decision(move, target=building.id)
            return Decision(Take(villager.id, building.id, food, qty), target=building.id)
    return None


def _eat(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    if p.issued:
        return DONE
    foods = (step.target,) if step.target is not None else view.foods
    items = view.ctx.registry.items
    level = view.level(villager, EAT)
    for food in foods:
        have = villager.inventory.count(food)
        if have:
            p.issued = True
            qty = min(have, max(1, math.ceil(level / items[food].nutrition)))
            return act(Decision(Eat(villager.id, food, qty)))
    fetch = _fetch(view, villager, foods)
    if fetch is not None:
        return act(fetch)
    return fail("no food to eat" if step.target is None else f"no {step.target} to eat")


def _sleep(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    if p.issued:
        asleep = villager.activity is not None and villager.activity.kind == SLEEP
        return CARRY_ON if asleep else DONE
    home = view.home(villager)
    if home is not None and not view.avoided(villager, home.id) and not view.at_home(villager):
        move = view.go(villager, view.tiles(home))
        if move is not None:
            return act(Decision(move, target=home.id))
    p.issued = True
    return act(Decision(Sleep(villager.id)))


def _rest(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    hours = step.qty if step.qty is not None else 1
    if view.tick >= p.start + ticks_for_hours(view.ctx.config.calendar.tick_minutes, hours):
        return DONE
    return act(Decision(Wait(villager.id)))


def _go_home(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    home = view.home(villager)
    if home is None:
        return fail("no home")
    if view.at_home(villager):
        return DONE
    move = view.go(villager, view.tiles(home))
    return DONE if move is None else act(Decision(move, target=home.id))


def _move_in(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    if p.issued:
        return DONE if villager.home is not None else fail("could not move in")
    house = view.couple_house(villager) if villager.partner is not None else None
    house = house if house is not None else view.house_for(villager)
    if house is None:
        return fail("no house with a free bed")
    if house.id == villager.home:
        return DONE
    p.issued = True
    return act(Decision(SetHome(villager.id, house.id), target=house.id))


def _court(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    target = str(step.target)
    if villager.partner == target:
        return DONE
    other = view.state.villagers.get(target)
    if (
        villager.partner is not None
        or other is None
        or not other.adult
        or other.partner is not None
        or not rules.compatible(view, villager, other)
    ):
        return fail(f"{target} is not a possible partner")
    proposal = view.state.proposals.get(target)
    if proposal is not None and proposal.target == villager.id and proposal.expires_tick > view.tick:
        return act(Decision(AcceptCouple(villager.id, target), target=target))
    if p.issued:
        return DONE
    p.issued = True
    return act(Decision(ProposeCouple(villager.id, target), target=target))


def _store(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    if step.target is None:
        extra = rules.surplus(view, villager)
        if not extra:
            return DONE
        item, qty = extra[0]
    else:
        item = step.target
        held = villager.inventory.count(item)
        stored = p.base - held
        if held == 0 or (step.qty is not None and stored >= step.qty):
            return DONE
        qty = held if step.qty is None else min(held, step.qty - stored)
    for building in view.stores(villager):
        room = view.room(building)
        if room <= 0:
            continue
        move = view.go(villager, view.tiles(building))
        if move is not None:
            return act(Decision(move, target=building.id))
        deposit = Deposit(villager.id, building.id, item, min(qty, room))
        return act(Decision(deposit, target=building.id))
    return fail("no store with room")


def _take(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    item = str(step.target)
    taken = villager.inventory.count(item) - p.base
    if step.qty is not None and taken >= step.qty:
        return DONE
    registry = view.ctx.registry
    room = capacity_for(registry, villager.inventory, item, view.ctx.config.carry_limit)
    if room <= 0:
        return DONE if step.qty is None and taken > 0 else fail(f"no room to carry {item}")
    left = room if step.qty is None else min(room, step.qty - taken)
    for building in view.stores(villager):
        stock = view.held(building).get(item, 0)
        if stock <= 0:
            continue
        move = view.go(villager, view.tiles(building))
        if move is not None:
            return act(Decision(move, target=building.id))
        return act(Decision(Take(villager.id, building.id, item, min(left, stock)), target=building.id))
    if step.qty is None and taken > 0:
        return DONE
    return fail(f"no {item} in a store you may use")


HANDLERS: dict[str, Handler] = {
    "gather": _gather,
    "eat": _eat,
    "sleep": _sleep,
    "rest": _rest,
    "go_home": _go_home,
    "move_in": _move_in,
    "court": _court,
    "store": _store,
    "take": _take,
}
```

`advance` raises `KeyError` for `build`, `craft` and `research` until Task 5. Nothing calls them before then.

- [ ] **Step 4: Run the tests to watch them pass**

Run: `uv run pytest tests/pericles/test_executor.py -q`
Expected: PASS. If an assertion fails because a helper builds the world differently from what the test expects (for example the `Building` constructor), fix the helper, not the assertion.

- [ ] **Step 5: Run the gates and the mutation gate, then commit**

```bash
git add src/pericles/agents/executor.py tests/pericles/test_executor.py
git commit -m "feat(agents): executor for everyday plan steps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 5: Executor — build, craft, research

**Files:**
- Modify: `src/pericles/agents/executor.py`
- Test: `tests/pericles/test_executor_work.py` (create)

**Interfaces:**
- Consumes: Task 4's `Progress`, `Outcome`, `act`, `fail`, `DONE`, `CARRY_ON`, `HANDLERS`; `remaining_cost`, `footprint`, `COMMUNAL`; `View.sites`, `View.free_origin`
- Produces: `HANDLERS["build"]`, `HANDLERS["craft"]` and `HANDLERS["research"]`, and `workplace(view, villager, kind) -> Building | None`, which returns the nearest complete building of `kind`, ordered by Manhattan distance then id.

Semantics:
- **`build <kind>`:**
  1. Uses the site it placed (`progress.site`), else finds it by `progress.origin`, else joins an existing site of that kind it does not avoid, else places a communal site at `view.free_origin(kind, villager.pos)`.
  2. Delivers carried materials and then constructs. Done when the site is complete.
  3. Fails with:
     - `no free place for a X`
     - `could not place a X`
     - `the X site is gone`
     - `the X still needs N item, …`, when materials are missing and none are carried
- **`craft <recipe> [qty]`:** goes to the nearest complete workplace and sends `Craft`. Carries on while working. Each time the villager is free after a craft, it counts one completion, and the step is done after `qty` (default 1). Fails with `R needs N item, …` or `no B to work at`.
- **`research <tech>`:** done when the technology is known (villager or village scope). Otherwise it goes to the workplace and sends `Research`, then carries on while working. Fails with `T needs N item, …` or `no B to work at`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_executor_work.py`. Reuse the `view_of` and `run` helpers: copy them from `tests/pericles/test_executor.py`, or move both into `tests/pericles/conftest.py` as fixtures and use them from both files.

```python
from pericles.agents.executor import Outcome, Progress, advance, begin, workplace
from pericles.agents.plan import Step
from pericles.agents.view import PLACE
from pericles.core.buildings import Building, Ownership
from pericles.core.geometry import Coord
from pericles.core.intents import Construct, Craft, Deliver, MoveTo, PlaceBuilding, Research
from pericles.core.inventory import Inventory
from pericles.core.state import Activity, Villager

# (imports and helpers as in test_executor.py)


@pytest.mark.req("REQ-AGT-004")
def test_build_places_a_communal_site_then_delivers_then_constructs(registry, make_world) -> None:
    """AC1: build places, delivers and constructs through engine intents."""
    ada = Villager("ada", "Ada", Coord(8, 8), inventory=Inventory({"wood": 10, "stone": 4}))
    state = make_world(ROWS, [ada])
    step = Step(action="build", target="house")
    out, progress = run(registry, state, "ada", step)
    intent = out.decision.intent  # type: ignore[union-attr]
    assert isinstance(intent, (MoveTo, PlaceBuilding))
    if isinstance(intent, MoveTo):  # walk there first, then place
        ada.pos = intent.target
        out, _ = run(registry, state, "ada", step, progress)
        intent = out.decision.intent  # type: ignore[union-attr]
    assert isinstance(intent, PlaceBuilding) and intent.ownership == "communal"
    assert progress.origin == (intent.origin.x, intent.origin.y)
    state.buildings["b1"] = Building("b1", "house", intent.origin, Ownership("communal"))
    out, _ = run(registry, state, "ada", step, progress)
    assert progress.site == "b1"
    assert isinstance(out.decision.intent, (MoveTo, Deliver))  # type: ignore[union-attr]


@pytest.mark.req("REQ-AGT-004")
def test_build_fails_listing_missing_materials(registry, make_world) -> None:
    """AC2: a site that needs materials the villager lacks fails the step with what it needs."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(ROWS, [ada])
    state.buildings["b1"] = Building("b1", "house", Coord(3, 2), Ownership("communal"))
    out, _ = run(registry, state, "ada", Step(action="build", target="house"))
    assert out.failed == "the house still needs 4 stone, 10 wood"


@pytest.mark.req("REQ-AGT-004")
def test_build_with_materials_delivered_constructs_and_completes(registry, make_world) -> None:
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(ROWS, [ada])
    site = Building("b1", "house", Coord(3, 2), Ownership("communal"), delivered={"wood": 10, "stone": 4})
    state.buildings["b1"] = site
    step = Step(action="build", target="house")
    out, progress = run(registry, state, "ada", step)
    assert isinstance(out.decision.intent, (MoveTo, Construct))  # type: ignore[union-attr]
    site.complete = True
    assert run(registry, state, "ada", step, progress)[0].done


@pytest.mark.req("REQ-AGT-004")
def test_build_site_gone_fails(registry, make_world) -> None:
    """AC2: a site removed mid-step fails with a reason."""
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(2, 2))])
    progress = Progress(site="b9")
    out, _ = run(registry, state, "ada", Step(action="build", target="house"), progress)
    assert out.failed == "the house site is gone"


@pytest.mark.req("REQ-AGT-004")
def test_craft_counts_completions_and_carries_on_while_working(registry, make_world) -> None:
    """AC1: craft sends Craft at the workplace; done after qty completions."""
    ada = Villager("ada", "Ada", Coord(2, 2), inventory=Inventory({"wood": 2}))
    state = make_world(ROWS, [ada])
    step = Step(action="craft", target="saw_planks", qty=2)
    assert run(registry, state, "ada", step)[0].failed == "no lumber_camp to work at"
    state.buildings["l1"] = Building("l1", "lumber_camp", Coord(3, 2), Ownership("communal"), complete=True)
    out, progress = run(registry, state, "ada", step)
    assert out.decision is not None and isinstance(out.decision.intent, (MoveTo, Craft))
    if isinstance(out.decision.intent, MoveTo):
        ada.pos = out.decision.intent.target
        out, _ = run(registry, state, "ada", step, progress)
    assert out.decision is not None and out.decision.intent == Craft("ada", "saw_planks", "l1")
    ada.activity = Activity("recipe", "saw_planks", "l1", 30.0, 0.0, 1.0)
    assert run(registry, state, "ada", step, progress)[0] == Outcome()
    ada.activity = None
    out, _ = run(registry, state, "ada", step, progress)
    assert progress.count == 1 and out.decision is not None
    ada.inventory.remove("wood", 2)
    progress.issued, progress.count = False, 2
    assert run(registry, state, "ada", step, progress)[0].done


@pytest.mark.req("REQ-AGT-004")
def test_craft_without_inputs_fails(registry, make_world) -> None:
    """AC2: missing inputs fail the step, naming what is missing."""
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(2, 2))])
    out, _ = run(registry, state, "ada", Step(action="craft", target="smelt_iron"))
    assert out.failed == "smelt_iron needs 2 iron_ore, 1 wood"


@pytest.mark.req("REQ-AGT-004")
def test_research_done_when_known(registry, make_world) -> None:
    """AC1/AC2: research is done once known; without its cost it fails."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(ROWS, [ada])
    step = Step(action="research", target="metallurgy")
    assert run(registry, state, "ada", step)[0].failed == "metallurgy needs 2 iron_ore"
    ada.knowledge.add("metallurgy")
    assert run(registry, state, "ada", step)[0].done


def test_workplace_is_the_nearest_complete_building_of_its_kind(registry, make_world) -> None:
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(ROWS, [ada])
    state.buildings["s2"] = Building("s2", "smithy", Coord(10, 10), Ownership("communal"), complete=True)
    state.buildings["s1"] = Building("s1", "smithy", Coord(4, 2), Ownership("communal"), complete=True)
    state.buildings["s0"] = Building("s0", "smithy", Coord(3, 2), Ownership("communal"))
    view = view_of(registry, state)
    assert workplace(view, ada, "smithy").id == "s1"  # type: ignore[union-attr]
    assert workplace(view, ada, "mint") is None
```

Add the needed imports (`pytest`, `Callable`, `Registry`, `WorldState`) as in Task 4's test file. The expected missing-material strings follow the base pack's costs: house 10 wood and 4 stone; smelt_iron 2 iron_ore and 1 wood; metallurgy 2 iron_ore. Items are listed sorted by id.

- [ ] **Step 2: Run the tests to watch them fail**

Run: `uv run pytest tests/pericles/test_executor_work.py -q`
Expected: FAIL with `ImportError: cannot import name 'workplace'`.

- [ ] **Step 3: Implement**

Add to `src/pericles/agents/executor.py`:

```python
from pericles.agents.view import CONSTRUCT, PLACE
from pericles.core.buildings import COMMUNAL, Building, footprint, remaining_cost
from pericles.core.geometry import Coord
from pericles.core.intents import Construct, Craft, Deliver, PlaceBuilding, Research


def workplace(view: View, villager: Villager, kind: str) -> Building | None:
    complete = [b for b in view.state.buildings.values() if b.kind == kind and b.complete]
    return min(complete, key=lambda b: (villager.pos.manhattan(b.origin), b.id), default=None)


def _missing(villager: Villager, bundle: Mapping[str, int]) -> str:
    have = villager.inventory
    return ", ".join(
        f"{qty - have.count(item)} {item}"
        for item, qty in sorted(bundle.items())
        if have.count(item) < qty
    )


def _site(view: View, villager: Villager, kind: str, p: Progress) -> Building | Outcome:
    """The site this step works on, or the outcome of finding or placing one."""
    if p.site is not None:
        site = view.state.buildings.get(p.site)
        return site if site is not None else fail(f"the {kind} site is gone")
    if p.origin is not None:
        placed = next(
            (b for b in view.sites() if b.kind == kind and (b.origin.x, b.origin.y) == p.origin),
            None,
        )
        if placed is None:
            return fail(f"could not place a {kind}")
        p.site = placed.id
        return placed
    joined = next(
        (b for b in view.sites() if b.kind == kind and not view.avoided(villager, b.id)), None
    )
    if joined is not None:
        p.site = joined.id
        return joined
    origin = view.free_origin(kind, villager.pos)
    if origin is None:
        return fail(f"no free place for a {kind}")
    size = view.ctx.registry.buildings[kind].footprint
    move = view.go(villager, footprint(origin, size))
    if move is not None:
        return act(Decision(move, target=PLACE + kind))
    p.origin = (origin.x, origin.y)
    place = PlaceBuilding(villager.id, kind, origin, ownership=COMMUNAL)
    return act(Decision(place, target=PLACE + kind))


def _build(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    kind = str(step.target)
    found = _site(view, villager, kind, p)
    if isinstance(found, Outcome):
        return found
    site = found
    if site.complete:
        return DONE
    remaining = remaining_cost(site, view.ctx.registry)
    for item in sorted(remaining):
        have = villager.inventory.count(item)
        if have:
            move = view.go(villager, view.tiles(site))
            if move is not None:
                return act(Decision(move, target=site.id))
            deliver = Deliver(villager.id, site.id, item, min(have, remaining[item]))
            return act(Decision(deliver, target=site.id))
    if remaining:
        needs = ", ".join(f"{qty} {item}" for item, qty in sorted(remaining.items()))
        return fail(f"the {kind} still needs {needs}")
    move = view.go(villager, view.tiles(site))
    if move is not None:
        return act(Decision(move, target=site.id, job=CONSTRUCT))
    return act(Decision(Construct(villager.id, site.id), target=site.id, job=CONSTRUCT))


def _work_at(
    view: View, villager: Villager, kind: str, make: Callable[[str], Decision], p: Progress
) -> Outcome:
    building = workplace(view, villager, kind)
    if building is None:
        return fail(f"no {kind} to work at")
    move = view.go(villager, view.tiles(building))
    if move is not None:
        return act(Decision(move, target=building.id))
    p.issued = True
    return act(make(building.id))


def _craft(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    recipe = view.ctx.registry.recipes[str(step.target)]
    if p.issued and villager.activity is not None:
        return CARRY_ON
    if p.issued:
        p.count, p.issued = p.count + 1, False
    if p.count >= (step.qty if step.qty is not None else 1):
        return DONE
    if not villager.inventory.has(recipe.inputs):
        return fail(f"{recipe.id} needs {_missing(villager, recipe.inputs)}")

    def make(building: str) -> Decision:
        return Decision(Craft(villager.id, recipe.id, building), target=building, job=recipe.id)

    return _work_at(view, villager, recipe.building, make, p)


def _research(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    tech = view.ctx.registry.technologies[str(step.target)]
    known = view.state.village_knowledge if tech.scope == "village" else villager.knowledge
    if tech.id in known:
        return DONE
    if p.issued and villager.activity is not None:
        return CARRY_ON
    if not villager.inventory.has(tech.cost):
        return fail(f"{tech.id} needs {_missing(villager, tech.cost)}")

    def make(building: str) -> Decision:
        return Decision(Research(villager.id, tech.id, building), target=building)

    return _work_at(view, villager, tech.building, make, p)


HANDLERS |= {"build": _build, "craft": _craft, "research": _research}
```

Put the imports at the top of the module with the others. Write `HANDLERS` as one literal holding all 12 entries, rather than updating it afterwards, if that reads better.

- [ ] **Step 4: Run the tests to watch them pass**

Run: `uv run pytest tests/pericles/test_executor.py tests/pericles/test_executor_work.py -q`
Expected: PASS.

- [ ] **Step 5: Run the gates and the mutation gate, then commit**

```bash
git add src/pericles/agents/executor.py tests/pericles/test_executor_work.py tests/pericles/conftest.py
git commit -m "feat(agents): executor builds, crafts and researches

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 6: Prompt builder and versioned templates

**Files:**
- Create: `src/pericles/agents/prompts/plan.v1.system.txt`, `plan.v1.user.txt`, `plan.v1.retry.txt`
- Create: `src/pericles/agents/prompt.py`
- Check: `pyproject.toml`. The prompt files must ship with the package. Run `uv build` and list the wheel to confirm. Content YAML already ships the same way; mirror its configuration if needed.
- Test: `tests/pericles/test_prompt.py`

**Interfaces:**
- Consumes: `catalog_for`, `Catalog`, `Plan` (Task 3); `View`; `AgentConfig` fields (Task 1); `pericles.llm.types.Message`
- Produces, in `pericles.agents.prompt`:
  - `PROMPTS: Path`
  - `TemplateError(ValueError)`
  - `Template(version: str, system: string.Template, user: string.Template, retry: string.Template)`
  - `load_template(version: str) -> Template`
  - `template_paths(version: str) -> list[Path]`
  - `Situation`, a frozen dataclass with `triggers: tuple[str, ...]`, `plan: Plan | None`, `index: int`, `failure: str | None`
  - `Section(title: str, lines: tuple[str, ...], rank: int)`, and `ALWAYS = 99`
  - `sections(view, villager, situation, catalog) -> list[Section]`
  - `fit(sections, budget_tokens, chars_per_token, fixed_chars) -> list[Section]`
  - `plan_messages(view, villager, situation, catalog, template) -> tuple[Message, Message]`
  - `estimate_tokens(text: str, chars_per_token: float) -> int`

Section ranks, from first trimmed to never trimmed:

| Rank | Section |
|------|---------|
| 1 | "Recipes and costs" |
| 2 | "Nearby" (lines sorted by distance, so trimming removes the farthest first) |
| 3 | "Stores you may use" |
| 4 | "Family" |
| 5 | "Belongings" |
| `ALWAYS` | "You", "Traits", "Needs", "Your plan", "Actions you can use" |

- [ ] **Step 1: Write the template files**

`src/pericles/agents/prompts/plan.v1.system.txt`:

```
You are $name, one of the villagers of a small village. Every villager makes their own choices.
You decide what to do next by writing a short plan.

Answer with one JSON object and nothing else, in this form:
{"goal": "what you want to achieve", "steps": [{"action": "an action", "target": "its target or null", "qty": a number or null}], "reason": "why"}

Use only the actions listed under "Actions you can use", with one of their targets. A plan has at most $max_steps steps.
```

`src/pericles/agents/prompts/plan.v1.user.txt`:

```
$sections

What do you do next?
```

`src/pericles/agents/prompts/plan.v1.retry.txt`:

```
That answer could not be used: $error
Answer again with one JSON object in the form described.
```

- [ ] **Step 2: Write the failing tests**

Create `tests/pericles/test_prompt.py`:

```python
from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.plan import Plan, Step, catalog_for
from pericles.agents.prompt import (
    ALWAYS, PROMPTS, Section, Situation, TemplateError, estimate_tokens, fit, load_template,
    plan_messages, sections, template_paths,
)
from pericles.agents.view import NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_agent_config, default_config

MakeWorld = Callable[..., WorldState]
ROWS = ["." * 40] * 40
IDLE = Situation(("idle",), None, 0, None)


def view_of(registry: Registry, state: WorldState, **config: object) -> View:
    agents = AgentConfig(**config)  # type: ignore[arg-type]
    ctx = Context.build(registry, default_config())
    return View(ctx, state, agents, NodeIndex(state.nodes.values(), agents.index_cell), {})


def prompt(registry: Registry, state: WorldState, vid: str = "ada", situation: Situation = IDLE, **config: object) -> str:
    view = view_of(registry, state, **config)
    villager = state.villagers[vid]
    system, user = plan_messages(view, villager, situation, catalog_for(view, villager), load_template("plan.v1"))
    return system.content + "\n" + user.content


def village(make_world: MakeWorld) -> WorldState:
    ada = Villager("ada", "Ada", Coord(5, 5), sex="female", traits=("greedy",), needs={"hunger": 90.0}, inventory=Inventory({"wood": 3}))
    near = Villager("bram", "Bram", Coord(8, 5), sex="male")
    far = Villager("zed", "Zed", Coord(35, 35), sex="male")
    state = make_world(
        ROWS,
        [ada, near, far],
        nodes=[Node("n0", "berry_bush", Coord(6, 6), 5), Node("n9", "tree", Coord(36, 36), 5)],
    )
    state.buildings["h1"] = Building("h1", "house", Coord(9, 9), Ownership("communal"), complete=True)
    state.buildings["h9"] = Building("h9", "house", Coord(30, 30), Ownership("communal"), complete=True)
    return state


def test_template_files_exist_and_load() -> None:
    template = load_template("plan.v1")
    assert template.version == "plan.v1"
    assert [p.name for p in template_paths("plan.v1")] == [
        "plan.v1.system.txt", "plan.v1.user.txt", "plan.v1.retry.txt",
    ]
    with pytest.raises(TemplateError, match="plan.v9"):
        load_template("plan.v9")


@pytest.mark.req("REQ-AGT-010")
def test_templates_contain_no_steering_phrases() -> None:
    """AC3: no template contains a configured steering phrase (any case)."""
    phrases = default_agent_config().steering_phrases
    assert phrases
    for path in sorted(PROMPTS.glob("*.txt")):
        text = path.read_text(encoding="utf-8").lower()
        assert [p for p in phrases if p.lower() in text] == [], path.name


@pytest.mark.req("REQ-AGT-010")
def test_prompts_neither_order_obedience_nor_invite_breaking(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a rendered prompt contains none of the steering phrases either."""
    text = prompt(registry, village(make_world)).lower()
    assert [p for p in default_agent_config().steering_phrases if p in text] == []


@pytest.mark.req("REQ-AGT-009")
def test_traits_with_their_descriptions_are_in_the_prompt(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: each villager's traits are included in prompts."""
    assert "- greedy: Wants to own more than others." in prompt(registry, village(make_world))


@pytest.mark.req("REQ-AGT-002")
def test_perception_is_limited_to_the_radius(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: nearby villagers, buildings and nodes inside perception_radius only."""
    text = prompt(registry, village(make_world))
    assert "Bram (bram)" in text and "Zed" not in text
    assert "house h1" in text and "h9" not in text
    assert "berry_bush" in text and "tree:" not in text


@pytest.mark.req("REQ-AGT-002")
def test_store_summary_is_included(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: the village store summary is part of perception, wherever the store stands."""
    state = village(make_world)
    store = Building("s1", "storehouse", Coord(30, 5), Ownership("communal"), complete=True)
    store.storage.add("berries", 12)
    state.buildings["s1"] = store
    assert "- berries: 12" in prompt(registry, state)


@pytest.mark.req("REQ-AGT-002")
def test_prompt_shows_needs_plan_failure_and_triggers(registry: Registry, make_world: MakeWorld) -> None:
    """AC1 (the sections that exist in M2b): needs, current plan, last failure, why now."""
    plan = Plan(goal="food", steps=(Step(action="gather", target="berries"), Step(action="eat")), reason="hungry")
    text = prompt(registry, village(make_world), situation=Situation(("step_failed",), plan, 1, "no berries source within reach"))
    assert "- hunger: 90/100 (urgent)" in text
    assert "Goal: food" in text and "→ 2. eat" in text
    assert "Last step failed: no berries source within reach" in text
    assert "Deciding now because: step_failed" in text
    assert "- gather <item> [qty]" in text


@pytest.mark.req("REQ-AGT-002")
def test_prompts_are_deterministic(registry: Registry, make_world: MakeWorld) -> None:
    """AC4: same state → same prompt bytes, also after a save and load."""
    state = village(make_world)
    again = WorldState.from_dict(state.to_dict())
    assert prompt(registry, state) == prompt(registry, state) == prompt(registry, again)


def test_fit_trims_lowest_rank_last_lines_first() -> None:
    parts = [
        Section("You", ("a" * 40,), ALWAYS),
        Section("Nearby", ("n1", "n2", "n3"), 2),
        Section("Recipes and costs", ("r1", "r2"), 1),
    ]
    kept = fit(parts, budget_tokens=1, chars_per_token=1.0, fixed_chars=0)
    assert kept == [Section("You", ("a" * 40,), ALWAYS)]
    kept = fit(parts, budget_tokens=10_000, chars_per_token=1.0, fixed_chars=0)
    assert kept == parts
    trimmed = fit(parts, budget_tokens=estimate_tokens("## You\n" + "a" * 40 + "\n\n## Nearby\nn1\nn2", 1.0) + 1, chars_per_token=1.0, fixed_chars=0)
    assert [s.title for s in trimmed] == ["You", "Nearby"]
    assert trimmed[1].lines == ("n1", "n2")


@pytest.mark.req("REQ-AGT-002")
def test_crowded_village_is_trimmed_to_budget_farthest_first(registry: Registry, make_world: MakeWorld) -> None:
    """AC3 (Review Focus 4): over the budget, recipes go first, then the farthest nearby lines;
    identity, needs, plan and actions stay."""
    crowd = [Villager(f"v{i:02d}", f"V{i:02d}", Coord(5 + i % 10, 6 + i // 10), sex="male") for i in range(30)]
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(5, 5), sex="female"), *crowd])
    full = prompt(registry, state, prompt_budget_tokens=100_000)
    small = prompt(registry, state, prompt_budget_tokens=700)
    assert estimate_tokens(small, 4.0) <= 700 < estimate_tokens(full, 4.0)
    assert "## Recipes and costs" in full and "## Recipes and costs" not in small
    assert "V00 (v00)" in small and "V29 (v29)" not in small  # v29 is the farthest
    for kept in ("## You", "## Needs", "## Your plan", "## Actions you can use"):
        assert kept in small
```

`estimate_tokens(small, 4.0)` counts the system and user text joined by one newline. `plan_messages` must measure exactly the text it returns, so the budget check matches; see Step 4.

- [ ] **Step 3: Run the tests to watch them fail**

Run: `uv run pytest tests/pericles/test_prompt.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.agents.prompt'`.

- [ ] **Step 4: Implement `src/pericles/agents/prompt.py`**

```python
"""Plan prompts from versioned templates, within a token budget (REQ-AGT-002/010; ADR-0018 §4, §8)."""

from __future__ import annotations

import math
import string
from collections.abc import Sequence
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path

from pericles.agents.config import RELIEFS
from pericles.agents.plan import Catalog, Plan
from pericles.agents.view import View
from pericles.core.state import Villager
from pericles.llm.types import Message

PROMPTS = Path(str(files("pericles.agents").joinpath("prompts")))
PARTS = ("system", "user", "retry")
ALWAYS = 99
HOURS_PER_DAY = 24  # a unit, not a parameter
MINUTES_PER_HOUR = 60


class TemplateError(ValueError):
    """A prompt template version is missing or incomplete."""


@dataclass(frozen=True)
class Template:
    version: str
    system: string.Template
    user: string.Template
    retry: string.Template


def template_paths(version: str) -> list[Path]:
    return [PROMPTS / f"{version}.{part}.txt" for part in PARTS]


def load_template(version: str) -> Template:
    paths = template_paths(version)
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise TemplateError(f"prompt template {version!r}: missing {', '.join(missing)} in {PROMPTS}")
    system, user, retry = (string.Template(p.read_text(encoding="utf-8")) for p in paths)
    return Template(version, system, user, retry)


@dataclass(frozen=True)
class Situation:
    triggers: tuple[str, ...]
    plan: Plan | None
    index: int
    failure: str | None


@dataclass(frozen=True)
class Section:
    title: str
    lines: tuple[str, ...]
    rank: int


def estimate_tokens(text: str, chars_per_token: float) -> int:
    return math.ceil(len(text) / chars_per_token)


def render(parts: Sequence[Section]) -> str:
    return "\n\n".join(f"## {s.title}\n" + "\n".join(s.lines) for s in parts)


def fit(
    parts: Sequence[Section], budget_tokens: int, chars_per_token: float, fixed_chars: int
) -> list[Section]:
    """Drop last lines of the lowest-ranked trimmable section until the prompt fits."""
    current = list(parts)

    def size() -> int:
        kept = [s for s in current if s.lines or s.rank >= ALWAYS]
        return math.ceil((fixed_chars + len(render(kept))) / chars_per_token)

    while size() > budget_tokens:
        trimmable = [i for i, s in enumerate(current) if s.rank < ALWAYS and s.lines]
        if not trimmable:
            break
        i = min(trimmable, key=lambda j: (current[j].rank, j))
        current[i] = replace(current[i], lines=current[i].lines[:-1])
    return [s for s in current if s.lines or s.rank >= ALWAYS]
```

Then write the section builders. Each returns a `Section`. Lines are sorted wherever the order is not given, so prompts are deterministic.

- **`_you`, rank `ALWAYS`:**
  - `f"You are {name} ({id}), {sex or 'of no stated sex'}, {age}."` The age is `age_days // days_per_year` years, or days while under one year: `f"{years} years old"` / `f"{days} days old"`.
  - `f"It is {season.name}, day {day + 1} of the year, hour {hour}."` Take `season` and `day` from the calendar. Look at `Calendar.season_at` and `_locate` for the public way to get them. The hour is `(tick % ticks_per_day) * tick_minutes // MINUTES_PER_HOUR`.
- **`_traits`, rank `ALWAYS`:** `f"- {t}: {registry.traits[t].description}"` for each trait in `villager.traits` order, or `"- none"`.
- **`_needs`, rank `ALWAYS`:**
  - For each need id, sorted: `f"- {need}: {level:.0f}/100"`, plus `" (urgent)"` when the need's relief is in `RELIEFS` and `level >= view.config.urgent_at[relief]`.
  - `f"- injury: {villager.damage:.0f}"` when `damage > 0`.
- **`_plan`, rank `ALWAYS`:**
  - With no plan: `"- none yet"`.
  - With a plan: `f"Goal: {plan.goal}"`, then each step as `f"{mark} {n}. {action}{' ' + target if target else ''}{' x' + str(qty) if qty else ''}"`. The mark is `"✓"` for steps before `index`, `"→"` for `index`, and `" "` after.
  - Then `f"Last step failed: {failure}"` when set, and `f"Deciding now because: {', '.join(triggers)}"`.
- **`_belongings`, rank 5:**
  - `"Carrying: " + ", ".join(f"{qty} {item}")`, sorted, or `"Carrying: nothing"`.
  - `f"Home: {kind} {id}"`, or `"Home: none"`.
  - One line per building whose ownership lists the villager: `f"Owns: {kind} {id}"`.
- **`_family`, rank 4:** family members are `partner`, `children` (villagers listing the villager in `parents`) and `parents`, then proposals.
  - A member is *known* when within `perception_radius` (Manhattan) or sharing the villager's home. Its line is `f"- {relation} {name} ({id}): {status}"`. The status names the reliefs at or past `urgent_at` (`"needs eat urgently"`) or `"fine"`, plus `", injured"` when `damage > 0`.
  - A member who is not known: `f"- {relation} {name} ({id}): not in sight"`.
  - For each open proposal targeting the villager: `f"- {name} ({id}) has asked you to be partners"`.
  - With no lines: `"- none"`.
- **`_nearby`, rank 2:** entries within `perception_radius`, each as `(distance, text)`, sorted by `(distance, text)`, keeping the texts:
  - Other villagers: `f"{name} ({id}), {d} steps away, {doing}"`. `doing` is the activity `ident` when busy, `"walking"` when on a path, else `"idle"`.
  - Buildings (distance to origin): `f"{kind} {id}, {d} steps away, {state}"`. The state is `"complete"`, or `"site needing " + needs` (from `remaining_cost`; `"site ready to build"` when nothing remains), plus `f", owned by {owners}"` unless communal.
  - Nodes with stock > 0, grouped by kind: `f"{kind}: {count} within {radius} steps, nearest {d} steps away"`, with the nearest distance as its sort key.
  - Each line is prefixed `"- "`.
- **`_stores`, rank 3:** totals over `view.stores(villager)` of `view.held(b)`, as `f"- {item}: {qty}"`, sorted. With none: `"- none you may use"`.
- **`_knowledge`, rank 1:**
  - Recipes available to the villager: `f"- {id}: {inputs} -> {outputs} at a {building}"`.
  - Buildings available to the villager: `f"- {kind} costs {cost}"`.
  - Technologies in the catalog's research targets: `f"- {id} costs {cost} at a {building}"`.
  - Bundles are formatted `"2 wood, 1 hide"`, sorted by item.
- **`_actions`, rank `ALWAYS`:** `tuple(catalog.lines())`.

```python
def sections(view: View, villager: Villager, situation: Situation, catalog: Catalog) -> list[Section]:
    return [
        _you(view, villager),
        _traits(view, villager),
        _needs(view, villager),
        _plan(situation),
        _belongings(view, villager),
        _family(view, villager),
        _nearby(view, villager),
        _stores(view, villager),
        _knowledge(view, villager, catalog),
        _actions(catalog),
    ]


def plan_messages(
    view: View, villager: Villager, situation: Situation, catalog: Catalog, template: Template
) -> tuple[Message, Message]:
    config = view.config
    system = template.system.substitute(name=villager.name, max_steps=config.max_plan_steps)
    frame = template.user.substitute(sections="")
    fixed = len(system) + 1 + len(frame)  # the joining newline as estimate_tokens counts it
    kept = fit(
        sections(view, villager, situation, catalog),
        config.prompt_budget_tokens,
        config.chars_per_token,
        fixed,
    )
    user = template.user.substitute(sections=render(kept))
    return Message("system", system), Message("user", user)
```

The section headings in the test are `## You`, `## Traits`, `## Needs`, `## Your plan`, `## Belongings`, `## Family`, `## Nearby`, `## Stores you may use`, `## Recipes and costs` and `## Actions you can use`.

`RELIEFS` and the need-to-relief mapping come from `pericles.agents.config` and `registry.needs[need].relief`.

- [ ] **Step 5: Run the tests to watch them pass**

Run: `uv run pytest tests/pericles/test_prompt.py -q`
Expected: PASS. If the 700-token crowd test does not trim `v29` while keeping `v00`, adjust only the budget number in the test (keep `full` over it), and say so in the report.

- [ ] **Step 6: Check packaging**

Run: `uv build --wheel -o /tmp/pericles-wheel && unzip -l /tmp/pericles-wheel/*.whl | grep prompts`
Expected: the three `plan.v1.*.txt` files are listed. If they are not, add the package-data rule that `pyproject.toml` uses for `content/`.

- [ ] **Step 7: Run the gates and the mutation gate, then commit**

```bash
git add src/pericles/agents/prompt.py src/pericles/agents/prompts tests/pericles/test_prompt.py pyproject.toml
git commit -m "feat(agents): plan prompts from versioned templates within a token budget

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 7: PlanMind — triggers, retries, fallback, events, state

**Files:**
- Create: `src/pericles/agents/planmind.py`
- Test: `tests/pericles/test_planmind.py`

**Interfaces:**
- Consumes:
  - `Planner`, `failed_event`, `WATCHED`, `Mind` (Task 2, `controller.py`)
  - `Plan`, `catalog_for`, `check_plan` (Task 3)
  - `Progress`, `begin`, `advance` (Tasks 4–5)
  - `Template`, `Situation`, `plan_messages`, `load_template` (Task 6)
  - `TRIGGERS`, `RELIEFS`, `ticks_for_hours` (Task 1)
  - `pericles.llm.types.Request`, `Result`, `Message`
- Produces, in `pericles.agents.planmind`:
  - `Complete = Callable[[Sequence[Request]], list[Result]]`
  - `Record`, a mutable dataclass with `to_dict` and `from_dict`
  - `seed_for(run_seed: int, villager: str, tick: int) -> int`
  - `PlanMind(model: str, complete: Complete, fallback: Mind, config: AgentConfig, seed: int, template: Template)`, which implements `Planner`
  - `plan_minds(models: Iterable[str], complete: Complete, config: AgentConfig, seed: int) -> dict[str, PlanMind]`
- Agent event kinds and data:
  - `plan_made` {actor, model, triggers: [str], goal, steps: [{action, target, qty}], reason, retries: int, template}
  - `plan_invalid` {actor, model, attempt: int, error}
  - `plan_step` {actor, model, index, action, target, status: "done" | "failed", reason?}
  - `mind_fallback` {actor, model, reason, flagged: bool}

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_planmind.py`:

```python
import json
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller, Planner
from pericles.agents.planmind import PlanMind, plan_minds, seed_for
from pericles.agents.scripted import ScriptedMind, scripted_controller
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config
from pericles.llm.cache import ResponseCache
from pericles.llm.fake import FakeBackend, FakeError, FakeRule
from pericles.llm.gateway import BackendUnavailable, FailurePolicy, Gateway
from pericles.llm.types import ModelSpec, Sampling

MakeWorld = Callable[..., WorldState]
ROWS = ["." * 16] * 16
REST = json.dumps({"goal": "rest", "steps": [{"action": "rest", "qty": 1}], "reason": "tired"})
BERRIES = json.dumps(
    {"goal": "food", "steps": [{"action": "gather", "target": "berries", "qty": 2}, {"action": "eat"}], "reason": "hungry"}
)
IRON = json.dumps({"goal": "iron", "steps": [{"action": "gather", "target": "iron_ore"}], "reason": "tools"})


def setup(
    registry: Registry,
    make_world: MakeWorld,
    replies: Sequence[str | FakeError],
    *,
    mode: str = "wait",
    villagers: Sequence[Villager] | None = None,
    **config: object,
) -> tuple[Controller, Engine, WorldState, FakeBackend]:
    agents = AgentConfig(**config)  # type: ignore[arg-type]
    backend = FakeBackend([FakeRule(tuple(replies), kind="plan")])
    gateway = Gateway(
        {"m": ModelSpec("f", "fake-model", Sampling(0.7, 0.9, 256))},
        {"f": backend},
        ResponseCache(None, "off"),
        FailurePolicy(mode, 0.0, 2.0, 0.0, 2),
        sleep=lambda s: None,
    )
    engine = Engine(registry, default_config())
    controller = scripted_controller(engine.context, agents, plan_minds(["m"], gateway.complete_all, agents, seed=7))
    people = villagers if villagers is not None else [Villager("ada", "Ada", Coord(2, 2), model="m")]
    state = make_world(ROWS, people, nodes=[Node("n0", "berry_bush", Coord(4, 2), 50)])
    return controller, engine, state, backend


def step(controller: Controller, engine: Engine, state: WorldState) -> tuple[WorldState, list[tuple[str, dict]]]:
    state, events = engine.step(state, controller.intents(state))
    controller.observe(state, events)
    return state, controller.events()


def kinds(notes: list[tuple[str, dict]]) -> list[str]:
    return [k for k, _ in notes]


def test_plan_mind_is_a_planner(registry: Registry) -> None:
    mind = plan_minds(["m"], lambda rs: [], AgentConfig(), seed=1)["m"]
    assert isinstance(mind, Planner) and isinstance(mind, PlanMind)


def test_seed_for_is_stable_and_differs_by_villager_and_tick() -> None:
    assert seed_for(7, "ada", 3) == seed_for(7, "ada", 3)
    assert len({seed_for(7, "ada", 3), seed_for(7, "bram", 3), seed_for(7, "ada", 4), seed_for(8, "ada", 3)}) == 4
    assert 0 <= seed_for(7, "ada", 3) < 2**32


@pytest.mark.req("REQ-AGT-001")
def test_first_tick_plans_on_idle_and_records_the_trigger(registry: Registry, make_world: MakeWorld) -> None:
    """AC1/AC3: a villager with no plan asks on `idle`; the trigger is in the plan_made event."""
    controller, engine, state, backend = setup(registry, make_world, [BERRIES])
    state, notes = step(controller, engine, state)
    assert len(backend.calls) == 1
    made = dict(notes)["plan_made"]
    assert made["triggers"] == ["idle"] and made["model"] == "m" and made["template"] == "plan.v1"
    assert made["steps"][0] == {"action": "gather", "target": "berries", "qty": 2}
    assert backend.calls[0].seed == seed_for(7, "ada", 0)


@pytest.mark.req("REQ-AGT-001")
def test_no_call_on_ticks_without_a_trigger(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: while the plan runs and nothing fires, no LLM call is made."""
    controller, engine, state, backend = setup(registry, make_world, [REST], triggers=("idle",))
    for _ in range(20):
        state, _ = step(controller, engine, state)
    assert len(backend.calls) == 1


@pytest.mark.req("REQ-AGT-001")
def test_need_crossing_act_at_triggers_a_replan(registry: Registry, make_world: MakeWorld) -> None:
    """AC1/AC3: a need rising to act_at fires `need` once."""
    controller, engine, state, backend = setup(registry, make_world, [REST], triggers=("idle", "need"))
    state, _ = step(controller, engine, state)
    state.villagers["ada"].needs["hunger"] = 60.0
    state.villagers["ada"].path, state.villagers["ada"].activity = [], None
    controller.memory["ada"].idle_until = 0
    state, notes = step(controller, engine, state)
    assert dict(notes)["plan_made"]["triggers"] == ["need"]
    controller.memory["ada"].idle_until = 0
    state, notes = step(controller, engine, state)
    assert "plan_made" not in kinds(notes)


@pytest.mark.req("REQ-AGT-001")
def test_periodic_replan_after_replan_hours(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: `periodic` fires once replan_hours have passed since the plan was made."""
    controller, engine, state, backend = setup(
        registry, make_world, [json.dumps({"goal": "rest", "steps": [{"action": "rest", "qty": 99}], "reason": "r"})],
        triggers=("idle", "periodic"), replan_hours=1.0,
    )
    per_hour = 60 // default_config().calendar.tick_minutes
    seen: list[list[str]] = []
    for _ in range(per_hour + 20):
        state, notes = step(controller, engine, state)
        seen += [d["triggers"] for k, d in notes if k == "plan_made"]
    assert seen[0] == ["idle"] and ["periodic"] in seen[1:]


@pytest.mark.req("REQ-AGT-004")
def test_completed_plan_fires_step_completed_and_idle(registry: Registry, make_world: MakeWorld) -> None:
    """AC3: finishing the last step fires `idle` (and `step_completed`) for the next plan."""
    controller, engine, state, backend = setup(registry, make_world, [REST, REST])
    per_hour = 60 // default_config().calendar.tick_minutes
    made: list[list[str]] = []
    steps: list[dict] = []
    for _ in range(per_hour + 30):
        state, notes = step(controller, engine, state)
        made += [d["triggers"] for k, d in notes if k == "plan_made"]
        steps += [d for k, d in notes if k == "plan_step"]
    assert made[:2] == [["idle"], ["idle", "step_completed"]]
    assert steps[0]["status"] == "done" and steps[0]["action"] == "rest"


@pytest.mark.req("REQ-AGT-004")
def test_failed_step_fires_step_failed_and_the_reason_reaches_the_next_prompt(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: an impossible step is marked failed with a reason and fires `step_failed`."""
    controller, engine, state, backend = setup(registry, make_world, [IRON, REST], fallback_hours=0.01)
    state, notes = step(controller, engine, state)
    failed = [d for k, d in notes if k == "plan_step" and d["status"] == "failed"]
    assert failed and failed[0]["reason"] == "no way to gather iron_ore now"
    for _ in range(5):
        state, notes = step(controller, engine, state)
        if "plan_made" in kinds(notes):
            break
    assert "step_failed" in dict(notes)["plan_made"]["triggers"]
    assert "Last step failed: no way to gather iron_ore now" in backend.calls[-1].messages[-1].content


@pytest.mark.req("REQ-AGT-005")
def test_invalid_output_is_retried_with_the_error(registry: Registry, make_world: MakeWorld) -> None:
    """AC1/AC3: an invalid answer is retried with the validation error; both are logged."""
    controller, engine, state, backend = setup(registry, make_world, ["not json", BERRIES])
    state, notes = step(controller, engine, state)
    assert len(backend.calls) == 2
    retry = backend.calls[1].messages
    assert retry[-2].role == "assistant" and retry[-2].content == "not json"
    assert retry[-1].role == "user" and "could not be used" in retry[-1].content
    invalid = dict(notes)["plan_invalid"]
    assert invalid["attempt"] == 0 and invalid["model"] == "m" and invalid["error"]
    assert dict(notes)["plan_made"]["retries"] == 1


@pytest.mark.req("REQ-AGT-005")
def test_invalid_action_target_counts_as_invalid(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a target outside the catalog is invalid output, retried with the error."""
    bad = json.dumps({"goal": "g", "steps": [{"action": "build", "target": "castle"}], "reason": "r"})
    controller, engine, state, backend = setup(registry, make_world, [bad, BERRIES])
    state, notes = step(controller, engine, state)
    assert "'castle' is not a valid target for build" in dict(notes)["plan_invalid"]["error"]


@pytest.mark.req("REQ-AGT-005")
def test_after_retries_the_scripted_mind_takes_over(registry: Registry, make_world: MakeWorld) -> None:
    """AC2/AC3: after max_retries the fallback decides; the fallback is logged with model and reason."""
    controller, engine, state, backend = setup(registry, make_world, ["x", "y", "z", REST])
    scripted = ScriptedMind().decide(controller.view(state), state.villagers["ada"])
    intents = controller.intents(state)
    notes = controller.events()
    assert len(backend.calls) == 3  # first try + max_retries (2)
    fallback = dict(notes)["mind_fallback"]
    assert fallback["model"] == "m" and fallback["flagged"] is False
    assert fallback["reason"].startswith("invalid output after 3 attempts")
    assert [k for k, _ in notes].count("plan_invalid") == 3
    assert intents == [scripted.intent]


@pytest.mark.req("REQ-AGT-005")
def test_no_calls_during_the_fallback_window(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: the scripted mind drives the villager for fallback_hours; then it plans again."""
    controller, engine, state, backend = setup(registry, make_world, ["x", "y", "z", REST], fallback_hours=1.0)
    per_hour = 60 // default_config().calendar.tick_minutes
    for _ in range(per_hour - 1):
        state, _ = step(controller, engine, state)
    assert len(backend.calls) == 3
    for _ in range(40):
        state, _ = step(controller, engine, state)
    assert len(backend.calls) == 4


@pytest.mark.req("REQ-AGT-005")
def test_plan_that_cannot_start_falls_back_instead_of_asking_every_tick(registry: Registry, make_world: MakeWorld) -> None:
    """AC2 (Review Focus 1): a valid plan whose every step fails at once starts the fallback window."""
    controller, engine, state, backend = setup(registry, make_world, [IRON], triggers=("idle",))
    for _ in range(10):
        state, notes = step(controller, engine, state)
    assert len(backend.calls) == 1


@pytest.mark.req("REQ-LLM-009")
def test_live_mode_backend_error_falls_back_and_is_flagged(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: in live mode the villager uses fallback behaviour, and the event is flagged."""
    controller, engine, state, backend = setup(registry, make_world, [FakeError("down")], mode="live")
    state, notes = step(controller, engine, state)
    fallback = dict(notes)["mind_fallback"]
    assert fallback["flagged"] is True and "down" in fallback["reason"]


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_backend_failure_stops_the_tick(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: in wait mode the gateway's BackendUnavailable propagates; no plan is adopted."""
    controller, engine, state, backend = setup(registry, make_world, [FakeError("down")], mode="wait")
    with pytest.raises(BackendUnavailable):
        controller.intents(state)
    assert controller.events() == []


def test_records_of_dead_villagers_are_dropped(registry: Registry, make_world: MakeWorld) -> None:
    """Review Focus 3: a villager that dies leaves no record behind."""
    people = [Villager("ada", "Ada", Coord(2, 2), model="m"), Villager("bo", "Bo", Coord(3, 3), model="m")]
    controller, engine, state, backend = setup(registry, make_world, [REST], villagers=people)
    state, _ = step(controller, engine, state)
    del state.villagers["bo"]
    controller.memory["ada"].idle_until = 0
    state, _ = step(controller, engine, state)
    assert set(controller.to_dict()["minds"]["m"]["records"]) == {"ada"}


def test_snapshot_round_trip_continues_identically(registry: Registry, make_world: MakeWorld) -> None:
    """ADR-0018 §7: a restored mind continues the same step without asking again."""
    controller, engine, state, backend = setup(registry, make_world, [BERRIES])
    for _ in range(5):
        state, _ = step(controller, engine, state)
    blob = controller.to_dict()
    twin, twin_engine, _, twin_backend = setup(registry, make_world, [BERRIES])
    twin.load(blob)
    saved = WorldState.from_dict(state.to_dict())
    a = [step(controller, engine, state)[1] for _ in range(10)]
    b = [step(twin, twin_engine, saved)[1] for _ in range(10)]
    assert a == b and twin_backend.calls == []
```

The repeated `state, x = step(...)` rebinding inside list comprehensions in the last test does not carry state forward. Write it as two explicit loops that each update their own `state` and collect notes; the assertion stays the same. These tests drive the real `Engine`. If a test needs a villager to be due on a particular tick, reset `controller.memory[vid].idle_until` as shown, rather than changing production code.

- [ ] **Step 2: Run the tests to watch them fail**

Run: `uv run pytest tests/pericles/test_planmind.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pericles.agents.planmind'`.

- [ ] **Step 3: Implement `src/pericles/agents/planmind.py`**

```python
"""LLM plan minds: triggers, prompts, retries, fallback, agent events (ADR-0018)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, cast

from pericles.agents.config import RELIEFS, TRIGGERS, AgentConfig, ticks_for_hours
from pericles.agents.controller import WATCHED, Mind, failed_event
from pericles.agents.executor import Progress, advance, begin
from pericles.agents.plan import Catalog, Plan, catalog_for, check_plan
from pericles.agents.prompt import Situation, Template, load_template, plan_messages
from pericles.agents.scripted import ScriptedMind
from pericles.agents.view import Decision, View
from pericles.core.events import Event
from pericles.core.state import Villager, WorldState
from pericles.llm.types import Message, Request, Result

Complete = Callable[[Sequence[Request]], list[Result]]
IDLE, STEP_COMPLETED, STEP_FAILED, NEED, PERIODIC = TRIGGERS
KIND = "plan"


def seed_for(run_seed: int, villager: str, tick: int) -> int:
    digest = hashlib.sha256(f"{run_seed}:{villager}:{tick}".encode()).digest()
    return int.from_bytes(digest[:4], "big")


@dataclass
class Record:
    """One villager's plan state; everything but `decision` is saved (ADR-0018 §7)."""

    plan: Plan | None = None
    index: int = 0
    progress: Progress = field(default_factory=Progress)
    planned_tick: int = 0
    pending: list[str] = field(default_factory=list)
    failure: str | None = None
    above: list[str] = field(default_factory=list)
    fallback_until: int = 0
    decision: Decision | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": None if self.plan is None else self.plan.model_dump(mode="json"),
            "index": self.index,
            "progress": self.progress.to_dict(),
            "planned_tick": self.planned_tick,
            "pending": list(self.pending),
            "failure": self.failure,
            "above": list(self.above),
            "fallback_until": self.fallback_until,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Record:
        plan = data["plan"]
        failure = data["failure"]
        return cls(
            plan=None if plan is None else Plan.model_validate(plan),
            index=int(data["index"]),
            progress=Progress.from_dict(data["progress"]),
            planned_tick=int(data["planned_tick"]),
            pending=[str(t) for t in data["pending"]],
            failure=None if failure is None else str(failure),
            above=[str(r) for r in data["above"]],
            fallback_until=int(data["fallback_until"]),
        )


class PlanMind:
    def __init__(
        self,
        model: str,
        complete: Complete,
        fallback: Mind,
        config: AgentConfig,
        seed: int,
        template: Template,
    ) -> None:
        self.model = model
        self.complete = complete
        self.fallback = fallback
        self.config = config
        self.seed = seed
        self.template = template
        self.records: dict[str, Record] = {}
        self._events: list[tuple[str, dict[str, Any]]] = []

    # -- Planner -----------------------------------------------------------------------

    def prepare(self, view: View, villagers: Sequence[Villager]) -> None:
        alive = view.state.villagers
        self.records = {vid: r for vid, r in self.records.items() if vid in alive}
        asks: dict[str, tuple[str, ...]] = {}
        for villager in villagers:
            record = self.records.setdefault(villager.id, Record())
            record.decision = None
            if view.tick < record.fallback_until:
                continue
            self._run(view.tick, view, villager, record)
            fired = self._fired(view, villager, record)
            if fired:
                asks[villager.id] = fired
        if asks:
            self._plan(view, asks)

    def decide(self, view: View, villager: Villager) -> Decision | None:
        record = self.records.get(villager.id)
        if record is None or record.plan is None or view.tick < record.fallback_until:
            return self.fallback.decide(view, villager)
        return record.decision

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        for event in events:
            if event.kind not in WATCHED or not failed_event(event):
                continue
            vid = str(event.data.get("actor"))
            record = self.records.get(vid)
            villager = state.villagers.get(vid)
            if record is None or villager is None or record.plan is None:
                continue
            if record.index >= len(record.plan.steps):
                continue
            reason = str(event.data.get("reason", event.kind))
            self._failed(state.tick, villager, record, f"{event.kind}: {reason}")

    def take_events(self) -> list[tuple[str, dict[str, Any]]]:
        out, self._events = self._events, []
        return out

    def to_dict(self) -> dict[str, Any]:
        return {"records": {vid: self.records[vid].to_dict() for vid in sorted(self.records)}}

    def parse(self, data: Mapping[str, Any]) -> object:
        return {str(vid): Record.from_dict(r) for vid, r in data["records"].items()}

    def restore(self, parsed: object) -> None:
        self.records = cast(dict[str, Record], parsed)

    # -- Steps -------------------------------------------------------------------------

    def _note(self, kind: str, **data: Any) -> None:
        self._events.append((kind, {"model": self.model, **data}))

    def _start(self, tick: int, villager: Villager, record: Record) -> None:
        assert record.plan is not None
        steps = record.plan.steps
        record.progress = begin(tick, villager, steps[record.index]) if record.index < len(steps) else Progress()

    def _failed(self, tick: int, villager: Villager, record: Record, reason: str) -> None:
        assert record.plan is not None
        step = record.plan.steps[record.index]
        self._note("plan_step", actor=villager.id, index=record.index, action=step.action,
                   target=step.target, status="failed", reason=reason)
        record.failure = reason
        record.pending.append(STEP_FAILED)
        record.index += 1
        self._start(tick, villager, record)

    def _run(self, tick: int, view: View, villager: Villager, record: Record) -> None:
        """Advance the plan past finished or failed steps to this tick's decision."""
        while record.plan is not None:
            steps = record.plan.steps
            if record.index >= len(steps):
                record.plan = None
                record.pending.append(IDLE)
                return
            step = steps[record.index]
            outcome = advance(view, villager, step, record.progress)
            if outcome.done:
                self._note("plan_step", actor=villager.id, index=record.index,
                           action=step.action, target=step.target, status="done")
                record.pending.append(STEP_COMPLETED)
                record.index += 1
                self._start(tick, villager, record)
                continue
            if outcome.failed is not None:
                self._failed(tick, villager, record, outcome.failed)
                continue
            record.decision = outcome.decision
            return

    def _fired(self, view: View, villager: Villager, record: Record) -> tuple[str, ...]:
        fired = set(record.pending)
        if record.plan is None:
            fired.add(IDLE)
        now = [r for r in RELIEFS if view.level(villager, r) >= self.config.act_at[r]]
        if set(now) - set(record.above):
            fired.add(NEED)
        record.above = now
        replan = ticks_for_hours(view.ctx.config.calendar.tick_minutes, self.config.replan_hours)
        if record.plan is not None and view.tick - record.planned_tick >= replan:
            fired.add(PERIODIC)
        return tuple(t for t in TRIGGERS if t in fired and t in self.config.triggers)

    # -- Planning ----------------------------------------------------------------------

    def _plan(self, view: View, asks: Mapping[str, tuple[str, ...]]) -> None:
        villagers = view.state.villagers
        catalogs: dict[str, Catalog] = {}
        batch: list[Request] = []
        for vid in sorted(asks):
            villager, record = villagers[vid], self.records[vid]
            catalogs[vid] = catalog_for(view, villager)
            situation = Situation(asks[vid], record.plan, record.index, record.failure)
            messages = plan_messages(view, villager, situation, catalogs[vid], self.template)
            batch.append(
                Request(KIND, vid, view.tick, self.model, messages,
                        seed_for(self.seed, vid, view.tick), output=Plan, template=self.template.version)
            )
        adopted: dict[str, tuple[Plan, int]] = {}
        dropped: dict[str, tuple[str, bool]] = {}
        notes: list[tuple[str, dict[str, Any]]] = []
        while batch:
            retry: list[Request] = []
            for result in self.complete(batch):
                request, vid = result.request, result.request.villager
                if result.backend_error is not None:
                    dropped[vid] = (f"backend: {result.backend_error}", True)
                    continue
                error = result.error
                plan = cast(Plan | None, result.value)
                if error is None and plan is not None:
                    error = check_plan(plan, catalogs[vid], self.config.max_plan_steps)
                if error is None and plan is not None:
                    adopted[vid] = (plan, request.attempt)
                    continue
                notes.append(("plan_invalid", {"model": self.model, "actor": vid,
                                               "attempt": request.attempt, "error": error}))
                if request.attempt < self.config.max_retries:
                    retry.append(self._retry(request, result.text, str(error)))
                else:
                    dropped[vid] = (f"invalid output after {request.attempt + 1} attempts: {error}", False)
            batch = retry
        self._events.extend(notes)
        fallback = ticks_for_hours(view.ctx.config.calendar.tick_minutes, self.config.fallback_hours)
        for vid in sorted(asks):
            villager, record = villagers[vid], self.records[vid]
            if vid in adopted:
                plan, retries = adopted[vid]
                self._note("plan_made", actor=vid, triggers=list(asks[vid]), goal=plan.goal,
                           steps=[s.model_dump(mode="json") for s in plan.steps], reason=plan.reason,
                           retries=retries, template=self.template.version)
                record.plan, record.index, record.planned_tick = plan, 0, view.tick
                record.pending, record.failure, record.decision = [], None, None
                self._start(view.tick, villager, record)
                self._run(view.tick, view, villager, record)
                if record.plan is None:  # it ended or failed at once (Review Focus 1)
                    dropped[vid] = ("the plan gave nothing to do", False)
                else:
                    continue
            reason, flagged = dropped[vid]
            self._note("mind_fallback", actor=vid, reason=reason, flagged=flagged)
            record.plan, record.pending, record.decision = None, [], None
            record.fallback_until = view.tick + fallback

    def _retry(self, request: Request, text: str, error: str) -> Request:
        follow = self.template.retry.substitute(error=error)
        messages = (*request.messages, Message("assistant", text), Message("user", follow))
        return replace(request, messages=messages, attempt=request.attempt + 1)


def plan_minds(
    models: Iterable[str], complete: Complete, config: AgentConfig, seed: int
) -> dict[str, PlanMind]:
    """One plan mind per model key, sharing the gateway and the scripted fallback."""
    template = load_template(config.plan_template)
    return {
        key: PlanMind(key, complete, ScriptedMind(), config, seed, template)
        for key in sorted(models)
    }
```

Notes for the implementer:
- `Request` is positional with fields `kind, villager, tick, model, messages, seed, output, attempt, template`. Check `llm/types.py` and use keywords if that reads better.
- `failed_event` and `WATCHED` come from Task 2. `observe` uses the post-step `state.tick` as the start tick of the next step's progress. Engine failures arrive after the step, so this is the tick the next step can begin.
- In `test_after_retries_the_scripted_mind_takes_over`, the fallback mind decides on the same tick (`decide` sees `fallback_until > tick`).
- `plan_made.retries` is the attempt index of the accepted answer (0 means first try).

- [ ] **Step 4: Run the tests to watch them pass**

Run: `uv run pytest tests/pericles/test_planmind.py -q`
Expected: PASS. If a test's timing assumption about due ticks fails (for example the villager is not due because it is still walking), fix the test's setup (reset `idle_until`, place the node closer). Never weaken an assertion about calls, triggers or events.

- [ ] **Step 5: Run the gates and the mutation gate (agents ≥ 70%), then commit**

```bash
git add src/pericles/agents/planmind.py tests/pericles/test_planmind.py
git commit -m "feat(agents): LLM plan minds with triggers, retries and scripted fallback

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 8: Runs use plan minds; drawn traits; example experiment

**Files:**
- Create: `src/pericles/experiment/traits.py`
- Modify: `src/pericles/experiment/config.py` (`VillagerSpec.traits` optional; draw; template check)
- Modify: `src/pericles/experiment/launch.py`
- Create: `experiments/llm-village.yaml`
- Modify: `README.md` (the "Language models" section)
- Test: `tests/pericles/test_traits.py` (create), `tests/pericles/test_llm_launch.py`, `tests/pericles/test_experiment_config.py`

**Interfaces:**
- Consumes: `plan_minds` (Task 7), `load_template`, `TemplateError` (Task 6)
- Produces:
  - `pericles.experiment.traits.draw_traits(population: Sequence[VillagerSpec], traits: Sequence[str], count: int, seed: int) -> list[VillagerSpec]`
  - `launch._controller(experiment: Experiment, engine: Engine, gateway: Gateway) -> Controller`
  - `meta.json` gains `"templates": {"plan": "<version>"}`

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_traits.py`:

```python
import pytest

from pericles.experiment.config import VillagerSpec
from pericles.experiment.traits import draw_traits

IDS = ("altruistic", "dutiful", "fearful", "greedy", "industrious", "rebellious")


def spec(vid: str, traits: tuple[str, ...] | None = None) -> VillagerSpec:
    data = {"id": vid, "name": vid.title(), "age_days": 200}
    if traits is not None:
        data["traits"] = traits
    return VillagerSpec.model_validate(data)


@pytest.mark.req("REQ-AGT-009")
def test_omitted_traits_are_drawn_with_the_seed_and_given_traits_kept() -> None:
    """AC1: traits come from config, or are drawn with the seeded RNG."""
    population = [spec("ada"), spec("bram", ("greedy",)), spec("cora", ())]
    drawn = draw_traits(population, IDS, 2, seed=5)
    assert drawn[1].traits == ("greedy",) and drawn[2].traits == ()
    assert drawn[0].traits is not None and len(drawn[0].traits) == 2
    assert len(set(drawn[0].traits)) == 2 and set(drawn[0].traits) <= set(IDS)
    assert drawn[0].traits == tuple(sorted(drawn[0].traits))
    assert draw_traits(population, IDS, 2, seed=5) == drawn
    others = {draw_traits(population, IDS, 2, seed=s)[0].traits for s in range(20)}
    assert len(others) > 1


def test_zero_count_draws_nothing_and_too_many_is_an_error() -> None:
    assert draw_traits([spec("ada")], IDS, 0, seed=1)[0].traits is None
    with pytest.raises(ValueError, match="drawn_traits: 7 is more than the 6 traits"):
        draw_traits([spec("ada")], IDS, 7, seed=1)
```

Append to `tests/pericles/test_experiment_config.py`. Use the file's helper for building a minimal experiment mapping.

```python
@pytest.mark.req("REQ-AGT-009")
def test_drawn_traits_are_recorded_in_the_resolved_population(...) -> None:
    """AC1: with agents.drawn_traits: 2, entries without traits get two, pinned in resolved."""
    # mapping with agents: {drawn_traits: 2} and one villager without traits
    # experiment = experiment_from_mapping(mapping, base)
    # assert len(experiment.resolved["population"][0]["traits"]) == 2
    # assert experiment_from_mapping(experiment.resolved, base).resolved == experiment.resolved


def test_unknown_plan_template_is_an_experiment_error(...) -> None:
    # mapping with agents: {plan_template: plan.v9}
    # with pytest.raises(ExperimentError, match="agents.plan_template: prompt template 'plan.v9'"):
    #     experiment_from_mapping(mapping, base)
```

Write the bodies with that file's existing helpers (look for how other tests build a mapping, then `experiment_from_mapping(...)`). The comments give the assertions.

Append to `tests/pericles/test_llm_launch.py`. Reuse its fake-backend experiment helper: the file already builds experiments with a `fake` backend and a replies file.

```python
@pytest.mark.req("REQ-AGT-001")
def test_villagers_with_a_model_plan_through_the_gateway(...) -> None:
    """AC1/AC3: a started run with a model villager logs plan_made events with triggers."""
    # replies file: one rule kind=plan replying a valid rest plan
    # session = start(experiment, out); advance(session, days=1); session.close()
    # events = list(RunDirectory.open(out).event_log.events())
    # made = [e for e in events if e.kind == "plan_made"]
    # assert made and made[0].data["triggers"] == ["idle"] and made[0].data["model"] == "<key>"
    # and the call log has rows with template "plan.v1" and kind "plan"


@pytest.mark.req("REQ-AGT-010")
def test_template_version_is_in_meta_json(...) -> None:
    """AC2: the template version is recorded in meta.json and each LLM call."""
    # assert json.loads((out / "meta.json").read_text())["templates"] == {"plan": "plan.v1"}


def test_resume_mid_plan_continues_without_a_new_call(...) -> None:
    """Review Focus 2: stop mid-plan, reopen, continue; the event log equals an
    uninterrupted run's and the reopened backend gets no plan call until a trigger fires."""
    # Use one fake rule that always answers the same multi-step plan (a long rest, qty 12),
    # so the fake's reply counter cannot differ after reopening.
    # Run A: start, advance(days=2), digest.
    # Run B: start, advance(days=1), close; reopen, advance(days=2), digest.
    # assert digest A == digest B
```

Write these bodies with the helpers in `test_llm_launch.py`.

- [ ] **Step 2: Run the tests to watch them fail**

Run: `uv run pytest tests/pericles/test_traits.py tests/pericles/test_llm_launch.py tests/pericles/test_experiment_config.py -q`
Expected: FAIL. `pericles.experiment.traits` is missing, no `plan_made` events appear, and there is no `templates` key.

- [ ] **Step 3: Implement**

`src/pericles/experiment/traits.py`:

```python
"""Seeded trait draws for population entries that leave traits out (REQ-AGT-009; ADR-0018 §10)."""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pericles.experiment.config import VillagerSpec


def draw_traits(
    population: Sequence[VillagerSpec], traits: Sequence[str], count: int, seed: int
) -> list[VillagerSpec]:
    if count > len(traits):
        raise ValueError(f"drawn_traits: {count} is more than the {len(traits)} traits in the packs")
    if count == 0:
        return list(population)
    rng = random.Random(f"traits:{seed}")
    pool = sorted(traits)
    return [
        spec
        if spec.traits is not None
        else spec.model_copy(update={"traits": tuple(sorted(rng.sample(pool, count)))})
        for spec in population
    ]
```

In `src/pericles/experiment/config.py`:
- Change the field to `traits: tuple[StrictStr, ...] | None = None` in `VillagerSpec`.
- Replace each use of `spec.traits` with `spec.traits or ()`: the known-trait check at `:215` and the `Villager(...)` construction at `:341`.
- Where `assign_models` is applied (`:291`), draw traits right after it:
  ```python
  try:
      population = draw_traits(population, sorted(registry.traits), agents.drawn_traits, seed)
  except ValueError as error:
      raise ExperimentError(f"agents.{error}") from None
  ```
  Use the local names the function already has for the registry, the agent config and the seed.
- Next to the other agent-config checks, add:
  ```python
  try:
      load_template(agents.plan_template)
  except TemplateError as error:
      raise ExperimentError(f"agents.plan_template: {error}") from None
  ```
- The resolved population is dumped with `exclude_defaults=True`, so drawn traits (non-`None`) are recorded and a reopen re-reads them.

In `src/pericles/experiment/launch.py`:

```python
from pericles.agents.planmind import plan_minds


def _controller(experiment: Experiment, engine: Engine, gateway: Gateway) -> Controller:
    """Scripted minds plus one plan mind per model key (ADR-0018 §1)."""
    minds = plan_minds(experiment.llm.models, gateway.complete_all, experiment.agents, experiment.seed)
    return scripted_controller(engine.context, experiment.agents, minds)
```

In `start`:
- Remove the early `controller = scripted_controller(...)`.
- Pass `extra={**run_meta(experiment.llm), "templates": {"plan": experiment.agents.plan_template}}` to `RunDirectory.create`.
- After `gateway = open_gateway(...)` succeeds, build `controller = _controller(experiment, engine, gateway)` inside the same `try`, so a failure there also undoes the directory.

In `reopen`:

```python
    run_dir = RunDirectory.open(out)
    gateway: Gateway | None = None
    try:
        experiment = experiment_from_mapping(run_dir.config, run_dir.path)
        engine = Engine(experiment.registry, experiment.engine)
        backends = _backends(experiment)
        gateway = open_gateway(experiment.llm, backends, run_dir)
        controller = _controller(experiment, engine, gateway)
        state, _ = resume(run_dir, controller.load)
        if gateway.calls is not None:
            gateway.calls.truncate_after(state.tick - 1)
    except BaseException:
        if gateway is not None:
            gateway.close()
        run_dir.close()
        raise
    return Session(run_dir, experiment, engine, state, controller, gateway)
```

Create `experiments/llm-village.yaml`. Copy the `map:` block from `baseline.yaml`, then add:

```yaml
# An LLM village: six adults planned by a local Ollama model, two scripted (ADR-0018).
# Needs `ollama serve` and `ollama pull llama3.1:8b`. Replay a recorded run with
# llm: {cache: replay, cache_from: runs/<name>/llm_cache.sqlite}.
seed: 1
packs: [base]
map:
  # (same as baseline.yaml)
population:
  - {id: ada, name: Ada, sex: female, age_days: 210, model: llama, skills: {foraging: 20.0}, inventory: {berries: 4}}
  - {id: bram, name: Bram, sex: male, age_days: 260, model: llama, skills: {woodcutting: 25.0}, inventory: {berries: 4}}
  - {id: cora, name: Cora, sex: female, age_days: 180, model: llama, skills: {masonry: 20.0}, inventory: {berries: 4}}
  - {id: dov, name: Dov, sex: male, age_days: 300, model: llama, skills: {woodcutting: 15.0, masonry: 10.0}, inventory: {berries: 4}}
  - {id: elin, name: Elin, sex: female, age_days: 150, model: llama, skills: {fishing: 20.0}, inventory: {berries: 4}}
  - {id: fenn, name: Fenn, sex: male, age_days: 140, model: llama, skills: {hunting: 20.0}, inventory: {berries: 4}}
  - {id: greta, name: Greta, sex: female, age_days: 380, traits: [fearful], skills: {foraging: 30.0}, inventory: {berries: 4}}
  - {id: hugo, name: Hugo, sex: male, age_days: 220, traits: [], skills: {masonry: 25.0}, inventory: {berries: 4}}
agents:
  drawn_traits: 2
llm:
  backends:
    local: {kind: ollama}
  models:
    llama: {backend: local, name: "llama3.1:8b"}
run:
  days: 3
  snapshot_every_days: 1
```

Match the `llm:` keys to the shape `llm_config_from_mapping` reads: `backends.<key>.kind`, `models.<key>.backend` and `.name`. The URL comes from `ollama_url` in the default settings.

Add a test in `tests/pericles/test_experiment_config.py` that `experiments/llm-village.yaml` loads with `load_experiment` (or this repo's loader), using the same approach as any existing `baseline.yaml` loading test. Loading does not contact Ollama.

In `README.md`'s "Language models" section, replace the M2a paragraph saying villagers still use the scripted mind with:

> Villagers with a `model:` are planned by that model (ADR-0018). When a trigger fires (idle, step done or failed, a need reaching its level, or every `replan_hours`), the villager asks for a short plan of village jobs, which plain code then carries out. Invalid plans are retried with the error, then the scripted mind takes over for `fallback_hours`. Plans, retries and fallbacks appear in `events.sqlite`. `experiments/llm-village.yaml` is a ready example: `uv run pericles run experiments/llm-village.yaml runs/llm`.

Check the CLI command against the README's existing usage lines and use the same form.

- [ ] **Step 4: Run the tests to watch them pass**

Run: `uv run pytest tests/pericles/test_traits.py tests/pericles/test_llm_launch.py tests/pericles/test_experiment_config.py tests/pericles/test_llm_runs.py tests/pericles/test_cli.py tests/pericles/test_baseline.py -q`
Expected: PASS. `baseline.yaml` behaviour is unchanged, because `drawn_traits` defaults to 0.

- [ ] **Step 5: Check that the tests catch breaks**

`pericles.experiment` is not mutation-gated, so check by hand:
1. Temporarily make `draw_traits` ignore `seed`. The determinism and variety assertions must fail.
2. Temporarily drop the `templates` key. The meta test must fail.
3. Temporarily build the controller with no minds. The `plan_made` test must fail.

Revert each change, and record all three in the report.

- [ ] **Step 6: Run the gates, then commit**

```bash
git add src/pericles/experiment/ experiments/llm-village.yaml README.md tests/pericles/
git commit -m "feat(experiment): runs plan model villagers through the gateway; drawn traits; LLM example

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 9: Golden replay run (REQ-NFR-001)

**Files:**
- Create: `tests/golden/village.yaml`, `tests/golden/plans.yaml`, `tests/golden/village.digest`
- Test: `tests/pericles/test_golden.py`

**Interfaces:**
- Consumes:
  - `launch.start`, `launch.advance`
  - `RunDirectory.open(...).event_log.digest()`
  - `Session.gateway.backends`
  - the experiment loader
- Produces: none.

The golden experiment is small: a 32×32 map, 4 adults, all with `model: fake`, and 3 days. One backend has `kind: fake` with `replies: plans.yaml`.

The replies use the fake's rules, matched in file order by `kind`, `villager` and `pattern` against the last message.
- One rule matches any `plan` call whose last message contains `"(urgent)"`, with a plan of `eat` then `gather berries 4`.
- One rule for villager `cora` replies first with `"not json"`, then with a valid gather-and-store plan, which exercises a retry (Review Focus 5).
- A catch-all `plan` rule cycles through a `gather wood 4`, `build house` plan, a `rest 2` plan and a `sleep` plan.

The cache mode is `record`. The replay leg copies `llm_cache.sqlite` and runs with `cache: replay`.

- [ ] **Step 1: Write the golden files**

Write `tests/golden/plans.yaml`:

```yaml
- kind: plan
  pattern: "\\(urgent\\)"
  replies:
    - '{"goal": "eat", "steps": [{"action": "eat"}, {"action": "gather", "target": "berries", "qty": 4}], "reason": "hungry"}'
- kind: plan
  villager: cora
  replies:
    - "not json"
    - '{"goal": "stock up", "steps": [{"action": "gather", "target": "berries", "qty": 6}, {"action": "store", "target": "berries"}], "reason": "winter"}'
    - '{"goal": "rest", "steps": [{"action": "rest", "qty": 2}], "reason": "tired"}'
- kind: plan
  replies:
    - '{"goal": "a house", "steps": [{"action": "gather", "target": "wood", "qty": 4}, {"action": "build", "target": "house"}], "reason": "shelter"}'
    - '{"goal": "rest", "steps": [{"action": "rest", "qty": 2}], "reason": "tired"}'
    - '{"goal": "sleep", "steps": [{"action": "sleep"}], "reason": "night"}'
```

Write `tests/golden/village.yaml`:
- seed 3, packs `[base]`
- a 32×32 map with the baseline bands and no veins
- four adults (`ada`, `bram`, `cora`, `dov`) with `model: fake`, foraging skills and 4 berries each
- `llm`:
  - `backends: {f: {kind: fake, replies: plans.yaml}}`
  - `models: {fake: {backend: f, name: fake-model}}`
  - `cache: record`, `failure_mode: wait`. Use the exact key names in `llm/config.py`.
- `run: {days: 3, snapshot_every_days: 1}`

Resolve `replies` paths relative to the experiment file the same way M2a does; check `experiment/llm.py`'s `build_backends`.

- [ ] **Step 2: Write the failing test**

Create `tests/pericles/test_golden.py`:

```python
import os
import shutil
from pathlib import Path

import pytest

from pericles.experiment.config import load_experiment  # use this repo's loader name
from pericles.experiment.launch import advance, start
from pericles.experiment.rundir import RunDirectory

GOLDEN = Path(__file__).parent.parent / "golden"
UPDATE = os.environ.get("PERICLES_UPDATE_GOLDEN") == "1"


def recorded(tmp_path: Path) -> tuple[str, Path]:
    session = start(load_experiment(GOLDEN / "village.yaml"), tmp_path / "rec")
    advance(session)
    session.close()
    out = tmp_path / "rec"
    return RunDirectory.open(out).event_log.digest(), out


@pytest.mark.req("REQ-NFR-001")
def test_golden_run_digest_is_pinned_and_replay_reproduces_it(tmp_path: Path) -> None:
    """AC1: same config, seed and LLM cache in replay mode give the identical event-log hash."""
    digest, out = recorded(tmp_path)
    pinned = GOLDEN / "village.digest"
    if UPDATE:
        pinned.write_text(digest + "\n", encoding="utf-8")
    assert digest == pinned.read_text(encoding="utf-8").strip()
    cache = tmp_path / "cache.sqlite"
    shutil.copy(out / "llm_cache.sqlite", cache)  # the recorded cache's file name in a run dir
    experiment = load_experiment(GOLDEN / "village.yaml", llm={"cache": "replay", "cache_from": str(cache)})
    session = start(experiment, tmp_path / "replay")
    advance(session)
    assert sum(len(b.calls) for b in session.gateway.backends.values()) == 0  # type: ignore[attr-defined]
    session.close()
    assert RunDirectory.open(tmp_path / "replay").event_log.digest() == digest


def test_golden_run_exercises_plans_retries_and_steps(tmp_path: Path) -> None:
    _, out = recorded(tmp_path)
    kinds = [e.kind for e in RunDirectory.open(out).event_log.events()]
    assert kinds.count("plan_made") >= 4
    assert "plan_invalid" in kinds
    assert "plan_step" in kinds
```

Adapt `load_experiment(..., llm=...)` to however this repo overrides one experiment's settings. For example, read the YAML, set `mapping["llm"]["cache"] = "replay"` and `["cache_from"]`, then build with `experiment_from_mapping(mapping, GOLDEN)`. Check the run directory's cache file name in `experiment/llm.py` / `RunDirectory`.

- [ ] **Step 3: Run it to watch it fail, then pin the digest**

Run: `uv run pytest tests/pericles/test_golden.py -q`
Expected: FAIL, because `village.digest` is missing.

Run: `PERICLES_UPDATE_GOLDEN=1 uv run pytest tests/pericles/test_golden.py -q`, then `uv run pytest tests/pericles/test_golden.py -q`
Expected: PASS both times. The digest file now holds one hex line.

Then run the test three times in a row (`for i in 1 2 3; do uv run pytest tests/pericles/test_golden.py -q; done`) to confirm the record leg is deterministic. With concurrency 1, the fake backend's reply order follows request order, which is sorted by villager id.

- [ ] **Step 4: Check the runtime**

Run: `uv run pytest tests/pericles/test_golden.py -q --durations=3`
Expected: under 30 s in total. If it is slower, reduce to 2 days or a 24×24 map, re-pin, and say so in the report.

- [ ] **Step 5: Run the gates, then commit**

```bash
git add tests/golden tests/pericles/test_golden.py
git commit -m "test: golden replay run pins the event-log hash of an LLM village

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```

---

### Task 10: Requirements, traceability and README status

**Files:**
- Modify: `docs/requirements/agt.md`, `docs/requirements/llm.md`, `docs/requirements/nfr.md`
- Modify: `docs/requirements/traceability.md` (regenerated)
- Modify: `README.md` (status line)
- Test: `PYTHONPATH=tools uv run python -m pericles_tools.traceability check`

- [ ] **Step 1: Update the statuses**

Set `Implemented` on:
- REQ-AGT-001, REQ-AGT-003, REQ-AGT-004, REQ-AGT-005, REQ-AGT-009, REQ-AGT-010
- REQ-LLM-009
- REQ-NFR-001

Leave REQ-AGT-002 `Accepted`. Its AC1 sections for memories, opinions, laws, sanctions and board posts arrive in M2c and M3. Follow `docs/requirements/README.md` "Revising requirements" for the status-change convention.

- [ ] **Step 2: Regenerate the matrix and check it**

Run: `PYTHONPATH=tools uv run python -m pericles_tools.traceability matrix && PYTHONPATH=tools uv run python -m pericles_tools.traceability check`
Expected: exit 0. Every Implemented requirement has linked tests.

- [ ] **Step 3: Update the README status line**

Change the status line to: "M2b, LLM plan minds, is done. Next is M2c: memory, reflection and opinions."

- [ ] **Step 4: Run the full gates and the slow tests**

Run all the gates, then `uv run pytest -m slow -q`. This needs Ollama running and the MLX extra installed. Expected: all pass.

Optionally, as a live smoke test: `uv run pericles run experiments/llm-village.yaml /tmp/llm-smoke --days 1`, using the CLI's real flags. Record in the report whether villagers made plans and how many fallbacks happened. This is evidence for the PR, not a gate.

- [ ] **Step 5: Commit**

```bash
git add docs/requirements README.md
git commit -m "docs: plan-mind requirements implemented, traceability, README status

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01K3QfPmiNyMBLZ6s8bRnsHa"
```
