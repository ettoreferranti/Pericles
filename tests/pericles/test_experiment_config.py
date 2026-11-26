import copy
from pathlib import Path
from typing import Any

import pytest

from pericles.core.content.registry import base_pack_path
from pericles.core.geometry import Coord
from pericles.experiment import config as config_module
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
    "llm": {
        "backends": {"test": {"kind": "fake"}},
        "models": {"m": {"backend": "test", "name": "fake-m"}},
    },
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


@pytest.fixture
def no_start_tiles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Map validation keeps the start area walkable; empty it to reach build_world's guard."""
    monkeypatch.setattr(config_module, "start_area", lambda width, height, radius: [])


@pytest.mark.usefixtures("no_start_tiles")
def test_a_start_area_without_walkable_tiles_is_a_field_error(tmp_path: Path) -> None:
    """AC1: villagers need a walkable start tile; the error names the field, not a crash."""
    with pytest.raises(ExperimentError, match=r"^map\.start_radius: "):
        build_world(experiment_from_mapping(MINIMAL, tmp_path))


@pytest.mark.usefixtures("no_start_tiles")
def test_a_world_that_cannot_be_built_creates_no_run_directory(tmp_path: Path) -> None:
    """AC1: start builds the world before it creates the run directory."""
    from pericles.experiment.launch import start

    with pytest.raises(ExperimentError):
        start(experiment_from_mapping(MINIMAL, tmp_path), tmp_path / "run")
    assert not (tmp_path / "run").exists()


@pytest.mark.req("REQ-EXP-001")
def test_a_map_larger_than_max_map_tiles_is_a_field_error(tmp_path: Path) -> None:
    """AC2: a typo like width 1000000000 is refused before the map is generated."""
    data = changed("map.width", 1_000_000_000)
    with pytest.raises(ExperimentError, match=r"^map: .* more than engine.max_map_tiles"):
        experiment_from_mapping(data, tmp_path)


@pytest.mark.req("REQ-EXP-001")
def test_max_map_tiles_is_a_setting(tmp_path: Path) -> None:
    """AC2: the bound itself comes from the engine section."""
    data = {**MINIMAL, "engine": {"max_map_tiles": 100}}
    with pytest.raises(ExperimentError, match="24 × 24 = 576 tiles"):  # noqa: RUF001
        experiment_from_mapping(data, tmp_path)


@pytest.mark.req("REQ-EXP-001")
@pytest.mark.parametrize("value", [True, "5"])
def test_skills_must_be_numbers(tmp_path: Path, value: object) -> None:
    """AC2: a bool or a string is not a skill level."""
    data = changed("population.0.skills.foraging", value)
    with pytest.raises(ExperimentError, match=r"^population\[0\]\.skills\.foraging"):
        experiment_from_mapping(data, tmp_path)


@pytest.mark.req("REQ-EXP-001")
@pytest.mark.parametrize("key", ["bands", "veins"])
def test_duplicate_terrains_are_field_errors(tmp_path: Path, key: str) -> None:
    """AC2: a terrain listed twice in bands or veins names the second entry."""
    entries = {
        "bands": [{"terrain": "grass", "share": 0.5}, {"terrain": "grass", "share": 0.2}],
        "veins": [
            {"terrain": "iron_vein", "share": 0.01, "host": "grass"},
            {"terrain": "iron_vein", "share": 0.01, "host": "grass"},
        ],
    }
    data = changed(f"map.{key}", entries[key])
    with pytest.raises(ExperimentError, match=rf"^map\.{key}\[1\]\.terrain: duplicate"):
        experiment_from_mapping(data, tmp_path)


@pytest.mark.req("REQ-EXP-001")
def test_nested_settings_merge_key_by_key(tmp_path: Path) -> None:
    """AC1: overriding one relief's act_at keeps the defaults for the others."""
    data = {**MINIMAL, "agents": {"act_at": {"eat": 40.0}}}
    experiment = experiment_from_mapping(data, tmp_path)
    assert experiment.agents.act_at["eat"] == 40.0
    assert experiment.agents.act_at["sleep"] == 75.0


@pytest.mark.req("REQ-EXP-001")
def test_the_resolved_config_is_portable(tmp_path: Path) -> None:
    """AC1: the base pack is stored by name and the map holds every MapParams field."""
    resolved = experiment_from_mapping(MINIMAL, tmp_path).resolved
    assert resolved["packs"] == ["base"]
    assert resolved["map"]["octaves"] == 3
    assert resolved["map"]["veins"] == []
    rebuilt = experiment_from_mapping(resolved, tmp_path / "elsewhere")
    assert rebuilt.map == experiment_from_mapping(MINIMAL, tmp_path).map


@pytest.mark.req("REQ-LLM-006")
def test_the_llm_section_assigns_models_and_is_resolved(tmp_path: Path) -> None:
    """AC1: pinned villagers keep their model; the split is recorded in the resolved config."""
    data = changed("llm.assign", {"m": 1.0})
    data["population"].append({"id": "c", "name": "C", "sex": "male", "age_days": 300})
    experiment = experiment_from_mapping(data, tmp_path)
    models = {spec.id: spec.model for spec in experiment.population}
    assert models == {"a": "m", "b": "m", "c": "m"}
    assert experiment.llm.models["m"].name == "fake-m"
    resolved = experiment.resolved
    assert [p.get("model") for p in resolved["population"]] == ["m", "m", "m"]
    assert resolved["llm"]["models"]["m"]["temperature"] == 0.7
    again = experiment_from_mapping(resolved, tmp_path)
    assert again.population == experiment.population and again.llm == experiment.llm


@pytest.mark.req("REQ-LLM-006")
def test_paths_in_the_llm_section_resolve_against_the_experiment(tmp_path: Path) -> None:
    """AC1: fake replies and cache_from are stored as absolute paths."""
    data = changed("llm.backends.test", {"kind": "fake", "replies": "replies.yaml"})
    data["llm"]["cache"] = "replay"
    data["llm"]["cache_from"] = "old-run"
    experiment = experiment_from_mapping(data, tmp_path)
    assert experiment.llm.backends["test"].replies == str((tmp_path / "replies.yaml").resolve())
    assert experiment.llm.cache_from == str((tmp_path / "old-run").resolve())


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize(
    ("path", "value", "prefix"),
    [
        ("population.1.model", "ghost", r"population\[1\]\.model: unknown model 'ghost'"),
        (
            "engine",
            {"model_rule": "fixed", "adult_model": "ghost"},
            r"engine\.adult_model: unknown model 'ghost'",
        ),
        ("llm.models.m.backend", "nowhere", r"llm: models\.m\.backend: unknown backend"),
        ("llm.assign", {"ghost": 1.0}, r"llm: assign\.ghost: unknown model"),
        ("llm.colour", "red", r"llm\.colour: unknown setting"),
    ],
)
def test_model_errors_name_the_field(tmp_path: Path, path: str, value: object, prefix: str) -> None:
    """AC1: an undefined model or backend is a field error."""
    with pytest.raises(ExperimentError, match=f"^{prefix}"):
        experiment_from_mapping(changed(path, value), tmp_path)
