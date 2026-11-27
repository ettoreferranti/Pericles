from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.plan import (
    ACTIONS,
    Catalog,
    Plan,
    Step,
    catalog_for,
    check_plan,
    without_ignored_targets,
)
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
        "gather",
        "eat",
        "sleep",
        "rest",
        "go_home",
        "move_in",
        "court",
        "store",
        "take",
        "build",
        "craft",
        "research",
    )


@pytest.mark.req("REQ-AGT-003")
def test_plan_parses_and_its_schema_lists_the_actions() -> None:
    """AC1: a plan is {goal, steps:[{action, target, qty}], reason}, schema-validated."""
    text = (
        '{"goal": "eat", "steps": [{"action": "gather", "target": "berries", "qty": 4}],'
        ' "reason": "hungry"}'
    )
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
    assert check_plan(plan(Step(action="sleep", target="bed")), catalog, 6) is None
    assert check_plan(plan(Step(action="build", target="house")), catalog, 6) == (
        "steps[0].target: 'house' is not a valid target for build; valid: none right now"
    )
    too_long = plan(*[Step(action="sleep")] * 3)
    assert check_plan(too_long, catalog, 2) == "steps: at most 2 steps, got 3"


def test_catalog_lines_skip_actions_without_targets_and_never_list_store_items() -> None:
    catalog = Catalog({a: () for a in ACTIONS} | {"gather": ("wood",), "store": ("wood", "x")})
    lines = catalog.lines()
    assert any(
        line.startswith("- gather <item> [qty]") and line.endswith("targets: wood")
        for line in lines
    )
    assert not any(line.startswith("- build") for line in lines)
    assert any(line.startswith("- sleep") for line in lines)
    store = next(line for line in lines if line.startswith("- store"))
    assert "targets" not in store


@pytest.mark.req("REQ-AGT-003")
def test_gather_targets_are_content_level_not_perception_limited(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: gather lists items an action can produce for this villager, wherever nodes are."""
    ada = Villager("ada", "Ada", Coord(1, 1), sex="female")
    kid = Villager("kid", "Kid", Coord(2, 1), sex="male", adult=False)
    state = make_world(ROWS, [ada, kid])  # no nodes at all
    view = view_of(registry, state)
    adult_targets = catalog_for(view, ada).targets["gather"]
    assert "wood" in adult_targets and "berries" in adult_targets
    # A child may only do actions with a child-allowed tag, so the labour items drop out.
    child_targets = catalog_for(view, kid).targets["gather"]
    assert "berries" in child_targets
    assert "wood" not in child_targets and "stone" not in child_targets
    # Building-located actions (farming) are not gathering from the land.
    assert "grain" not in adult_targets


@pytest.mark.req("REQ-AGT-003")
def test_store_and_eat_accept_items_nobody_holds(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: store and eat targets are content-level, so plans can chain gather, store, eat."""
    ada = Villager("ada", "Ada", Coord(1, 1), sex="female", needs={"hunger": 50.0})
    state = make_world(ROWS, [ada])
    catalog = catalog_for(view_of(registry, state), ada)
    assert ada.inventory.count("wood") == 0 and ada.inventory.count("meat") == 0
    plan = Plan(
        goal="g",
        steps=(
            Step(action="gather", target="berries"),
            Step(action="store", target="wood"),
            Step(action="eat", target="meat"),
        ),
        reason="r",
    )
    assert check_plan(plan, catalog, 6) is None


def test_gather_usage_does_not_claim_proximity() -> None:
    catalog = Catalog({a: () for a in ACTIONS} | {"gather": ("wood",)})
    gather = next(line for line in catalog.lines() if line.startswith("- gather"))
    assert "nearby" not in gather


@pytest.mark.req("REQ-AGT-003")
def test_targets_on_actions_that_take_none_are_ignored_and_dropped() -> None:
    """AC2: `sleep house b0` means sleep; the plan is valid and the stray target is dropped
    (a live run lost 129 plans and their retries to this)."""
    stray = Plan(
        goal="g",
        steps=(
            Step(action="sleep", target="house b0"),
            Step(action="go_home", target="home"),
            Step(action="rest", target="here", qty=2),
            Step(action="move_in", target="b1"),
            Step(action="gather", target="wood", qty=3),
        ),
        reason="r",
    )
    catalog = Catalog({a: () for a in ACTIONS} | {"gather": ("wood",)})
    assert check_plan(stray, catalog, 6) is None
    clean = without_ignored_targets(stray)
    assert [s.target for s in clean.steps] == [None, None, None, None, "wood"]
    assert [s.qty for s in clean.steps] == [None, None, 2, None, 3]
    assert (clean.goal, clean.reason) == ("g", "r")


@pytest.mark.req("REQ-AGT-003")
def test_eat_is_not_offered_below_the_eating_level(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC2: below `act_at["eat"]` the catalog leaves `eat` out and a plan naming it is invalid,
    with the reason (a live run failed 200 eat steps as "not hungry")."""
    full = Villager("ada", "Ada", Coord(1, 1), sex="female", needs={"hunger": 49.0})
    hungry = Villager("bob", "Bob", Coord(2, 1), sex="male", needs={"hunger": 50.0})
    state = make_world(ROWS, [full, hungry])
    view = view_of(registry, state)
    eat = Plan(goal="g", steps=(Step(action="rest"), Step(action="eat")), reason="r")
    not_hungry = catalog_for(view, full)
    assert not any(line.startswith("- eat") for line in not_hungry.lines())
    assert check_plan(eat, not_hungry, 6) == (
        "steps[1].action: eat is not possible now: you are not hungry enough "
        "(eating works from 50, you are at 49)"
    )
    can_eat = catalog_for(view, hungry)
    assert any(line.startswith("- eat") for line in can_eat.lines())
    assert check_plan(eat, can_eat, 6) is None
