import pytest

from pericles.core.buildings import Building, Ownership
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.intents import Research, StartAction
from pericles.core.mapgen import TileMap
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import DEFAULT_CALENDAR, default_config

BUILDINGS = {
    "house",
    "storehouse",
    "farm",
    "fishing_hut",
    "lumber_camp",
    "quarry",
    "mine",
    "smithy",
    "mint",
    "town_hall",
    "palisade",
    "school",
    "mill",
    "bakery",
}


def grass_world(villagers: list[Villager]) -> WorldState:
    return WorldState.new(1, TileMap(8, 8, ["grass"] * 64, [0.0] * 64), villagers)


@pytest.mark.req("REQ-SIM-009")
def test_base_pack_has_the_v1_buildings(registry: Registry) -> None:
    """AC4: the base pack includes the fourteen v1 buildings, mill and bakery among them."""
    assert set(registry.buildings) == BUILDINGS
    assert registry.buildings["palisade"].entrance is False
    assert registry.buildings["house"].housing > 0
    assert registry.buildings["storehouse"].storage > 0
    hosts = {recipe.building for recipe in registry.recipes.values()}
    assert {"smithy", "mint", "lumber_camp", "fishing_hut"} <= hosts


@pytest.mark.req("REQ-SIM-011")
def test_base_pack_ships_two_school_technologies(registry: Registry) -> None:
    """AC3: at least two sample technologies are researchable at the school."""
    techs = [tech for tech in registry.technologies.values() if tech.building == "school"]
    assert len(techs) >= 2
    assert {tech.scope for tech in techs} == {"villager", "village"}


@pytest.mark.req("REQ-SIM-011")
def test_a_school_technology_can_be_researched(registry: Registry) -> None:
    """AC3: crop_rotation is researched at a completed school and unlocks for the village."""
    villager = Villager("a", "Ana", Coord(0, 0))
    villager.inventory.add(registry, "grain", 10)
    state = grass_world([villager])
    state.buildings["b0"] = Building(
        "b0", "school", Coord(1, 0), Ownership("communal"), complete=True
    )
    engine = Engine(registry, default_config(debug_invariants=True))
    engine.step(state, [Research("a", "crop_rotation", "b0")])
    for _ in range(registry.technologies["crop_rotation"].research_ticks):
        engine.step(state, [])
    assert "crop_rotation" in state.village_knowledge


@pytest.mark.req("REQ-SIM-003")
def test_the_default_winter_blocks_farming(registry: Registry) -> None:
    """AC2: in the default calendar, winter rejects sowing actions such as farm_grain."""
    assert DEFAULT_CALENDAR.seasons[-1].name == "winter"
    assert DEFAULT_CALENDAR.seasons[-1].blocked_tags == ("sowing",)
    assert "sowing" in registry.actions["farm_grain"].tags
    winter_start = 30 * DEFAULT_CALENDAR.ticks_per_day
    outcomes = []
    for tick in (0, winter_start):
        state = grass_world([Villager("a", "Ana", Coord(0, 0))])
        state.tick = tick
        state.buildings["b0"] = Building(
            "b0", "farm", Coord(1, 0), Ownership("communal"), complete=True
        )
        events = Engine(registry, default_config()).step(
            state, [StartAction("a", "farm_grain", "b0")]
        )[1]
        outcomes.append((events[0].kind, events[0].data.get("reason")))
    assert outcomes == [("work_started", None), ("intent_rejected", "season")]


def test_default_config_accepts_overrides() -> None:
    config = default_config(carry_limit=12.0)
    assert (config.calendar, config.carry_limit) == (DEFAULT_CALENDAR, 12.0)


@pytest.mark.req("REQ-SIM-009")
def test_a_farm_hosts_four_farmers(registry: Registry) -> None:
    """AC3: the farm declares four workers; a fifth farmer is turned away."""
    names = ["a", "b", "c", "d", "e"]
    spots = [Coord(1, 2), Coord(1, 3), Coord(1, 4), Coord(2, 1), Coord(3, 1)]
    state = grass_world(
        [Villager(n, n.upper(), spot) for n, spot in zip(names, spots, strict=True)]
    )
    state.buildings["b0"] = Building(
        "b0", "farm", Coord(2, 2), Ownership("communal"), complete=True
    )
    engine = Engine(registry, default_config())
    kinds = [
        engine.step(state, [StartAction(n, "farm_grain", "b0")])[1][0].data.get("reason")
        for n in names
    ]
    assert kinds == [None, None, None, None, "building_full"]


@pytest.mark.req("REQ-SIM-009")
def test_grain_becomes_flour_becomes_bread(registry: Registry) -> None:
    """AC4: the mill grinds grain into flour and the bakery bakes it into bread."""
    grind, bake = registry.recipes["grind_flour"], registry.recipes["bake_bread"]
    assert (grind.building, dict(grind.inputs), dict(grind.outputs)) == (
        "mill",
        {"grain": 3},
        {"flour": 2},
    )
    assert (bake.building, dict(bake.inputs), dict(bake.outputs)) == (
        "bakery",
        {"flour": 2, "wood": 1},
        {"bread": 2},
    )
    assert registry.items["grain"].nutrition == 3
    assert registry.items["bread"].nutrition == 20
    assert registry.items["flour"].nutrition == 0
    # Processing pays: 3 grain (9 nutrition) become 2 bread (40).
    assert 2 * registry.items["bread"].nutrition > 3 * registry.items["grain"].nutrition


@pytest.mark.req("REQ-SIM-012")
def test_base_needs_damage_and_relief(registry: Registry) -> None:
    """AC1/AC2: hunger and cold can kill (starvation, cold); fatigue is relieved by sleep."""
    needs = registry.needs
    assert (needs["hunger"].relief, needs["hunger"].death_cause) == ("eat", "starvation")
    assert (needs["cold"].relief, needs["cold"].death_cause) == ("shelter", "cold")
    assert (needs["fatigue"].relief, needs["fatigue"].damage_per_hour) == ("sleep", 0.0)


@pytest.mark.req("REQ-SIM-016")
def test_children_can_gather_berries(registry: Registry) -> None:
    """AC1: berry gathering is light work, the one base action children may do."""
    light = sorted(a.id for a in registry.actions.values() if "light" in a.tags)
    assert light == ["gather_berries"]
