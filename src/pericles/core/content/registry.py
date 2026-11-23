"""Merge content packs into an immutable, referentially checked registry (REQ-SIM-005)."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import cast

from pericles.core.content.loader import ContentError, Pack, load_pack
from pericles.core.content.schema import (
    SECTIONS,
    TARGET_SECTION,
    ActionDef,
    BuildingDef,
    ItemDef,
    Model,
    ModifierDef,
    NeedDef,
    NodeDef,
    RecipeDef,
    TechDef,
    TerrainDef,
    TraitDef,
)

logger = logging.getLogger("pericles.core.content")


@dataclass(frozen=True)
class Override:
    section: str
    id: str
    previous_pack: str
    pack: str


@dataclass(frozen=True)
class Registry:
    terrains: Mapping[str, TerrainDef]
    items: Mapping[str, ItemDef]
    nodes: Mapping[str, NodeDef]
    needs: Mapping[str, NeedDef]
    actions: Mapping[str, ActionDef]
    recipes: Mapping[str, RecipeDef]
    buildings: Mapping[str, BuildingDef]
    technologies: Mapping[str, TechDef]
    traits: Mapping[str, TraitDef]
    packs: tuple[str, ...]
    origins: Mapping[tuple[str, str], str]
    overrides: tuple[Override, ...]

    def section(self, name: str) -> Mapping[str, Model]:
        if name not in SECTIONS:
            raise KeyError(name)
        return cast(Mapping[str, Model], getattr(self, name))

    def all_ids(self) -> frozenset[str]:
        return frozenset(ident for name in SECTIONS for ident in self.section(name))


def base_pack_path() -> Path:
    return Path(str(files("pericles.content").joinpath("base")))


def load_registry(paths: Sequence[Path]) -> Registry:
    return build_registry([load_pack(path) for path in paths])


def build_registry(packs: Sequence[Pack]) -> Registry:
    if not packs:
        raise ContentError("at least one content pack is required")
    merged: dict[str, dict[str, Model]] = {section: {} for section in SECTIONS}
    origins: dict[tuple[str, str], str] = {}
    overrides: list[Override] = []
    for pack in packs:
        for section in SECTIONS:
            for ident, definition in pack.defs[section].items():
                if ident in merged[section]:
                    previous = origins[(section, ident)]
                    overrides.append(Override(section, ident, previous, pack.name))
                    logger.info(
                        "content override: %s[%s] from pack %r replaced by pack %r",
                        section,
                        ident,
                        previous,
                        pack.name,
                    )
                merged[section][ident] = definition
                origins[(section, ident)] = pack.name

    def view(section: str) -> Mapping[str, Model]:
        return MappingProxyType(merged[section])

    registry = Registry(
        terrains=cast(Mapping[str, TerrainDef], view("terrains")),
        items=cast(Mapping[str, ItemDef], view("items")),
        nodes=cast(Mapping[str, NodeDef], view("nodes")),
        needs=cast(Mapping[str, NeedDef], view("needs")),
        actions=cast(Mapping[str, ActionDef], view("actions")),
        recipes=cast(Mapping[str, RecipeDef], view("recipes")),
        buildings=cast(Mapping[str, BuildingDef], view("buildings")),
        technologies=cast(Mapping[str, TechDef], view("technologies")),
        traits=cast(Mapping[str, TraitDef], view("traits")),
        packs=tuple(pack.name for pack in packs),
        origins=MappingProxyType(origins),
        overrides=tuple(overrides),
    )
    problems = check_references(registry)
    if problems:
        raise ContentError("\n".join(problems))
    return registry


def check_references(registry: Registry) -> list[str]:
    problems: list[str] = []

    def where(section: str, ident: str, field: str) -> str:
        return f"{registry.origins[(section, ident)]}: {section}[{ident}].{field}"

    def refs(section: str, ident: str, field: str, target: str, values: Iterable[str]) -> None:
        known = registry.section(target)
        for value in values:
            if value not in known:
                problems.append(f"{where(section, ident, field)}: unknown {target} id {value!r}")

    def tags(section: str, ident: str, field: str, target: str, values: Iterable[str]) -> None:
        for value in values:
            if not any(value in getattr(d, "tags", ()) for d in registry.section(target).values()):
                problems.append(f"{where(section, ident, field)}: no {target} have tag {value!r}")

    def modifiers(section: str, ident: str, mods: Iterable[ModifierDef]) -> None:
        for mod in mods:
            target = TARGET_SECTION[mod.target.kind]
            if mod.target.id is not None:
                refs(section, ident, "modifiers.target.id", target, [mod.target.id])
            if mod.target.tag is not None:
                tags(section, ident, "modifiers.target.tag", target, [mod.target.tag])

    for ident, node in registry.nodes.items():
        refs("nodes", ident, "yields", "items", [node.yields])
        refs("nodes", ident, "terrains", "terrains", node.terrains)
    for ident, item in registry.items.items():
        modifiers("items", ident, item.modifiers)
    for ident, action in registry.actions.items():
        refs("actions", ident, "inputs", "items", action.inputs)
        refs("actions", ident, "outputs", "items", action.outputs)
        tags("actions", ident, "requires.tools", "items", action.requires.tools)
        if action.location.node is not None:
            refs("actions", ident, "location.node", "nodes", [action.location.node])
        host = registry.nodes.get(action.location.node) if action.location.node else None
        if host is not None and host.yields in registry.items and host.yields not in action.outputs:
            problems.append(
                f"{where('actions', ident, 'outputs')}: must include {host.yields!r}, "
                f"the yield of node {action.location.node!r}"
            )
        if action.location.building is not None:
            refs("actions", ident, "location.building", "buildings", [action.location.building])
        refs("actions", ident, "location.terrains", "terrains", action.location.terrains)
    for ident, recipe in registry.recipes.items():
        refs("recipes", ident, "building", "buildings", [recipe.building])
        refs("recipes", ident, "inputs", "items", recipe.inputs)
        refs("recipes", ident, "outputs", "items", recipe.outputs)
    for ident, building in registry.buildings.items():
        refs("buildings", ident, "cost", "items", building.cost)
    for ident, tech in registry.technologies.items():
        refs("technologies", ident, "building", "buildings", [tech.building])
        refs("technologies", ident, "cost", "items", tech.cost)
        refs("technologies", ident, "unlocks_recipes", "recipes", tech.unlocks_recipes)
        refs("technologies", ident, "unlocks_buildings", "buildings", tech.unlocks_buildings)
        modifiers("technologies", ident, tech.modifiers)
    for ident, trait in registry.traits.items():
        modifiers("traits", ident, trait.modifiers)
    return problems
