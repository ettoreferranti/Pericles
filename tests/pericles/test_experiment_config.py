import copy
from pathlib import Path
from typing import Any

import pytest

from pericles.core.content.registry import base_pack_path
from pericles.core.geometry import Coord
from pericles.experiment.config import (
    ExperimentError,
    build_world,
    experiment_from_mapping,
    load_experiment,
)
from pericles.experiment.defaults import default_agent_config, default_config

pytestmark = pytest.mark.req("REQ-EXP-001")
BASELINE = Path(__file__).parents[2] / "experiments" / "baseline.yaml"
MINIMAL: dict[str, Any] = {
    "seed": 3,
    "map": {
        "width": 24,
        "height": 24,
        "bands": [{"terrain": "grass", "share": 0.7}, {"terrain": "forest", "share": 0.3}],
        "start_terrain": "grass",
        "start_radius": 4,
        "feature_size": 8,
    },
    "population": [
        {"id": "a", "name": "A", "sex": "female", "age_days": 200, "skills": {"foraging": 5}},
        {
            "id": "b",
            "name": "B",
            "sex": "male",
            "age_days": 10,
            "inventory": {"berries": 3},
            "model": "m",
        },
    ],
    "run": {"days": 2, "snapshot_every_days": 1},
}


def changed(path: str, value: object) -> dict[str, Any]:
    """MINIMAL with the dotted `path` (list indices as numbers) set to `value`; None deletes."""
    data = copy.deepcopy(MINIMAL)
    *parents, last = [int(p) if p.isdigit() else p for p in path.split(".")]
    node: Any = data
    for part in parents:
        node = node[part]
    if value is None:
        del node[last]
    else:
        node[last] = value
    return data


def with_key(key: object) -> dict[Any, Any]:
    """MINIMAL plus an extra top-level entry under a non-string key."""
    return {**MINIMAL, key: 2}


def test_the_baseline_experiment_loads() -> None:
    """AC1: seed, map, packs, population, engine and agent parameters come from the file."""
    experiment = load_experiment(BASELINE)
    assert experiment.seed == 1
    assert experiment.packs == (base_pack_path(),)
    assert len(experiment.population) == 12
    assert experiment.engine == default_config()
    assert experiment.agents == default_agent_config()
    assert experiment.run.days == 60


def test_sections_override_the_packaged_defaults(tmp_path: Path) -> None:
    """AC1: engine and agents sections override the defaults key by key."""
    data = {
        **copy.deepcopy(MINIMAL),
        "engine": {"debug_invariants": True},
        "agents": {"idle_ticks": 4},
    }
    experiment = experiment_from_mapping(data, tmp_path)
    assert experiment.engine.debug_invariants
    assert experiment.engine.calendar == default_config().calendar
    assert experiment.agents.idle_ticks == 4


def test_the_resolved_config_rebuilds_the_same_experiment(tmp_path: Path) -> None:
    """AC1: the run directory's config snapshot alone reproduces the experiment."""
    first = experiment_from_mapping(copy.deepcopy(MINIMAL), tmp_path)
    again = experiment_from_mapping(copy.deepcopy(first.resolved), tmp_path / "elsewhere")
    assert (again.seed, again.map, again.population, again.run) == (
        first.seed,
        first.map,
        first.population,
        first.run,
    )
    assert (again.engine, again.agents, again.packs) == (first.engine, first.agents, first.packs)
    assert again.resolved == first.resolved


@pytest.mark.parametrize(
    ("data", "prefix"),
    [
        ({**MINIMAL, "sede": 1}, "sede: unknown section"),
        (changed("run", None), "run: missing"),
        (changed("seed", "x"), "seed: expected an integer"),
        (changed("seed", True), "seed: expected an integer"),
        ({**MINIMAL, "packs": ["no/such/pack"]}, "packs:"),
        ({**MINIMAL, "packs": "base"}, "packs: expected a non-empty list"),
        (changed("map.width", "64"), "map.width:"),
        (changed("map.bands", None), "map.bands: missing"),
        (changed("map.bands.0.colour", "red"), "map.bands[0].colour: unknown setting"),
        (changed("map.bands.0.terrain", "lava"), "map:"),
        (changed("population", {"a": 1}), "population: expected a list"),
        (changed("population.1.id", "a"), "population[1].id: duplicate id 'a'"),
        (changed("population.1.id", "Bad Id"), "population[1].id:"),
        (changed("population.0.age_days", "old"), "population[0].age_days:"),
        (changed("population.0.age", 3), "population[0].age:"),
        (changed("population.0.sex", "other"), "population[0].sex: must be one of"),
        (
            changed("population.0.traits", ["lazy"]),
            "population[0].traits[0]: unknown trait 'lazy'",
        ),
        (
            changed("population.0.skills", {"juggling": 3}),
            "population[0].skills.juggling: unknown skill",
        ),
        (
            changed("population.0.skills", {"foraging": 1000.0}),
            "population[0].skills.foraging: at most",
        ),
        (
            changed("population.0.knowledge", ["warp"]),
            "population[0].knowledge[0]: unknown id 'warp'",
        ),
        (
            changed("population.0.inventory", {"unobtainium": 1}),
            "population[0].inventory.unobtainium: unknown item",
        ),
        (
            changed("population.0.inventory", {"stone": 11}),
            "population[0].inventory: weighs more than carry_limit",
        ),
        (changed("run.days", 0), "run.days:"),
        ({**MINIMAL, "engine": {"carry_limit": "x"}}, "engine.carry_limit:"),
        ({**MINIMAL, "engine": {"sexes": ["x"]}}, "engine:"),
        (
            {**MINIMAL, "agents": {"house_building": "hut"}},
            "agents.house_building: unknown building 'hut'",
        ),
        (
            {**MINIMAL, "agents": {"store_building": "farm"}},
            "agents.store_building: 'farm' has no storage",
        ),
        (
            {**MINIMAL, "agents": {"house_building": "storehouse"}},
            "agents.house_building: 'storehouse' has no housing",
        ),
        ([1, 2], "experiment: expected a mapping"),
        (with_key(1), "experiment: setting names must be strings, got 1"),
        (with_key(None), "experiment: setting names must be strings, got None"),
        ({**MINIMAL, "engine": {1: 1}}, "engine: setting names must be strings, got 1"),
        ({**MINIMAL, "agents": {2: 1}}, "agents: setting names must be strings, got 2"),
        (changed("map", {1: 1}), "map: setting names must be strings, got 1"),
        (
            changed("map.bands.0", {1: 1}),
            "map.bands[0]: setting names must be strings, got 1",
        ),
        (changed("map", [1]), "map: expected a mapping"),
        (changed("run", [1]), "run: expected a mapping"),
        ({**MINIMAL, "engine": [1]}, "engine: expected a mapping"),
        ({**MINIMAL, "agents": 3}, "agents: expected a mapping"),
        (changed("population.0", "ada"), "population[0]: expected a mapping"),
        (changed("population", []), "population: expected at least one villager"),
        ({**MINIMAL, "packs": [3]}, "packs: expected a non-empty list"),
        (
            changed("population.0.inventory", {"berries": "3"}),
            "population[0].inventory.berries:",
        ),
        (changed("map.bands", "grass"), "map.bands: expected a list"),
    ],
)
def test_errors_name_the_field(tmp_path: Path, data: object, prefix: str) -> None:
    """AC2: the config is validated at load; errors name the field and the problem."""
    with pytest.raises(ExperimentError) as caught:
        experiment_from_mapping(data, tmp_path)
    assert str(caught.value).startswith(prefix), str(caught.value)


def test_null_packs_means_the_base_pack(tmp_path: Path) -> None:
    """AC1: an explicit `packs: null` is the same as leaving it out."""
    experiment = experiment_from_mapping({**copy.deepcopy(MINIMAL), "packs": None}, tmp_path)
    assert experiment.packs == (base_pack_path(),)


def test_load_reports_bad_yaml(tmp_path: Path) -> None:
    """AC2: unreadable files are experiment errors too."""
    path = tmp_path / "e.yaml"
    path.write_text("seed: [1\n", encoding="utf-8")
    with pytest.raises(ExperimentError, match="invalid YAML"):
        load_experiment(path)


def test_build_world_places_the_population(tmp_path: Path) -> None:
    """AC1: villagers start near the centre, with their age, adulthood, model and belongings."""
    experiment = experiment_from_mapping(copy.deepcopy(MINIMAL), tmp_path)
    world = build_world(experiment)
    a, b = world.villagers["a"], world.villagers["b"]
    tpd = experiment.engine.calendar.ticks_per_day
    assert (a.born_tick, b.born_tick) == (-200 * tpd, -10 * tpd)
    assert a.adult and not b.adult
    assert b.model is None  # children get a model when they come of age
    assert b.inventory.count("berries") == 3
    assert a.skills == {"foraging": 5.0}
    centre = world.tilemap.start()
    assert a.pos != b.pos
    assert max(centre.manhattan(v.pos) for v in (a, b)) <= 1
    assert world.nodes and world.digest() == build_world(experiment).digest()
    assert isinstance(a.pos, Coord)
