from collections.abc import Callable

import pytest
from test_executor import ROWS, run, view_of

from pericles.agents.executor import Outcome, Progress, workplace
from pericles.agents.plan import Step
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.intents import Construct, Craft, Deliver, MoveTo, PlaceBuilding
from pericles.core.inventory import Inventory
from pericles.core.state import Activity, Villager, WorldState

MakeWorld = Callable[..., WorldState]


@pytest.mark.req("REQ-AGT-004")
def test_build_places_a_communal_site_then_delivers_then_constructs(
    registry: Registry, make_world: MakeWorld
) -> None:
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
def test_build_fails_listing_missing_materials(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: a site that needs materials the villager lacks fails the step with what it needs."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(ROWS, [ada])
    state.buildings["b1"] = Building("b1", "house", Coord(3, 2), Ownership("communal"))
    out, _ = run(registry, state, "ada", Step(action="build", target="house"))
    assert out.failed == "the house still needs 4 stone, 10 wood"


@pytest.mark.req("REQ-AGT-004")
def test_build_with_materials_delivered_constructs_and_completes(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a fully supplied site is constructed; the step is done once it is complete."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(ROWS, [ada])
    site = Building(
        "b1", "house", Coord(3, 2), Ownership("communal"), delivered={"wood": 10, "stone": 4}
    )
    state.buildings["b1"] = site
    step = Step(action="build", target="house")
    out, progress = run(registry, state, "ada", step)
    assert isinstance(out.decision.intent, (MoveTo, Construct))  # type: ignore[union-attr]
    site.complete = True
    assert run(registry, state, "ada", step, progress)[0].done


@pytest.mark.req("REQ-AGT-004")
def test_build_site_gone_fails(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: a site removed mid-step fails with a reason."""
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(2, 2))])
    progress = Progress(site="b9")
    out, _ = run(registry, state, "ada", Step(action="build", target="house"), progress)
    assert out.failed == "the house site is gone"


@pytest.mark.req("REQ-AGT-004")
def test_craft_counts_completions_and_carries_on_while_working(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: craft sends Craft at the workplace; done after qty completions."""
    ada = Villager("ada", "Ada", Coord(2, 2), inventory=Inventory({"wood": 2}))
    state = make_world(ROWS, [ada])
    step = Step(action="craft", target="saw_planks", qty=2)
    assert run(registry, state, "ada", step)[0].failed == "no lumber_camp to work at"
    state.buildings["l1"] = Building(
        "l1", "lumber_camp", Coord(3, 2), Ownership("communal"), complete=True
    )
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
def test_craft_without_inputs_fails(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: missing inputs fail the step, naming what is missing."""
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(2, 2))])
    out, _ = run(registry, state, "ada", Step(action="craft", target="smelt_iron"))
    assert out.failed == "smelt_iron needs 2 iron_ore, 1 wood"


@pytest.mark.req("REQ-AGT-004")
def test_research_done_when_known(registry: Registry, make_world: MakeWorld) -> None:
    """AC1/AC2: research is done once known; without its cost it fails."""
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(ROWS, [ada])
    step = Step(action="research", target="metallurgy")
    assert run(registry, state, "ada", step)[0].failed == "metallurgy needs 2 iron_ore"
    ada.knowledge.add("metallurgy")
    assert run(registry, state, "ada", step)[0].done


def test_workplace_is_the_nearest_complete_building_of_its_kind(
    registry: Registry, make_world: MakeWorld
) -> None:
    ada = Villager("ada", "Ada", Coord(2, 2))
    state = make_world(ROWS, [ada])
    owner = Ownership("communal")
    state.buildings["s2"] = Building("s2", "smithy", Coord(10, 10), owner, complete=True)
    state.buildings["s1"] = Building("s1", "smithy", Coord(4, 2), owner, complete=True)
    state.buildings["s0"] = Building("s0", "smithy", Coord(3, 2), owner)
    view = view_of(registry, state)
    assert workplace(view, ada, "smithy").id == "s1"  # type: ignore[union-attr]
    assert workplace(view, ada, "mint") is None
