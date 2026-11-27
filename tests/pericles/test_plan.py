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
    assert any(
        line.startswith("- gather <item> [qty]") and line.endswith("targets: wood")
        for line in lines
    )
    assert not any(line.startswith("- build") for line in lines)
    assert any(line.startswith("- sleep") for line in lines)
    store = next(line for line in lines if line.startswith("- store"))
    assert "targets" not in store
