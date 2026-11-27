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
    assert {i.actor for i in intents if isinstance(i, MoveTo) and i.target == Coord(5, 5)} == {
        "a",
        "b",
    }


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
