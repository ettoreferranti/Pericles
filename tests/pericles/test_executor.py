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
    AcceptCouple,
    Deposit,
    Eat,
    MoveTo,
    ProposeCouple,
    SetHome,
    Sleep,
    StartAction,
    Take,
    Wait,
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


def run(
    registry: Registry, state: WorldState, vid: str, step: Step, p: Progress | None = None
) -> tuple[Outcome, Progress]:
    villager = state.villagers[vid]
    progress = p if p is not None else begin(state.tick, villager, step)
    return advance(view_of(registry, state), villager, step, progress), progress


def store(bid: str, at: Coord, items: dict[str, int] | None = None) -> Building:
    return Building(
        bid,
        "storehouse",
        at,
        Ownership("communal"),
        complete=True,
        storage=Inventory(dict(items or {})),
    )


@pytest.mark.req("REQ-AGT-004")
def test_gather_walks_to_the_node_then_starts_the_action(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a plan step becomes engine intents (pathfind, act) without LLM calls."""
    ada = Villager("ada", "Ada", Coord(1, 1))
    state = make_world(ROWS, [ada], nodes=[Node("n0", "berry_bush", Coord(6, 1), 10)])
    out, _ = run(registry, state, "ada", Step(action="gather", target="berries", qty=3))
    assert isinstance(out.decision.intent, MoveTo)  # type: ignore[union-attr]
    ada.pos = Coord(5, 1)
    out, _ = run(registry, state, "ada", Step(action="gather", target="berries", qty=3))
    assert out.decision is not None and out.decision.intent == StartAction(
        "ada", "gather_berries", "n0"
    )


@pytest.mark.req("REQ-AGT-004")
def test_gather_is_done_once_qty_more_are_held(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: the step ends when its goal holds."""
    ada = Villager("ada", "Ada", Coord(1, 1), inventory=Inventory({"berries": 1}))
    state = make_world(ROWS, [ada], nodes=[Node("n0", "berry_bush", Coord(2, 1), 10)])
    step = Step(action="gather", target="berries", qty=3)
    progress = begin(0, ada, step)
    assert progress.base == 1
    ada.inventory.add(registry, "berries", 3)
    out, _ = run(registry, state, "ada", step, progress)
    assert out.done


@pytest.mark.req("REQ-AGT-004")
def test_gather_with_no_source_fails_with_a_reason(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: a step that becomes impossible fails with a reason."""
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(1, 1))])
    out, _ = run(registry, state, "ada", Step(action="gather", target="berries"))
    assert out.failed == "no berries source within reach"
    out, _ = run(registry, state, "ada", Step(action="gather", target="plank"))
    assert out.failed == "no way to gather plank now"


@pytest.mark.req("REQ-AGT-004")
def test_eat_carried_food_then_done(registry: Registry, make_world: MakeWorld) -> None:
    """AC1: eat sends one Eat intent; the step is done afterwards."""
    ada = Villager(
        "ada", "Ada", Coord(1, 1), inventory=Inventory({"berries": 5}), needs={"hunger": 60.0}
    )
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
    assert (
        run(registry, state, "ada", Step(action="eat", target="fish"))[0].failed == "no fish to eat"
    )
    state.buildings["s1"] = store("s1", Coord(2, 2), {"berries": 10})
    out, _ = run(registry, state, "ada", Step(action="eat"))
    assert out.decision is not None and isinstance(out.decision.intent, (MoveTo, Take))


@pytest.mark.req("REQ-AGT-004")
def test_sleep_sleeps_then_carries_on_then_is_done(
    registry: Registry, make_world: MakeWorld
) -> None:
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
    assert (
        run(registry, state, "ada", Step(action="move_in"))[0].failed == "no house with a free bed"
    )
    state.buildings["h1"] = Building(
        "h1", "house", Coord(6, 6), Ownership("communal"), complete=True
    )
    out, progress = run(registry, state, "ada", Step(action="move_in"))
    assert out.decision is not None and out.decision.intent == SetHome("ada", "h1")
    ada.home = "h1"
    assert run(registry, state, "ada", Step(action="move_in"), progress)[0].done
    out, _ = run(registry, state, "ada", Step(action="go_home"))
    assert out.decision is not None and isinstance(out.decision.intent, MoveTo)


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
    assert (
        run(registry, state, "ada", Step(action="store", target="wood"))[0].failed
        == "no store with room"
    )
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
