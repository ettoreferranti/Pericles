"""Pydantic schemas for content pack files (REQ-SIM-005, ADR-0005, ADR-0013)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Id = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]*$")]
Count = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
NonNegative = Annotated[float, Field(ge=0)]
Bundle = dict[Id, Count]
TargetKind = Literal["action", "recipe", "building", "need", "item", "node"]

SECTIONS: tuple[str, ...] = (
    "terrains",
    "items",
    "nodes",
    "needs",
    "actions",
    "recipes",
    "buildings",
    "technologies",
    "traits",
)
TARGET_SECTION: dict[str, str] = {
    "action": "actions",
    "recipe": "recipes",
    "building": "buildings",
    "need": "needs",
    "item": "items",
    "node": "nodes",
}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TargetDef(Model):
    kind: TargetKind
    id: Id | None = None
    tag: Id | None = None


class ModifierDef(Model):
    target: TargetDef
    attribute: Id
    op: Literal["add", "mul", "set"]
    value: float


class TerrainDef(Model):
    id: Id
    walkable: bool
    move_cost: float = Field(default=1.0, gt=0)
    color: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")


class ItemDef(Model):
    id: Id
    weight: NonNegative = 1.0
    nutrition: NonNegative = 0.0
    tags: tuple[Id, ...] = ()
    durability: Count | None = None
    modifiers: tuple[ModifierDef, ...] = ()


class NodeDef(Model):
    id: Id
    yields: Id
    terrains: tuple[Id, ...] = Field(min_length=1)
    density: float = Field(gt=0, le=1)
    stock: Count
    regrowth_per_day: NonNegative = 0.0


class NeedDef(Model):
    id: Id
    rate_per_hour: NonNegative
    critical: float = Field(default=100.0, gt=0, le=100)


class RequiresDef(Model):
    tools: tuple[Id, ...] = ()
    skill: Id | None = None
    min_skill: NonNegative = 0.0
    knowledge: bool = False


class LocationDef(Model):
    node: Id | None = None
    building: Id | None = None
    terrains: tuple[Id, ...] = ()


class ActionDef(Model):
    id: Id
    duration_ticks: Count
    inputs: Bundle = Field(default_factory=dict)
    outputs: Bundle = Field(default_factory=dict)
    skill: Id | None = None
    requires: RequiresDef = RequiresDef()
    location: LocationDef = LocationDef()
    tags: tuple[Id, ...] = ()


class RecipeDef(Model):
    id: Id
    building: Id
    inputs: Bundle = Field(default_factory=dict)
    outputs: Bundle = Field(min_length=1)
    work_ticks: Count
    skill: Id | None = None


class BuildingDef(Model):
    id: Id
    cost: Bundle = Field(default_factory=dict)
    build_work: Count
    footprint: tuple[Count, Count] = (1, 1)
    workers: NonNegativeInt = 0
    housing: NonNegativeInt = 0
    storage: NonNegativeInt = 0
    entrance: bool = True
    tags: tuple[Id, ...] = ()


class TechDef(Model):
    id: Id
    building: Id
    cost: Bundle = Field(default_factory=dict)
    research_ticks: Count
    scope: Literal["villager", "village"] = "villager"
    unlocks_recipes: tuple[Id, ...] = ()
    unlocks_buildings: tuple[Id, ...] = ()
    modifiers: tuple[ModifierDef, ...] = ()


class TraitDef(Model):
    id: Id
    description: str = Field(min_length=1)
    modifiers: tuple[ModifierDef, ...] = ()


class PackFile(Model):
    terrains: tuple[TerrainDef, ...] = ()
    items: tuple[ItemDef, ...] = ()
    nodes: tuple[NodeDef, ...] = ()
    needs: tuple[NeedDef, ...] = ()
    actions: tuple[ActionDef, ...] = ()
    recipes: tuple[RecipeDef, ...] = ()
    buildings: tuple[BuildingDef, ...] = ()
    technologies: tuple[TechDef, ...] = ()
    traits: tuple[TraitDef, ...] = ()
