from collections.abc import Callable

import pytest

from pericles.agents.executor import Outcome, Progress, workplace
from pericles.agents.plan import Step
from pericles.agents.view import Memory, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.intents import Construct, Craft, Deliver, MoveTo, PlaceBuilding, Research
from pericles.core.inventory import Inventory
from pericles.core.state import Activity, Villager, WorldState

MakeWorld = Callable[..., WorldState]
Runner = Callable[..., tuple[Outcome, Progress]]
ViewOf = Callable[..., View]


@pytest.mark.req("REQ-AGT-004")
def test_build_places_a_communal_site_then_delivers_then_constructs(
    registry: Registry, make_world: MakeWorld, run: Runner, rows: list[str]
) -> None:
    """AC1: build places, delivers and constructs through engine intents."""
    ada = Villager("ada", "Ada", Coord(8, 8), inventory=Inventory({"wood": 10, "stone": 4}))
    state = make_world(rows, [ada])
    step = Step(action="build", target="house")
    out, progress = run(state, "ada", step)
    intent = out.decision.intent  # type: ignore[union-attr]
    assert isinstance(intent, (MoveTo, PlaceBuilding))
    if isinstance(intent, MoveTo):  # walk there first, then place
        ada.pos = intent.target
        out, _ = run(state, "ada", step, progress)
        intent = out.decision.intent  # type: ignore[union-attr]
    assert isinstance(intent, PlaceBuilding) and intent.ownership == "communal"
    assert progress.origin == (intent.origin.x, intent.origin.y)
    state.buildings["b1"] = Building("b1", "house", intent.origin, Ownership("communal"))
    out, _ = run(state, "ada", step, progress)
    assert progress.site == "b1"
    assert isinstance(out.decision.intent, (MoveTo, Deliver))  # type: ignore[union-attr]


@pytest.mark.req("REQ-AGT-004")
def test_build_fails_listing_missing_materials(
    registry: Registry, make_world: MakeWorld, run: Runner, rows: list[str]
) -> None:
    """AC2: a site that needs materials the villager lacks fails the step with what it needs."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(rows, [ada])
    state.buildings["b1"] = Building("b1", "house", Coord(3, 2), Ownership("communal"))
    out, _ = run(state, "ada", Step(action="build", target="house"))
    assert out.failed == "the house still needs 4 stone, 10 wood"


@pytest.mark.req("REQ-AGT-004")
def test_build_with_materials_delivered_constructs_and_completes(
    registry: Registry, make_world: MakeWorld, run: Runner, rows: list[str]
) -> None:
    """AC1: a fully supplied site is constructed; the step is done once it is complete."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(rows, [ada])
    site = Building(
        "b1", "house", Coord(3, 2), Ownership("communal"), delivered={"wood": 10, "stone": 4}
    )
    state.buildings["b1"] = site
    step = Step(action="build", target="house")
    out, progress = run(state, "ada", step)
    assert isinstance(out.decision.intent, (MoveTo, Construct))  # type: ignore[union-attr]
    site.complete = True
    assert run(state, "ada", step, progress)[0].done


@pytest.mark.req("REQ-AGT-004")
def test_build_site_gone_fails(
    registry: Registry, make_world: MakeWorld, run: Runner, rows: list[str]
) -> None:
    """AC2: a site removed mid-step fails with a reason."""
    state = make_world(rows, [Villager("ada", "Ada", Coord(2, 2))])
    progress = Progress(site="b9")
    out, _ = run(state, "ada", Step(action="build", target="house"), progress)
    assert out.failed == "the house site is gone"


@pytest.mark.req("REQ-AGT-004")
def test_craft_counts_completions_and_carries_on_while_working(
    registry: Registry, make_world: MakeWorld, run: Runner, rows: list[str]
) -> None:
    """AC1: craft sends Craft at the workplace; done after qty completions."""
    ada = Villager("ada", "Ada", Coord(2, 2), inventory=Inventory({"wood": 2}))
    state = make_world(rows, [ada])
    step = Step(action="craft", target="saw_planks", qty=2)
    assert run(state, "ada", step)[0].failed == "no lumber_camp to work at"
    state.buildings["l1"] = Building(
        "l1", "lumber_camp", Coord(3, 2), Ownership("communal"), complete=True
    )
    out, progress = run(state, "ada", step)
    assert out.decision is not None and isinstance(out.decision.intent, (MoveTo, Craft))
    if isinstance(out.decision.intent, MoveTo):
        ada.pos = out.decision.intent.target
        out, _ = run(state, "ada", step, progress)
    assert out.decision is not None and out.decision.intent == Craft("ada", "saw_planks", "l1")
    ada.activity = Activity("recipe", "saw_planks", "l1", 30.0, 0.0, 1.0)
    assert run(state, "ada", step, progress)[0] == Outcome()
    ada.activity = None
    ada.inventory.add(registry, "plank", 2)
    out, _ = run(state, "ada", step, progress)
    assert progress.count == 1 and out.decision is not None
    ada.inventory.remove("wood", 2)
    progress.issued, progress.count = False, 2
    assert run(state, "ada", step, progress)[0].done


@pytest.mark.req("REQ-AGT-004")
def test_craft_without_inputs_fails(
    registry: Registry, make_world: MakeWorld, run: Runner, rows: list[str]
) -> None:
    """AC2: missing inputs fail the step, naming what is missing."""
    state = make_world(rows, [Villager("ada", "Ada", Coord(2, 2))])
    out, _ = run(state, "ada", Step(action="craft", target="smelt_iron"))
    assert out.failed == "smelt_iron needs 2 iron_ore, 1 wood"


@pytest.mark.req("REQ-AGT-004")
def test_research_done_when_known(
    registry: Registry, make_world: MakeWorld, run: Runner, rows: list[str]
) -> None:
    """AC1/AC2: research is done once known; without its cost it fails."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(rows, [ada])
    step = Step(action="research", target="metallurgy")
    assert run(state, "ada", step)[0].failed == "metallurgy needs 2 iron_ore"
    ada.knowledge.add("metallurgy")
    assert run(state, "ada", step)[0].done


def test_workplace_is_the_nearest_complete_building_of_its_kind(
    registry: Registry, make_world: MakeWorld, view_of: ViewOf, rows: list[str]
) -> None:
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(rows, [ada])
    owner = Ownership("communal")
    state.buildings["s2"] = Building("s2", "smithy", Coord(10, 10), owner, complete=True)
    state.buildings["s1"] = Building("s1", "smithy", Coord(4, 2), owner, complete=True)
    state.buildings["s0"] = Building("s0", "smithy", Coord(3, 2), owner)
    view = view_of(state)
    assert workplace(view, ada, "smithy").id == "s1"  # type: ignore[union-attr]
    assert workplace(view, ada, "mint") is None


@pytest.mark.req("REQ-AGT-004")
def test_craft_not_counted_when_nothing_was_produced(
    registry: Registry, make_world: MakeWorld, rows: list[str], run: Runner
) -> None:
    """AC1: a rejected or interrupted craft is not a completion; the Craft is re-issued."""
    ada = Villager("ada", "Ada", Coord(2, 2), inventory=Inventory({"wood": 2}))
    state = make_world(rows, [ada])
    owner = Ownership("communal")
    state.buildings["l1"] = Building("l1", "lumber_camp", Coord(3, 2), owner, complete=True)
    step = Step(action="craft", target="saw_planks", qty=1)
    out, progress = run(state, "ada", step)
    assert out.decision is not None and out.decision.intent == Craft("ada", "saw_planks", "l1")
    out, _ = run(state, "ada", step, progress)  # free again, no plank gained
    assert progress.count == 0
    assert out.decision is not None and out.decision.intent == Craft("ada", "saw_planks", "l1")


@pytest.mark.req("REQ-AGT-004")
def test_research_sends_research_at_the_workplace_and_carries_on(
    registry: Registry, make_world: MakeWorld, rows: list[str], run: Runner
) -> None:
    """AC1: research sends Research at the school, then carries on while busy."""
    ada = Villager("ada", "Ada", Coord(2, 2), inventory=Inventory({"iron_ore": 2}))
    state = make_world(rows, [ada])
    state.buildings["sc1"] = Building(
        "sc1", "school", Coord(3, 2), Ownership("communal"), complete=True
    )
    step = Step(action="research", target="metallurgy")
    out, progress = run(state, "ada", step)
    assert out.decision is not None
    assert out.decision.intent == Research("ada", "metallurgy", "sc1")
    ada.activity = Activity("research", "metallurgy", "sc1", 600.0, 0.0, 1.0)
    assert run(state, "ada", step, progress)[0] == Outcome()


@pytest.mark.req("REQ-AGT-004")
def test_build_fails_when_the_placed_site_never_appears(
    registry: Registry, make_world: MakeWorld, rows: list[str], run: Runner
) -> None:
    """AC2: a placement that left no site at its origin fails the step."""
    state = make_world(rows, [Villager("ada", "Ada", Coord(2, 2))])
    progress = Progress(origin=(5, 5))
    out, _ = run(state, "ada", Step(action="build", target="house"), progress)
    assert out.failed == "could not place a house"


@pytest.mark.req("REQ-AGT-004")
def test_build_fails_when_there_is_no_free_place(
    registry: Registry, make_world: MakeWorld, run: Runner
) -> None:
    """AC2: with no clear ground the step fails with a reason."""
    state = make_world(["~~~~"] * 4, [Villager("ada", "Ada", Coord(1, 1))])
    out, _ = run(state, "ada", Step(action="build", target="house"))
    assert out.failed == "no free place for a house"


@pytest.mark.req("REQ-AGT-004")
def test_build_joins_a_site_it_does_not_avoid(
    registry: Registry, make_world: MakeWorld, rows: list[str], run: Runner
) -> None:
    """AC1: an existing site the villager avoids is skipped for another of the same kind."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(rows, [ada])
    owner = Ownership("communal")
    state.buildings["b1"] = Building("b1", "house", Coord(3, 2), owner)
    state.buildings["b2"] = Building("b2", "house", Coord(8, 8), owner)
    memory = {"ada": Memory(avoid={"b1": state.tick + 50})}
    _, progress = run(state, "ada", Step(action="build", target="house"), memory=memory)
    assert progress.site == "b2"


@pytest.mark.req("REQ-AGT-004")
def test_build_delivers_what_is_carried_up_to_what_is_needed(
    registry: Registry, make_world: MakeWorld, rows: list[str], run: Runner
) -> None:
    """AC1: Deliver carries the exact quantity: the smaller of held and still needed."""
    ada = Villager("ada", "Ada", Coord(2, 2), inventory=Inventory({"wood": 3}))
    state = make_world(rows, [ada])
    state.buildings["b1"] = Building("b1", "house", Coord(3, 2), Ownership("communal"))
    step = Step(action="build", target="house")
    out, _ = run(state, "ada", step)
    assert out.decision is not None and out.decision.intent == Deliver("ada", "b1", "wood", 3)
    ada.inventory.add(registry, "wood", 12)
    out, _ = run(state, "ada", step)
    assert out.decision is not None and out.decision.intent == Deliver("ada", "b1", "wood", 10)
