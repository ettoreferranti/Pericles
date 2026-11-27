from collections.abc import Callable

import pytest

from pericles.agents.config import AgentConfig
from pericles.agents.plan import Plan, Step, catalog_for
from pericles.agents.prompt import (
    ALWAYS,
    PROMPTS,
    Section,
    Situation,
    TemplateError,
    estimate_tokens,
    fit,
    load_template,
    plan_messages,
    render,
    template_paths,
)
from pericles.agents.view import NodeIndex, View
from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.nodes import Node
from pericles.core.state import Proposal, Villager, WorldState
from pericles.experiment.defaults import default_agent_config, default_config

MakeWorld = Callable[..., WorldState]
ROWS = ["." * 40] * 40
IDLE = Situation(("idle",), None, 0, None)


def view_of(registry: Registry, state: WorldState, **config: object) -> View:
    agents = AgentConfig(**config)  # type: ignore[arg-type]
    ctx = Context.build(registry, default_config())
    return View(ctx, state, agents, NodeIndex(state.nodes.values(), agents.index_cell), {})


def prompt(
    registry: Registry,
    state: WorldState,
    vid: str = "ada",
    situation: Situation = IDLE,
    **config: object,
) -> str:
    view = view_of(registry, state, **config)
    villager = state.villagers[vid]
    system, user = plan_messages(
        view, villager, situation, catalog_for(view, villager), load_template("plan.v1")
    )
    return system.content + "\n" + user.content


def village(make_world: MakeWorld) -> WorldState:
    ada = Villager(
        "ada",
        "Ada",
        Coord(5, 5),
        sex="female",
        traits=("greedy",),
        needs={"hunger": 90.0},
        inventory=Inventory({"wood": 3}),
    )
    near = Villager("bram", "Bram", Coord(8, 5), sex="male")
    far = Villager("zed", "Zed", Coord(35, 35), sex="male")
    state = make_world(
        ROWS,
        [ada, near, far],
        nodes=[Node("n0", "berry_bush", Coord(6, 6), 5), Node("n9", "tree", Coord(36, 36), 5)],
    )
    state.buildings["h1"] = Building(
        "h1", "house", Coord(9, 9), Ownership("communal"), complete=True
    )
    state.buildings["h9"] = Building(
        "h9", "house", Coord(30, 30), Ownership("communal"), complete=True
    )
    return state


def test_template_files_exist_and_load() -> None:
    template = load_template("plan.v1")
    assert template.version == "plan.v1"
    assert [p.name for p in template_paths("plan.v1")] == [
        "plan.v1.system.txt",
        "plan.v1.user.txt",
        "plan.v1.retry.txt",
    ]
    with pytest.raises(TemplateError, match=r"plan\.v9"):
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
def test_prompts_neither_order_obedience_nor_invite_breaking(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1: a rendered prompt contains none of the steering phrases either."""
    text = prompt(registry, village(make_world)).lower()
    assert [p for p in default_agent_config().steering_phrases if p in text] == []


@pytest.mark.req("REQ-AGT-009")
def test_traits_with_their_descriptions_are_in_the_prompt(
    registry: Registry, make_world: MakeWorld
) -> None:
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
    store.storage.add(registry, "berries", 12)
    state.buildings["s1"] = store
    assert "- berries: 12" in prompt(registry, state)


@pytest.mark.req("REQ-AGT-002")
def test_prompt_shows_needs_plan_failure_and_triggers(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC1 (the sections that exist in M2b): needs, current plan, last failure, why now."""
    plan = Plan(
        goal="food",
        steps=(Step(action="gather", target="berries"), Step(action="eat")),
        reason="hungry",
    )
    text = prompt(
        registry,
        village(make_world),
        situation=Situation(("step_failed",), plan, 1, "no berries source within reach"),
    )
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
    trimmed = fit(
        parts,
        budget_tokens=estimate_tokens("## You\n" + "a" * 40 + "\n\n## Nearby\nn1\nn2", 1.0) + 1,
        chars_per_token=1.0,
        fixed_chars=0,
    )
    assert [s.title for s in trimmed] == ["You", "Nearby"]
    assert trimmed[1].lines == ("n1", "n2")


@pytest.mark.req("REQ-AGT-002")
def test_crowded_village_is_trimmed_to_budget_farthest_first(
    registry: Registry, make_world: MakeWorld
) -> None:
    """AC3 (Review Focus 4): over the budget, recipes go first, then the farthest nearby lines;
    identity, needs, plan and actions stay."""
    crowd = [
        Villager(f"v{i:02d}", f"V{i:02d}", Coord(5 + i % 10, 6 + i // 10), sex="male")
        for i in range(30)
    ]
    state = make_world(ROWS, [Villager("ada", "Ada", Coord(5, 5), sex="female"), *crowd])
    full = prompt(registry, state, prompt_budget_tokens=100_000)
    small = prompt(registry, state, prompt_budget_tokens=700)
    assert estimate_tokens(small, 4.0) <= 700 < estimate_tokens(full, 4.0)
    assert "## Recipes and costs" in full and "## Recipes and costs" not in small
    assert "V00 (v00)" in small and "V29 (v29)" not in small  # v29 is the farthest
    for kept in ("## You", "## Needs", "## Your plan", "## Actions you can use"):
        assert kept in small


def test_fit_keeps_everything_at_exactly_the_budget() -> None:
    parts = [Section("You", ("abc",), ALWAYS), Section("Nearby", ("n1", "n2"), 2)]
    exact = estimate_tokens(render(parts), 1.0)
    assert fit(parts, budget_tokens=exact, chars_per_token=1.0, fixed_chars=0) == parts
    assert fit(parts, budget_tokens=exact - 1, chars_per_token=1.0, fixed_chars=0) != parts


@pytest.mark.req("REQ-AGT-002")
def test_family_is_perceived_only_when_known(registry: Registry, make_world: MakeWorld) -> None:
    """AC2: a relative's state is shown when in sight or sharing a home; else 'not in sight'."""
    state = village(make_world)
    ada = state.villagers["ada"]
    ada.home, ada.partner, ada.parents = "h1", "bram", ("mom",)
    state.villagers["bram"].partner = "ada"
    state.villagers["bram"].needs = {"hunger": 90.0}
    kid = Villager("kid", "Kid", Coord(35, 5), sex="male", parents=("ada",), home="h1")
    kid.needs = {"hunger": 10.0}
    mom = Villager("mom", "Mom", Coord(5, 35), sex="female", needs={"hunger": 99.0})
    cara = Villager("cara", "Cara", Coord(6, 5), sex="female")
    for other in (kid, mom, cara):
        state.villagers[other.id] = other
    state.proposals["cara"] = Proposal("ada", state.tick + 5)
    state.proposals["zed"] = Proposal("ada", state.tick)  # lapsed
    state.proposals["bram"] = Proposal("cara", state.tick + 5)  # not to Ada
    text = prompt(registry, state)
    assert "- partner Bram (bram): needs eat urgently" in text
    assert "- child Kid (kid): fine" in text
    assert "- parent Mom (mom): not in sight\n" in text
    assert "Cara (cara) has asked you to be partners" in text
    assert "Zed (zed) has asked" not in text
    assert "Bram (bram) has asked" not in text
