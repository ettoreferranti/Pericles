"""experiment.yaml → a validated Experiment, and its starting world (REQ-EXP-001; ADR-0016 §5)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

from pericles.agents.config import AgentConfig
from pericles.core.config import EngineConfig
from pericles.core.content.loader import ContentError, read_yaml
from pericles.core.content.registry import Registry, base_pack_path, load_registry
from pericles.core.inventory import bundle_weight
from pericles.core.mapgen import Band, MapParams, Vein, generate_map, start_area, validate
from pericles.core.nodes import place_nodes
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_settings_mapping
from pericles.experiment.settings import (
    SettingsError,
    agent_config_from_mapping,
    as_mapping,
    engine_config_from_mapping,
    values_for,
)

SECTIONS = ("seed", "packs", "map", "population", "run", "engine", "agents")
REQUIRED = ("seed", "map", "population", "run")
BASE = "base"
ID = r"^[a-z][a-z0-9_]*$"


class ExperimentError(ValueError):
    """An experiment file is invalid; the message starts with the dotted field path."""


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VillagerSpec(_Spec):
    id: Annotated[StrictStr, Field(pattern=ID)]
    name: Annotated[StrictStr, Field(min_length=1)]
    sex: StrictStr | None = None
    age_days: Annotated[StrictInt, Field(ge=0)]
    traits: tuple[StrictStr, ...] = ()
    skills: dict[StrictStr, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)
    knowledge: tuple[StrictStr, ...] = ()
    model: StrictStr | None = None
    inventory: dict[StrictStr, Annotated[StrictInt, Field(gt=0)]] = Field(default_factory=dict)


class RunSpec(_Spec):
    days: Annotated[StrictInt, Field(gt=0)]
    snapshot_every_days: Annotated[StrictInt, Field(gt=0)]


@dataclass(frozen=True)
class Experiment:
    seed: int
    packs: tuple[Path, ...]
    map: MapParams
    population: tuple[VillagerSpec, ...]
    run: RunSpec
    engine: EngineConfig
    agents: AgentConfig
    registry: Registry
    resolved: dict[str, Any]


def _path(loc: Sequence[int | str]) -> str:
    return "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in loc)


def _pydantic(model: type[_Spec], data: object, where: str) -> Any:
    try:
        return model.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        raise ExperimentError(f"{where}{_path(first['loc'])}: {first['msg']}") from None


def _list(data: object, where: str) -> list[Any]:
    if not isinstance(data, list):
        raise ExperimentError(f"{where}: expected a list")
    return data


def _packs(data: object, base_dir: Path) -> tuple[Path, ...]:
    raw = [BASE] if data is None else data
    if not isinstance(raw, list) or not raw or not all(isinstance(p, str) for p in raw):
        raise ExperimentError("packs: expected a non-empty list of pack paths")
    return tuple(base_pack_path() if p == BASE else (base_dir / p).resolve() for p in raw)


def _registry(packs: tuple[Path, ...]) -> Registry:
    try:
        return load_registry(list(packs))
    except (ContentError, OSError) as error:
        raise ExperimentError(f"packs: {error}") from None


def _merged(section: str, data: object) -> dict[str, Any]:
    defaults = dict(default_settings_mapping()[section])
    overrides = {} if data is None else dict(as_mapping(data, section))
    return {**defaults, **overrides}


def _map(data: object, registry: Registry) -> MapParams:
    raw = as_mapping(data, "map")
    values = values_for(MapParams, raw, "map", nested={"bands", "veins"})

    def parts(key: str, cls: type[Any]) -> tuple[Any, ...]:
        items = _list(raw.get(key, []), f"map.{key}")
        return tuple(
            cls(**values_for(cls, as_mapping(item, f"map.{key}[{i}]"), f"map.{key}[{i}]", set()))
            for i, item in enumerate(items)
        )

    params = MapParams(**values, bands=parts("bands", Band), veins=parts("veins", Vein))
    try:
        validate(params, registry)
    except ValueError as error:
        raise ExperimentError(f"map: {error}") from None
    return params


def _check_agents(agents: AgentConfig, registry: Registry) -> None:
    for name, attribute in (("house_building", "housing"), ("store_building", "storage")):
        kind = getattr(agents, name)
        if kind not in registry.buildings:
            raise ExperimentError(f"agents.{name}: unknown building {kind!r}")
        if not getattr(registry.buildings[kind], attribute):
            raise ExperimentError(f"agents.{name}: {kind!r} has no {attribute}")


def _skills(registry: Registry) -> set[str]:
    named = {a.skill for a in registry.actions.values()}
    named |= {a.requires.skill for a in registry.actions.values()}
    named |= {r.skill for r in registry.recipes.values()}
    return {skill for skill in named if skill}


def _population(data: object, registry: Registry, engine: EngineConfig) -> tuple[VillagerSpec, ...]:
    skills = _skills(registry)
    known = registry.all_ids()
    specs: list[VillagerSpec] = []
    for i, entry in enumerate(_list(data, "population")):
        where = f"population[{i}]"
        spec: VillagerSpec = _pydantic(VillagerSpec, entry, where)
        if any(s.id == spec.id for s in specs):
            raise ExperimentError(f"{where}.id: duplicate id {spec.id!r}")
        if spec.sex is not None and spec.sex not in engine.sexes:
            raise ExperimentError(f"{where}.sex: must be one of {engine.sexes}")
        for j, trait in enumerate(spec.traits):
            if trait not in registry.traits:
                raise ExperimentError(f"{where}.traits[{j}]: unknown trait {trait!r}")
        for skill in sorted(spec.skills):
            if skill not in skills:
                raise ExperimentError(f"{where}.skills.{skill}: unknown skill")
            if spec.skills[skill] > engine.max_skill:
                raise ExperimentError(
                    f"{where}.skills.{skill}: at most max_skill {engine.max_skill}"
                )
        for j, ident in enumerate(spec.knowledge):
            if ident not in known:
                raise ExperimentError(f"{where}.knowledge[{j}]: unknown id {ident!r}")
        for item in sorted(spec.inventory):
            if item not in registry.items:
                raise ExperimentError(f"{where}.inventory.{item}: unknown item")
        if bundle_weight(registry, spec.inventory) > engine.carry_limit:
            raise ExperimentError(
                f"{where}.inventory: weighs more than carry_limit {engine.carry_limit}"
            )
        specs.append(spec)
    return tuple(specs)


def experiment_from_mapping(raw: object, base_dir: Path) -> Experiment:
    if not isinstance(raw, Mapping):
        raise ExperimentError("experiment: expected a mapping")
    for key in sorted(raw):
        if key not in SECTIONS:
            raise ExperimentError(f"{key}: unknown section")
    for key in REQUIRED:
        if key not in raw:
            raise ExperimentError(f"{key}: missing")
    seed = raw["seed"]
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise ExperimentError("seed: expected an integer")
    try:
        packs = _packs(raw.get("packs"), base_dir)
        registry = _registry(packs)
        engine_data = _merged("engine", raw.get("engine"))
        agents_data = _merged("agents", raw.get("agents"))
        engine = engine_config_from_mapping(engine_data, "engine")
        agents = agent_config_from_mapping(agents_data, "agents")
        _check_agents(agents, registry)
        params = _map(raw["map"], registry)
        population = _population(raw["population"], registry, engine)
        run: RunSpec = _pydantic(RunSpec, raw["run"], "run")
    except SettingsError as error:
        raise ExperimentError(str(error)) from None
    resolved = {
        "seed": seed,
        "packs": [str(p) for p in packs],
        "map": dict(as_mapping(raw["map"], "map")),
        "population": [spec.model_dump(mode="json", exclude_defaults=True) for spec in population],
        "run": run.model_dump(mode="json"),
        "engine": engine_data,
        "agents": agents_data,
    }
    return Experiment(seed, packs, params, population, run, engine, agents, registry, resolved)


def load_experiment(path: Path) -> Experiment:
    try:
        raw = read_yaml(path)
    except ContentError as error:
        raise ExperimentError(str(error)) from None
    return experiment_from_mapping(raw, path.parent)


def build_world(experiment: Experiment) -> WorldState:
    """Generate the map and nodes, and place the population near the centre (ADR-0016 §5)."""
    registry, engine = experiment.registry, experiment.engine
    tilemap = generate_map(experiment.seed, experiment.map, registry)
    centre = tilemap.start()
    spots = sorted(
        (
            c
            for c in start_area(tilemap.width, tilemap.height, experiment.map.start_radius)
            if registry.terrains[tilemap.terrain_at(c)].walkable
        ),
        key=lambda c: (centre.manhattan(c), c.y, c.x),
    )
    ticks = engine.calendar.ticks_per_day
    villagers = []
    for i, spec in enumerate(experiment.population):
        adult = spec.age_days >= engine.adult_age_days
        villager = Villager(
            spec.id,
            spec.name,
            spots[i % len(spots)],
            skills=dict(spec.skills),
            knowledge=set(spec.knowledge),
            traits=spec.traits,
            sex=spec.sex,
            born_tick=-spec.age_days * ticks,
            adult=adult,
            model=spec.model if adult else None,
        )
        for item, qty in sorted(spec.inventory.items()):
            villager.inventory.add(registry, item, qty)
        villagers.append(villager)
    nodes = place_nodes(experiment.seed, tilemap, registry)
    return WorldState.new(experiment.seed, tilemap, villagers, nodes)
