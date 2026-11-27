import json
from collections.abc import Callable, Sequence

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller, Planner
from pericles.agents.executor import Progress, begin
from pericles.agents.plan import Plan, Step
from pericles.agents.planmind import PlanMind, Record, plan_minds, seed_for
from pericles.agents.scripted import ScriptedMind, scripted_controller
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Craft, Intent, Research
from pericles.core.inventory import Inventory
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config
from pericles.llm.cache import ResponseCache
from pericles.llm.fake import FakeBackend, FakeError, FakeRule
from pericles.llm.gateway import BackendUnavailable, FailurePolicy, Gateway
from pericles.llm.types import ModelSpec, Request, Result, Sampling

MakeWorld = Callable[..., WorldState]
Notes = list[tuple[str, dict]]  # type: ignore[type-arg]
ROWS = ["." * 16] * 16
REST = json.dumps({"goal": "rest", "steps": [{"action": "rest", "qty": 1}], "reason": "tired"})
BERRIES = json.dumps(
    {
        "goal": "food",
        "steps": [{"action": "gather", "target": "berries", "qty": 2}, {"action": "eat"}],
        "reason": "hungry",
    }
)
SNAP = json.dumps(
    {
        "goal": "food",
        "steps": [
            {"action": "gather", "target": "berries", "qty": 2},
            {"action": "rest", "qty": 5},
        ],
        "reason": "hungry",
    }
)
IRON = json.dumps(
    {"goal": "iron", "steps": [{"action": "gather", "target": "iron_ore"}], "reason": "tools"}
)


def setup(
    registry: Registry,
    make_world: MakeWorld,
    replies: Sequence[str | FakeError],
    *,
    mode: str = "wait",
    villagers: Sequence[Villager] | None = None,
    rules: Sequence[FakeRule] = (),
    **config: object,
) -> tuple[Controller, Engine, WorldState, FakeBackend]:
    agents = AgentConfig(**config)  # type: ignore[arg-type]
    backend = FakeBackend([*rules, FakeRule(tuple(replies), kind="plan")])
    gateway = Gateway(
        {"m": ModelSpec("f", "fake-model", Sampling(0.7, 0.9, 256))},
        {"f": backend},
        ResponseCache(None, "off"),
        FailurePolicy(mode, 0.0, 2.0, 0.0, 2),
        sleep=lambda s: None,
    )
    engine = Engine(registry, default_config())
    controller = scripted_controller(
        engine.context, agents, plan_minds(["m"], gateway.complete_all, agents, seed=7)
    )
    people = (
        villagers if villagers is not None else [Villager("ada", "Ada", Coord(2, 2), model="m")]
    )
    state = make_world(ROWS, people, nodes=[Node("n0", "berry_bush", Coord(4, 2), 50)])
    return controller, engine, state, backend


def step(controller: Controller, engine: Engine, state: WorldState) -> tuple[WorldState, Notes]:
    state, events = engine.step(state, controller.intents(state))
    controller.observe(state, events)
    return state, controller.events()


def tick(controller: Controller, state: WorldState, events: Sequence[Event] = ()) -> list[Intent]:
    """One tick without the engine: decide, then observe `events` as if the engine sent them."""
    intents = controller.intents(state)
    state.tick += 1
    controller.observe(state, events)
    return intents


def kinds(notes: Notes) -> list[str]:
    return [k for k, _ in notes]


def mind_of(controller: Controller) -> PlanMind:
    mind = controller.minds["m"]
    assert isinstance(mind, PlanMind)
    return mind


def test_plan_mind_is_a_planner(registry: Registry) -> None:
    mind = plan_minds(["m"], lambda rs: [], AgentConfig(), seed=1)["m"]
    assert isinstance(mind, Planner) and isinstance(mind, PlanMind)


def test_seed_for_is_stable_and_differs_by_villager_and_tick() -> None:
    assert seed_for(7, "ada", 3) == seed_for(7, "ada", 3)
    seeds = {seed_for(7, "ada", 3), seed_for(7, "bram", 3), seed_for(7, "ada", 4)}
    assert len(seeds | {seed_for(8, "ada", 3)}) == 4
    assert 0 <= seed_for(7, "ada", 3) < 2**32


@pytest.mark.req("REQ-AGT-001")
def test_first_tick_plans_on_idle_and_records_the_trigger(
    registry: Registry, make_world: MakeWorld
) -> None:
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
    controller, engine, state, backend = setup(
        registry, make_world, [REST], triggers=("idle", "need")
    )
    state, _ = step(controller, engine, state)
    state.villagers["ada"].needs["hunger"] = AgentConfig().act_at["eat"]  # exactly at act_at
    state.villagers["ada"].path, state.villagers["ada"].activity = [], None
    controller.memory["ada"].idle_until = 0
    state, notes = step(controller, engine, state)
    assert dict(notes)["plan_made"]["triggers"] == ["need"]
    assert "Goal: rest" in backend.calls[-1].messages[-1].content  # the plan it replaces
    controller.memory["ada"].idle_until = 0
    state, notes = step(controller, engine, state)
    assert "plan_made" not in kinds(notes)


@pytest.mark.req("REQ-AGT-001")
def test_periodic_replan_after_replan_hours(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: `periodic` fires once replan_hours have passed since the plan was made."""
    long_rest = json.dumps(
        {"goal": "rest", "steps": [{"action": "rest", "qty": 99}], "reason": "r"}
    )
    controller, engine, state, _backend = setup(
        registry, make_world, [long_rest], triggers=("idle", "periodic"), replan_hours=1.0
    )
    per_hour = 60 // default_config().calendar.tick_minutes
    seen: list[list[str]] = []
    for _ in range(per_hour + 20):
        state, notes = step(controller, engine, state)
        seen += [d["triggers"] for k, d in notes if k == "plan_made"]
    assert seen[0] == ["idle"] and ["periodic"] in seen[1:]


@pytest.mark.req("REQ-AGT-004")
def test_completed_plan_fires_step_completed_and_idle(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC3: finishing the last step fires `idle` (and `step_completed`) for the next plan."""
    controller, engine, state, _backend = setup(registry, make_world, [REST, REST])
    per_hour = 60 // default_config().calendar.tick_minutes
    made: list[list[str]] = []
    steps: list[dict] = []  # type: ignore[type-arg]
    for _ in range(per_hour + 30):
        state, notes = step(controller, engine, state)
        made += [d["triggers"] for k, d in notes if k == "plan_made"]
        steps += [d for k, d in notes if k == "plan_step"]
    assert made[:2] == [["idle"], ["idle", "step_completed"]]
    assert steps[0]["status"] == "done" and steps[0]["action"] == "rest"


@pytest.mark.req("REQ-AGT-004")
def test_failed_step_fires_step_failed_and_the_reason_reaches_the_next_prompt(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: an impossible step is marked failed with a reason and fires `step_failed`."""
    controller, engine, state, backend = setup(
        registry, make_world, [IRON, REST], fallback_hours=0.01
    )
    state, notes = step(controller, engine, state)
    failed = [d for k, d in notes if k == "plan_step" and d["status"] == "failed"]
    assert failed[:1] == [
        {
            "model": "m",
            "actor": "ada",
            "index": 0,
            "action": "gather",
            "target": "iron_ore",
            "status": "failed",
            "reason": "no iron_ore source within reach",
        }
    ]
    for _ in range(5):
        ada = state.villagers["ada"]  # the scripted fallback walks her off; make her due again
        ada.path, ada.activity = [], None
        controller.memory["ada"].idle_until = 0
        state, notes = step(controller, engine, state)
        if "plan_made" in kinds(notes):
            break
    assert "step_failed" in dict(notes)["plan_made"]["triggers"]
    assert (
        "Last step failed: no iron_ore source within reach"
        in backend.calls[-1].messages[-1].content
    )


@pytest.mark.req("REQ-AGT-004")
def test_research_interrupted_because_already_known_completes_the_step(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: research the engine stops as already_known, once the technology is known, is done."""
    research = json.dumps(
        {"goal": "learn", "steps": [{"action": "research", "target": "metallurgy"}], "reason": "r"}
    )
    ada = Villager("ada", "Ada", Coord(2, 2), model="m", inventory=Inventory({"iron_ore": 2}))
    controller, _engine, state, _backend = setup(registry, make_world, [research], villagers=[ada])
    school = Building("b1", "school", Coord(3, 2), Ownership("communal"), complete=True)
    state.buildings["b1"] = school
    intents = tick(controller, state)
    assert any(isinstance(i, Research) for i in intents)
    assert "plan_step" not in kinds(controller.events())
    ada.knowledge.add("metallurgy")  # someone else's research finished it (village scope)
    data = {"actor": "ada", "cause": "engine", "reason": "already_known"}
    controller.observe(state, [Event(state.tick, 0, "work_interrupted", data)])
    assert "plan_step" not in kinds(controller.events())  # observe decides nothing by itself
    tick(controller, state)
    steps = [d for k, d in controller.events() if k == "plan_step"]
    assert [(d["action"], d["status"]) for d in steps] == [("research", "done")]


@pytest.mark.req("REQ-AGT-004")
def test_rejected_intent_fails_the_step_on_its_next_due_tick(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: an engine rejection fails the step with its reason; the next step starts afresh."""
    plan = json.dumps(
        {
            "goal": "g",
            "steps": [{"action": "rest", "qty": 3}, {"action": "gather", "target": "berries"}],
            "reason": "r",
        }
    )
    ada = Villager("ada", "Ada", Coord(2, 2), model="m", inventory=Inventory({"berries": 2}))
    controller, _engine, state, _backend = setup(
        registry, make_world, [plan], villagers=[ada], triggers=("idle",)
    )
    tick(controller, state)
    mind = mind_of(controller)
    mind.records["ada"].progress.count = 5  # stale progress the next step must not inherit
    controller.events()
    rejected = Event(state.tick, 0, "intent_rejected", {"actor": "ada", "reason": "too_tired"})
    tick(controller, state, [rejected])
    assert "plan_step" not in kinds(controller.events())
    assert mind.records["ada"].rejected == "intent_rejected: too_tired"
    controller.memory["ada"].idle_until = 0
    due = state.tick
    tick(controller, state)
    failed = [d for k, d in controller.events() if k == "plan_step"]
    assert len(failed) == 1 and failed[0]["status"] == "failed" and failed[0]["action"] == "rest"
    assert "too_tired" in failed[0]["reason"]
    record = mind.records["ada"]
    assert record.index == 1 and record.rejected is None
    assert record.progress == begin(due, ada, Step(action="gather", target="berries"))
    assert record.progress == Progress(start=due, base=2)


@pytest.mark.req("REQ-AGT-004")
def test_craft_rejected_every_time_fails_instead_of_reissuing_forever(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: a Craft the engine rejects each time fails the step rather than looping."""
    plan = json.dumps(
        {"goal": "g", "steps": [{"action": "craft", "target": "saw_planks"}], "reason": "r"}
    )
    ada = Villager("ada", "Ada", Coord(2, 2), model="m", inventory=Inventory({"wood": 3}))
    controller, _engine, state, _backend = setup(
        registry, make_world, [plan, REST], villagers=[ada], triggers=("idle",)
    )
    camp = Building("b1", "lumber_camp", Coord(3, 2), Ownership("communal"), complete=True)
    state.buildings["b1"] = camp
    crafts = 0
    steps: list[dict] = []  # type: ignore[type-arg]
    for _ in range(10):
        intents = controller.intents(state)
        state.tick += 1
        crafted = [i for i in intents if isinstance(i, Craft)]
        crafts += len(crafted)
        rejected = Event(state.tick, 0, "intent_rejected", {"actor": "ada", "reason": "busy"})
        controller.observe(state, [rejected] if crafted else [])
        steps += [d for k, d in controller.events() if k == "plan_step" and d["action"] == "craft"]
        controller.memory["ada"].idle_until = 0
    assert crafts == 1
    assert [d["status"] for d in steps] == ["failed"] and "busy" in steps[0]["reason"]


@pytest.mark.req("REQ-AGT-005")
def test_invalid_output_is_retried_with_the_error(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1/AC3: an invalid answer is retried with the validation error; both are logged."""
    controller, engine, state, backend = setup(registry, make_world, ["not json", BERRIES])
    state, notes = step(controller, engine, state)
    assert len(backend.calls) == 2
    retry = backend.calls[1].messages
    assert retry[-2].role == "assistant" and retry[-2].content == "not json"
    assert retry[-1].role == "user" and "could not be used" in retry[-1].content
    invalid = dict(notes)["plan_invalid"]
    assert invalid["attempt"] == 0 and invalid["model"] == "m" and invalid["error"]
    assert invalid == {"model": "m", "actor": "ada", "attempt": 0, "error": invalid["error"]}
    assert invalid["error"] in retry[-1].content
    assert dict(notes)["plan_made"]["retries"] == 1


@pytest.mark.req("REQ-AGT-005")
def test_invalid_action_target_counts_as_invalid(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a target outside the catalog is invalid output, retried with the error."""
    bad = json.dumps(
        {"goal": "g", "steps": [{"action": "build", "target": "castle"}], "reason": "r"}
    )
    controller, engine, state, _backend = setup(registry, make_world, [bad, BERRIES])
    state, notes = step(controller, engine, state)
    assert "'castle' is not a valid target for build" in dict(notes)["plan_invalid"]["error"]


@pytest.mark.req("REQ-AGT-005")
def test_after_retries_the_scripted_mind_takes_over(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2/AC3: after max_retries the fallback decides; it is logged with model and reason."""
    controller, _engine, state, backend = setup(registry, make_world, ["x", "y", "z", REST])
    scripted = ScriptedMind().decide(controller.view(state), state.villagers["ada"])
    intents = controller.intents(state)
    notes = controller.events()
    assert len(backend.calls) == 3  # first try + max_retries (2)
    fallback = dict(notes)["mind_fallback"]
    assert fallback["model"] == "m" and fallback["flagged"] is False
    assert fallback["reason"].startswith("invalid output after 3 attempts")
    assert [k for k, _ in notes].count("plan_invalid") == 3
    assert scripted is not None and intents == [scripted.intent]


@pytest.mark.req("REQ-AGT-005")
def test_no_calls_during_the_fallback_window(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: the scripted mind drives the villager for fallback_hours; then it plans again."""
    controller, engine, state, backend = setup(
        registry, make_world, ["x", "y", "z", REST], fallback_hours=1.0
    )
    per_hour = 60 // default_config().calendar.tick_minutes
    for _ in range(per_hour - 1):
        state, _ = step(controller, engine, state)
    assert len(backend.calls) == 3
    for _ in range(40):
        state, _ = step(controller, engine, state)
    assert len(backend.calls) == 4


@pytest.mark.req("REQ-AGT-005")
def test_plan_that_cannot_start_falls_back_instead_of_asking_every_tick(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2 (Review Focus 1): a valid plan whose steps all fail at once falls back for a window."""
    controller, engine, state, backend = setup(registry, make_world, [IRON], triggers=("idle",))
    fallbacks: list[str] = []
    for _ in range(10):
        state, notes = step(controller, engine, state)
        fallbacks += [d["reason"] for k, d in notes if k == "mind_fallback"]
        flags = [(d["actor"], d["flagged"]) for k, d in notes if k == "mind_fallback"]
        assert flags in ([], [("ada", False)])
    assert len(backend.calls) == 1
    assert fallbacks == ["the plan gave nothing to do"]
    record = mind_of(controller).records["ada"]
    assert record.plan is None and record.progress == Progress()
    assert Record.from_dict(record.to_dict()) == record


@pytest.mark.req("REQ-LLM-009")
def test_live_mode_backend_error_falls_back_and_is_flagged(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: in live mode the villager uses fallback behaviour, and the event is flagged."""
    controller, engine, state, _backend = setup(
        registry, make_world, [FakeError("down")], mode="live"
    )
    state, notes = step(controller, engine, state)
    fallback = dict(notes)["mind_fallback"]
    assert fallback["flagged"] is True and "down" in fallback["reason"]


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_backend_failure_stops_the_tick(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: in wait mode the gateway's BackendUnavailable propagates; no plan is adopted."""
    controller, _engine, state, _backend = setup(
        registry, make_world, [FakeError("down")], mode="wait"
    )
    with pytest.raises(BackendUnavailable):
        controller.intents(state)
    assert controller.events() == []


def test_records_of_dead_villagers_are_dropped(registry: Registry, make_world: MakeWorld) -> None:
    """Review Focus 3: a villager that dies leaves no record behind."""
    people = [
        Villager("ada", "Ada", Coord(2, 2), model="m"),
        Villager("bo", "Bo", Coord(3, 3), model="m"),
    ]
    controller, engine, state, _backend = setup(registry, make_world, [REST], villagers=people)
    state, notes = step(controller, engine, state)
    assert [d["actor"] for k, d in notes if k == "plan_made"] == ["ada", "bo"]
    del state.villagers["bo"]
    controller.memory["ada"].idle_until = 0
    state, _ = step(controller, engine, state)
    assert set(controller.to_dict()["minds"]["m"]["records"]) == {"ada"}


def test_record_round_trips_through_its_dict() -> None:
    """ADR-0018 §7: every saved field survives to_dict/from_dict."""
    mind = plan_minds(["m"], lambda rs: [], AgentConfig(), seed=1)["m"]
    plan = mind.parse({"records": {}})
    assert plan == {}
    record = Record(
        plan=Plan(goal="g", steps=(Step(action="rest", qty=2),), reason="r"),
        index=1,
        progress=Progress(start=4, base=1, issued=True, count=2, site="b1", origin=(3, 4)),
        planned_tick=3,
        pending=["step_failed", "idle"],
        failure="no food",
        above=["eat"],
        fallback_until=9,
        rejected="intent_rejected: busy",
    )
    assert json.loads(json.dumps(record.to_dict())) == record.to_dict()  # JSON-shaped
    assert Record.from_dict(record.to_dict()) == record
    assert Record.from_dict(Record().to_dict()) == Record()


def test_snapshot_round_trip_continues_identically(
    registry: Registry, make_world: MakeWorld
) -> None:
    """ADR-0018 §7: a restored mind continues the same step without asking again."""
    controller, engine, state, _backend = setup(registry, make_world, [SNAP], triggers=("idle",))
    for _ in range(5):
        state, _ = step(controller, engine, state)
    blob = controller.to_dict()
    twin, twin_engine, _, twin_backend = setup(registry, make_world, [SNAP], triggers=("idle",))
    twin.load(blob)
    assert twin.to_dict() == blob
    saved = WorldState.from_dict(state.to_dict())
    a: list[Notes] = []
    for _ in range(40):
        state, notes = step(controller, engine, state)
        a.append(notes)
    b: list[Notes] = []
    for _ in range(40):
        saved, notes = step(twin, twin_engine, saved)
        b.append(notes)
    assert a == b and twin_backend.calls == []
    assert "plan_step" in [k for notes in a for k, _ in notes]  # the mind acted in the window


def test_events_carry_their_full_payloads(registry: Registry, make_world: MakeWorld) -> None:
    """ADR-0018 §6: plan_made and plan_step name the actor, step, target, goal and reason."""
    controller, engine, state, _backend = setup(registry, make_world, [BERRIES], triggers=("idle",))
    notes: Notes = []
    for _ in range(120):
        state, more = step(controller, engine, state)
        notes += more
        if len([k for k, _ in notes if k == "plan_step"]) >= 2:
            break
    made = next(d for k, d in notes if k == "plan_made")
    assert made == {
        "model": "m",
        "actor": "ada",
        "triggers": ["idle"],
        "goal": "food",
        "steps": [
            {"action": "gather", "target": "berries", "qty": 2},
            {"action": "eat", "target": None, "qty": None},
        ],
        "reason": "hungry",
        "retries": 0,
        "template": "plan.v1",
    }
    steps = [d for k, d in notes if k == "plan_step"]
    assert steps[:2] == [
        {
            "model": "m",
            "actor": "ada",
            "index": 0,
            "action": "gather",
            "target": "berries",
            "status": "done",
        },
        {
            "model": "m",
            "actor": "ada",
            "index": 1,
            "action": "eat",
            "target": None,
            "status": "done",
        },
    ]


@pytest.mark.req("REQ-AGT-004")
def test_steps_run_in_order_each_from_a_fresh_start(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1/AC2: failed and finished steps hand over in order; each step has its own start."""
    plan = json.dumps(
        {
            "goal": "g",
            "steps": [
                {"action": "gather", "target": "iron_ore"},
                {"action": "gather", "target": "iron_ore"},
                {"action": "rest", "qty": 1},
                {"action": "rest", "qty": 1},
                {"action": "gather", "target": "berries", "qty": 1},
            ],
            "reason": "r",
        }
    )
    controller, engine, state, _backend = setup(
        registry, make_world, [plan], triggers=("idle",), max_plan_steps=5
    )
    per_hour = 60 // default_config().calendar.tick_minutes
    seen: list[tuple[int, str, str, str | None]] = []
    starts: list[int] = []
    for _ in range(3 * per_hour):
        state, notes = step(controller, engine, state)
        for k, d in notes:
            if k == "plan_step":
                seen.append((d["index"], d["action"], d["status"], d.get("reason")))
                starts.append(mind_of(controller).records["ada"].progress.start)
        if len(seen) >= 5:
            break
        if "ada" in controller.memory:
            controller.memory["ada"].idle_until = 0
    reason = "no iron_ore source within reach"
    assert seen[:5] == [
        (0, "gather", "failed", reason),
        (1, "gather", "failed", reason),
        (2, "rest", "done", None),
        (3, "rest", "done", None),
        (4, "gather", "done", None),
    ]
    assert starts[2] - starts[1] == per_hour  # the second rest began when the first ended


@pytest.mark.req("REQ-AGT-001")
def test_periodic_fires_exactly_every_replan_hours(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: with the villager due every tick, `periodic` fires replan_hours after each plan."""
    long_rest = json.dumps(
        {"goal": "rest", "steps": [{"action": "rest", "qty": 99}], "reason": "r"}
    )
    controller, engine, state, _backend = setup(
        registry, make_world, [long_rest], triggers=("idle", "periodic"), replan_hours=0.25
    )
    every = 15 // default_config().calendar.tick_minutes
    ticks: list[int] = []
    for _ in range(2 * every + 1):
        now = state.tick
        state, notes = step(controller, engine, state)
        ticks += [now for k, _ in notes if k == "plan_made"]
        controller.memory["ada"].idle_until = 0
    assert ticks == [0, every, 2 * every]


@pytest.mark.req("REQ-AGT-001")
def test_batch_asks_in_villager_order_and_handles_each_answer(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1/REQ-AGT-005 AC2: one batch per tick in id order; one villager's fallback leaves the
    other's plan running."""
    people = [
        Villager("bo", "Bo", Coord(3, 3), model="m"),
        Villager("ada", "Ada", Coord(2, 2), model="m"),
    ]
    controller, engine, state, backend = setup(
        registry,
        make_world,
        [REST],
        villagers=people,
        rules=[FakeRule(("x",), kind="plan", villager="ada")],
        fallback_hours=2.0,
    )
    state, notes = step(controller, engine, state)
    assert [c.villager for c in backend.calls] == ["ada", "bo", "ada", "ada"]
    assert [(k, d["actor"]) for k, d in notes] == [
        ("plan_invalid", "ada"),
        ("plan_invalid", "ada"),
        ("plan_invalid", "ada"),
        ("mind_fallback", "ada"),
        ("plan_made", "bo"),
    ]
    per_hour = 60 // default_config().calendar.tick_minutes
    done: list[int] = []
    for _ in range(per_hour + 5):
        for vid in ("ada", "bo"):
            villager = state.villagers[vid]
            villager.path, villager.activity = [], None
            controller.memory[vid].idle_until = 0
        now = state.tick
        state, notes = step(controller, engine, state)
        done += [now for k, d in notes if k == "plan_step" and d["actor"] == "bo"]
    assert done[:1] == [per_hour]  # bo's rest ends on time while ada is in her fallback window


def test_requests_name_kind_villager_tick_seed_and_template(
    registry: Registry, make_world: MakeWorld
) -> None:
    """ADR-0018 §2: each request is a `plan` request for this tick, seeded from the run."""
    seen: list[Request] = []

    def complete(requests: Sequence[Request]) -> list[Result]:
        seen.extend(requests)
        value = Plan.model_validate_json(REST)
        return [Result(r, REST, value, None, None, 0, 0, 0.0, False) for r in requests]

    agents = AgentConfig()
    engine = Engine(registry, default_config())
    controller = scripted_controller(engine.context, agents, plan_minds(["m"], complete, agents, 7))
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(2, 2), model="m")])
    state.tick = 5
    controller.intents(state)
    (request,) = seen
    assert (request.kind, request.villager, request.tick, request.model) == ("plan", "ada", 5, "m")
    assert (request.seed, request.output, request.attempt) == (seed_for(7, "ada", 5), Plan, 0)
    assert request.template == "plan.v1"


def test_decide_without_a_record_uses_the_fallback(
    registry: Registry, make_world: MakeWorld
) -> None:
    """A villager the mind never prepared is decided by the scripted fallback."""
    controller, _engine, state, _backend = setup(registry, make_world, [REST])
    ada = state.villagers["ada"]
    view = controller.view(state)
    assert mind_of(controller).decide(view, ada) == ScriptedMind().decide(view, ada)


def test_observe_keeps_only_failures_of_villagers_with_a_plan(
    registry: Registry, make_world: MakeWorld
) -> None:
    """ADR-0018 §4: only engine failures count; the first one is kept; others are ignored."""
    people = [
        Villager("ada", "Ada", Coord(2, 2), model="m"),
        Villager("bo", "Bo", Coord(3, 3), model="m"),
    ]
    controller, _engine, state, _backend = setup(
        registry, make_world, [REST], villagers=people, rules=[FakeRule(("x",), villager="bo")]
    )
    controller.intents(state)
    mind = mind_of(controller)
    assert mind.records["ada"].plan is not None and mind.records["bo"].plan is None

    def event(kind: str, **data: object) -> Event:
        return Event(state.tick, 0, kind, data)

    mind.observe(
        state,
        [
            event("work_interrupted", actor="ada", cause="villager", reason="chose"),
            event("villager_moved", actor="ada"),
            event("intent_rejected", actor="ghost", reason="gone"),
            event("intent_rejected", actor="bo", reason="no plan"),
            event("intent_rejected", actor="ada"),
            event("move_failed", actor="ada", reason="blocked"),
        ],
    )
    assert mind.records["ada"].rejected == "intent_rejected: intent_rejected"
    assert mind.records["bo"].rejected is None


@pytest.mark.req("REQ-LLM-009")
def test_live_mode_backend_errors_fall_back_for_every_villager_in_the_batch(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: each villager whose request failed in live mode falls back, flagged."""
    people = [
        Villager("ada", "Ada", Coord(2, 2), model="m"),
        Villager("bo", "Bo", Coord(3, 3), model="m"),
    ]
    controller, engine, state, _backend = setup(
        registry, make_world, [FakeError("down")], mode="live", villagers=people
    )
    state, notes = step(controller, engine, state)
    flagged = [(d["actor"], d["flagged"]) for k, d in notes if k == "mind_fallback"]
    assert flagged == [("ada", True), ("bo", True)]


@pytest.mark.req("REQ-AGT-001")
def test_steps_settled_on_the_adoption_tick_do_not_trigger_a_second_ask(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: a step that fails as the plan is adopted fires nothing more; the plan runs on."""
    plan = json.dumps(
        {
            "goal": "food",
            "steps": [
                {"action": "gather", "target": "iron_ore"},
                {"action": "gather", "target": "berries", "qty": 2},
            ],
            "reason": "r",
        }
    )
    controller, engine, state, backend = setup(registry, make_world, [plan])
    done: list[int] = []
    for _ in range(200):
        before = len(backend.calls)
        state, notes = step(controller, engine, state)
        done = [d["index"] for k, d in notes if k == "plan_step" and d["status"] == "done"]
        if done:
            break
        assert len(backend.calls) == 1
    assert done == [1] and before == 1


@pytest.mark.req("REQ-AGT-004")
def test_a_rejected_eat_fails_the_step_with_the_rejection(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: an Eat the engine rejects is a failed step, not one done because it was sent."""
    plan = json.dumps({"goal": "eat", "steps": [{"action": "eat"}], "reason": "r"})
    ada = Villager("ada", "Ada", Coord(2, 2), model="m", inventory=Inventory({"berries": 3}))
    controller, _engine, state, _backend = setup(
        registry, make_world, [plan, REST], villagers=[ada], triggers=("idle",)
    )
    tick(controller, state)
    controller.events()
    rejected = Event(state.tick, 0, "intent_rejected", {"actor": "ada", "reason": "not_hungry"})
    assert mind_of(controller).records["ada"].progress.issued is True
    controller.observe(state, [rejected])
    assert mind_of(controller).records["ada"].progress.issued is False
    controller.memory["ada"].idle_until = 0  # the controller idles untargeted failures
    tick(controller, state)
    steps = [d for k, d in controller.events() if k == "plan_step"]
    assert [(d["action"], d["status"]) for d in steps] == [("eat", "failed")]
    assert "not_hungry" in steps[0]["reason"]


def test_records_of_dead_villagers_are_dropped_when_none_is_due(
    registry: Registry, make_world: MakeWorld
) -> None:
    """Review Focus 3: observe prunes the dead, so a snapshot never carries their record."""
    people = [
        Villager("ada", "Ada", Coord(2, 2), model="m"),
        Villager("bo", "Bo", Coord(3, 3), model="m"),
    ]
    controller, engine, state, _backend = setup(registry, make_world, [REST], villagers=people)
    state, _ = step(controller, engine, state)
    assert controller.memory["ada"].idle_until > state.tick  # resting: nobody is due next tick
    del state.villagers["bo"]
    state, _ = step(controller, engine, state)
    assert set(controller.to_dict()["minds"]["m"]["records"]) == {"ada"}
