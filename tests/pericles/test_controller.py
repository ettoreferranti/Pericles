from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller, MindFailure
from pericles.agents.view import Decision, Memory, View
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Construct, MoveTo, Sleep, StartAction, Wait
from pericles.core.state import Activity, Villager, WorldState
from pericles.experiment.defaults import default_config

MakeWorld = Callable[..., WorldState]
ROWS = ["." * 8] * 8
GOAL = Coord(5, 5)


class Script:
    """A stub mind: returns `make(villager)` and records who asked."""

    def __init__(self, make: Callable[[Villager], Decision | None]) -> None:
        self.make = make
        self.asked: list[str] = []

    def decide(self, view: View, villager: Villager) -> Decision | None:
        self.asked.append(villager.id)
        return self.make(villager)


class Broken:
    def decide(self, view: View, villager: Villager) -> Decision | None:
        raise MindFailure("invalid JSON twice")


def walk(v: Villager) -> Decision:
    return Decision(MoveTo(v.id, GOAL), target="goal")


def controller(
    registry: Registry, adult: object, child: object | None = None, **kw: object
) -> Controller:
    ctx = Context.build(registry, default_config())
    return Controller(ctx, AgentConfig(), adult, child or Script(walk), **kw)  # type: ignore[arg-type]


def gathering() -> Activity:
    return Activity("action", "gather_berries", "n0", 30.0, 0.0, 1.0)


@pytest.mark.req("REQ-AGT-008")
def test_only_due_villagers_are_asked_in_id_order(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: idle villagers decide; walking or working villagers carry on."""
    state = make_world(
        ROWS,
        [
            Villager("c", "C", Coord(0, 0)),
            Villager("a", "A", Coord(0, 0)),
            Villager("b", "B", Coord(0, 0), path=[Coord(1, 0)]),
            Villager("d", "D", Coord(0, 0), activity=gathering()),
        ],
    )
    mind = Script(walk)
    intents = controller(registry, mind).intents(state)
    assert mind.asked == ["a", "c"]
    assert intents == [MoveTo("a", GOAL), MoveTo("c", GOAL)]


@pytest.mark.req("REQ-AGT-008")
def test_an_urgent_need_overrides_work(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a villager drops its work when a need reaches its urgent level."""
    urgent = AgentConfig().urgent_at["eat"]
    state = make_world(
        ROWS, [Villager("d", "D", Coord(0, 0), activity=gathering(), needs={"hunger": urgent})]
    )
    mind = Script(walk)
    assert controller(registry, mind).intents(state) == [MoveTo("d", GOAL)]


@pytest.mark.req("REQ-AGT-008")
def test_redundant_intents_are_not_sent(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: re-sending the current move, action or sleep would restart it, so it is dropped."""
    hungry = {"hunger": AgentConfig().urgent_at["eat"]}
    state = make_world(
        ROWS,
        [
            Villager("a", "A", Coord(0, 0), path=[Coord(1, 0), GOAL], needs=dict(hungry)),
            Villager("b", "B", Coord(0, 0), activity=gathering(), needs=dict(hungry)),
            Villager(
                "c",
                "C",
                Coord(0, 0),
                activity=Activity("sleep", "sleep", None, 0.0, 0.0, 0.0),
                needs=dict(hungry),
            ),
            Villager("d", "D", Coord(0, 0), activity=gathering(), needs=dict(hungry)),
        ],
    )
    answers = {
        "a": Decision(MoveTo("a", GOAL)),
        "b": Decision(StartAction("b", "gather_berries", "n0")),
        "c": Decision(Sleep("c")),
        "d": Decision(StartAction("d", "gather_berries", "n9")),
    }
    intents = controller(registry, Script(lambda v: answers[v.id])).intents(state)
    assert intents == [StartAction("d", "gather_berries", "n9")]


@pytest.mark.req("REQ-AGT-008")
def test_wait_idles_the_villager_without_an_intent(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a waiting villager is not asked again until idle_ticks pass."""
    a = Villager("a", "A", Coord(0, 0))
    state = make_world(ROWS, [a])
    mind = Script(lambda v: Decision(Wait(v.id)))
    ctl = controller(registry, mind)
    assert ctl.intents(state) == []
    assert ctl.memory["a"].idle_until == AgentConfig().idle_ticks
    state.tick = AgentConfig().idle_ticks - 1
    ctl.intents(state)
    assert mind.asked == ["a"]
    state.tick = ctl.memory["a"].idle_until
    ctl.intents(state)
    assert mind.asked == ["a", "a"]


@pytest.mark.req("REQ-SIM-016")
def test_children_never_reach_a_model_mind(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: children run on the scripted child mind; no model mind is ever consulted for them."""
    kid = Villager("k", "K", Coord(0, 0), adult=False, model="llm")
    state = make_world(ROWS, [kid])
    llm, child = Script(walk), Script(walk)
    controller(registry, Script(walk), child, minds={"llm": llm}).intents(state)
    assert llm.asked == []
    assert child.asked == ["k"]


@pytest.mark.req("REQ-AGT-008")
def test_model_minds_with_scripted_fallback(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: an adult uses its model's mind; a failing mind falls back to the scripted one."""
    state = make_world(
        ROWS,
        [
            Villager("a", "A", Coord(0, 0), model="llm"),
            Villager("b", "B", Coord(0, 0), model="broken"),
            Villager("c", "C", Coord(0, 0), model="unknown"),
            Villager("d", "D", Coord(0, 0)),
        ],
    )
    llm, scripted = Script(walk), Script(walk)
    ctl = controller(registry, scripted, minds={"llm": llm, "broken": Broken()})
    ctl.intents(state)
    assert llm.asked == ["a"]
    assert scripted.asked == ["b", "c", "d"]
    assert ctl.fallbacks == 1


@pytest.mark.req("REQ-AGT-008")
def test_failures_are_avoided_or_idled(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a rejected target is avoided for avoid_ticks; a rejection without a target idles."""
    config = AgentConfig()
    state = make_world(ROWS, [Villager("a", "A", Coord(0, 0)), Villager("b", "B", Coord(0, 0))])
    ctl = controller(
        registry,
        Script(lambda v: Decision(MoveTo(v.id, GOAL), target="n7" if v.id == "a" else None)),
    )
    ctl.intents(state)
    state.tick = 1
    ctl.observe(
        state,
        [
            Event(0, 0, "move_failed", {"actor": "a", "target": [5, 5], "reason": "no_path"}),
            Event(0, 1, "intent_rejected", {"actor": "b", "intent": "move_to", "reason": "x"}),
            Event(0, 2, "intent_rejected", {"actor": "zz", "intent": "move_to", "reason": "x"}),
        ],
    )
    assert ctl.memory["a"].avoid == {"n7": 1 + config.avoid_ticks}
    assert ctl.memory["a"].target is None
    assert ctl.memory["b"].idle_until == 1 + config.idle_ticks
    state.tick = 1 + config.avoid_ticks
    ctl.observe(state, [])
    assert ctl.memory["a"].avoid == {}


@pytest.mark.req("REQ-EXP-003")
def test_memory_round_trips_and_forgets_the_dead(registry: Registry, make_world: MakeWorld) -> None:
    """AC3: controller memory survives a snapshot; dead villagers' memory is dropped."""
    state = make_world(ROWS, [Villager("a", "A", Coord(0, 0)), Villager("b", "B", Coord(0, 0))])
    ctl = controller(registry, Script(walk))
    ctl.intents(state)
    ctl.memory["a"].avoid["n1"] = 40
    ctl.fallbacks = 2
    copy = controller(registry, Script(walk))
    copy.load(ctl.to_dict())
    assert copy.to_dict() == ctl.to_dict()
    assert copy.memory["a"] == Memory(target="goal", avoid={"n1": 40})
    copy.load({})
    assert copy.memory == {} and copy.fallbacks == 0
    del state.villagers["b"]
    ctl.intents(state)
    assert set(ctl.memory) == {"a"}


@pytest.mark.req("REQ-AGT-008")
def test_redundancy_matches_the_whole_intent(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: only an identical move, build or sleep is dropped; anything else is sent."""
    hungry = {"hunger": AgentConfig().urgent_at["eat"]}
    building = Activity("construction", "house", "h1", 30.0, 0.0, 1.0)
    state = make_world(
        ROWS,
        [
            Villager(
                "a", "A", Coord(0, 0), path=[Coord(1, 0), Coord(2, 0), GOAL], needs=dict(hungry)
            ),
            Villager(
                "b", "B", Coord(0, 0), path=[Coord(1, 0), Coord(2, 0), GOAL], needs=dict(hungry)
            ),
            Villager("c", "C", Coord(0, 0), activity=building, needs=dict(hungry)),
            Villager("d", "D", Coord(0, 0), activity=building, needs=dict(hungry)),
            Villager("e", "E", Coord(0, 0), activity=gathering(), needs=dict(hungry)),
            Villager(
                "f",
                "F",
                Coord(0, 0),
                activity=Activity("construction", "house", "h2", 30.0, 0.0, 1.0),
                needs=dict(hungry),
            ),
            Villager("g", "G", Coord(0, 0), activity=gathering(), needs=dict(hungry)),
        ],
    )
    answers = {
        "a": Decision(MoveTo("a", GOAL)),
        "b": Decision(MoveTo("b", Coord(2, 0))),
        "c": Decision(Construct("c", "h1")),
        "d": Decision(Construct("d", "h9")),
        "e": Decision(Construct("e", "h1")),
        "f": Decision(Construct("f", "h1")),
        "g": Decision(Wait("g")),
    }
    ctl = controller(registry, Script(lambda v: answers[v.id]))
    assert ctl.intents(state) == [
        MoveTo("b", Coord(2, 0)),
        Construct("d", "h9"),
        Construct("e", "h1"),
        Construct("f", "h1"),
    ]
    assert ctl.memory["g"].idle_until == AgentConfig().idle_ticks


@pytest.mark.req("REQ-AGT-008")
def test_every_mind_gets_a_real_view(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: every mind sees this controller's config and memory; the node index is cached."""
    seen: list[View] = []

    class Spy:
        def decide(self, view: View, villager: Villager) -> Decision | None:
            seen.append(view)
            return walk(villager)

    state = make_world(
        ROWS,
        [
            Villager("a", "A", Coord(0, 0), model="m"),
            Villager("b", "B", Coord(0, 0)),
            Villager("c", "C", Coord(0, 0), model="broken"),
            Villager("k", "K", Coord(0, 0), adult=False),
        ],
    )
    ctl = controller(registry, Spy(), Spy(), minds={"m": Spy(), "broken": Broken()})
    ctl.intents(state)
    assert len(seen) == 4
    for view in seen:
        assert view.config is ctl.config and view.memory is ctl.memory
        assert view.state is state and view.index.cell == ctl.config.index_cell
    first = seen[0].index
    ctl.intents(state)
    assert seen[4].index is first
    state.nodes = dict(state.nodes)
    ctl.intents(state)
    assert seen[8].index is not first


@pytest.mark.req("REQ-AGT-008")
def test_every_failure_counts_and_later_villagers_are_still_handled(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: each fallback is counted; one villager's wait or odd event does not stop the rest."""
    state = make_world(
        ROWS,
        [
            Villager("a", "A", Coord(0, 0), model="broken"),
            Villager("b", "B", Coord(0, 0), model="broken"),
        ],
    )
    ctl = controller(registry, Script(lambda v: Decision(Wait(v.id))), minds={"broken": Broken()})
    assert ctl.intents(state) == []
    assert ctl.fallbacks == 2
    assert [ctl.memory[v].idle_until for v in "ab"] == [AgentConfig().idle_ticks] * 2

    state.tick = 5
    ctl.memory["a"].avoid["n1"] = 99
    ctl.observe(
        state,
        [
            Event(0, 0, "tick", {"actor": "a"}),
            Event(0, 1, "intent_rejected", {"actor": "zz"}),
            Event(0, 2, "move_failed", {"actor": "a"}),
        ],
    )
    assert ctl.memory["a"].idle_until == state.tick + AgentConfig().idle_ticks
    assert ctl.memory["a"].avoid == {"n1": 99}


@pytest.mark.req("REQ-AGT-008")
def test_an_idle_window_beats_urgency(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: an urgent villager whose untargeted intent failed waits out its idle window."""
    config = AgentConfig()
    a = Villager("a", "A", Coord(0, 0), needs={"hunger": config.urgent_at["eat"]})
    state = make_world(ROWS, [a])
    mind = Script(lambda v: Decision(MoveTo(v.id, GOAL)))
    ctl = controller(registry, mind)
    ctl.intents(state)
    ctl.observe(state, [Event(0, 0, "intent_rejected", {"actor": "a", "reason": "x"})])
    until = ctl.memory["a"].idle_until
    assert until == state.tick + config.idle_ticks
    state.tick = until - 1
    assert ctl.intents(state) == []
    assert mind.asked == ["a"]
    state.tick = until
    ctl.intents(state)
    assert mind.asked == ["a", "a"]


@pytest.mark.req("REQ-AGT-008")
def test_no_decision_idles_the_villager(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: a mind with nothing to do is not asked again until idle_ticks pass."""
    state = make_world(ROWS, [Villager("a", "A", Coord(0, 0))])
    mind = Script(lambda v: None)
    ctl = controller(registry, mind)
    assert ctl.intents(state) == []
    assert ctl.memory["a"].idle_until == AgentConfig().idle_ticks
    state.tick = AgentConfig().idle_ticks - 1
    ctl.intents(state)
    assert mind.asked == ["a"]


@pytest.mark.req("REQ-AGT-008")
def test_one_villager_with_no_decision_does_not_stop_the_rest(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: villagers after one with nothing to do are still asked."""
    state = make_world(ROWS, [Villager("a", "A", Coord(0, 0)), Villager("b", "B", Coord(0, 0))])
    mind = Script(lambda v: None if v.id == "a" else walk(v))
    assert controller(registry, mind).intents(state) == [MoveTo("b", GOAL)]


def interrupted(actor: str, cause: str) -> Event:
    data = {"actor": actor, "work": "action", "ident": "x", "target": "n1", "cause": cause}
    return Event(0, 0, "work_interrupted", {**data, "reason": "depleted"})


@pytest.mark.req("REQ-AGT-008")
def test_work_the_engine_stops_is_a_failure(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: engine-stopped work avoids its target, or idles without one; other stops are ignored."""
    config = AgentConfig()
    state = make_world(ROWS, [Villager("a", "A", Coord(0, 0)), Villager("b", "B", Coord(0, 0))])
    ctl = controller(
        registry,
        Script(lambda v: Decision(MoveTo(v.id, GOAL), target="n7" if v.id == "a" else None)),
    )
    ctl.intents(state)
    state.tick = 3
    ctl.observe(state, [interrupted("a", "actor"), interrupted("b", "intervened")])
    assert ctl.memory["a"].avoid == {} and ctl.memory["b"].idle_until == 0
    ctl.observe(state, [interrupted("a", "engine"), interrupted("b", "engine")])
    assert ctl.memory["a"].avoid == {"n7": 3 + config.avoid_ticks}
    assert ctl.memory["b"].idle_until == 3 + config.idle_ticks


@pytest.mark.req("REQ-AGT-008")
def test_other_events_change_nothing(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: events that are not failures leave memory untouched."""
    state = make_world(ROWS, [Villager("a", "A", Coord(0, 0))])
    ctl = controller(registry, Script(walk))
    ctl.intents(state)
    before = ctl.to_dict()
    ctl.observe(state, [Event(0, 0, "stopped", {"actor": "a", "at": [0, 0]})])
    assert ctl.to_dict() == before
