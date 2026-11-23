"""The complete, serialisable world state (ADR-0013, ADR-0014)."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pericles.core.buildings import Building
from pericles.core.canonical import digest
from pericles.core.geometry import Coord
from pericles.core.inventory import Inventory
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import Modifier
from pericles.core.nodes import Node


@dataclass
class Activity:
    """Work in progress: an action, recipe, research or construction (ADR-0014)."""

    kind: str
    ident: str
    target: str | None
    work: float
    done: float
    speed: float
    reserved: Inventory = field(default_factory=Inventory)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "ident": self.ident,
            "target": self.target,
            "work": self.work,
            "done": self.done,
            "speed": self.speed,
            "reserved": self.reserved.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Activity:
        target = data["target"]
        return cls(
            str(data["kind"]),
            str(data["ident"]),
            None if target is None else str(target),
            float(data["work"]),
            float(data["done"]),
            float(data["speed"]),
            Inventory.from_dict(data["reserved"]),
        )


@dataclass
class Villager:
    id: str
    name: str
    pos: Coord
    path: list[Coord] = field(default_factory=list)
    move_progress: float = 0.0
    inventory: Inventory = field(default_factory=Inventory)
    skills: dict[str, float] = field(default_factory=dict)
    knowledge: set[str] = field(default_factory=set)
    traits: tuple[str, ...] = ()
    activity: Activity | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "pos": list(self.pos),
            "path": [list(c) for c in self.path],
            "move_progress": self.move_progress,
            "inventory": self.inventory.to_dict(),
            "skills": dict(sorted(self.skills.items())),
            "knowledge": sorted(self.knowledge),
            "traits": list(self.traits),
            "activity": None if self.activity is None else self.activity.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Villager:
        activity = data["activity"]
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            pos=Coord(*data["pos"]),
            path=[Coord(*c) for c in data["path"]],
            move_progress=float(data["move_progress"]),
            inventory=Inventory.from_dict(data["inventory"]),
            skills={str(k): float(v) for k, v in data["skills"].items()},
            knowledge={str(k) for k in data["knowledge"]},
            traits=tuple(str(t) for t in data["traits"]),
            activity=None if activity is None else Activity.from_dict(activity),
        )


def _rng_to_json(rng: random.Random) -> dict[str, Any]:
    version, internal, gauss = rng.getstate()
    return {"version": version, "internal": list(internal), "gauss": gauss}


def _rng_from_json(data: Mapping[str, Any]) -> random.Random:
    rng = random.Random()
    rng.setstate((data["version"], tuple(data["internal"]), data["gauss"]))
    return rng


@dataclass
class WorldState:
    seed: int
    tick: int
    tilemap: TileMap
    villagers: dict[str, Villager]
    modifiers: tuple[Modifier, ...]
    rng: random.Random
    nodes: dict[str, Node] = field(default_factory=dict)
    buildings: dict[str, Building] = field(default_factory=dict)
    village_knowledge: set[str] = field(default_factory=set)
    next_building: int = 0

    @classmethod
    def new(
        cls,
        seed: int,
        tilemap: TileMap,
        villagers: Iterable[Villager] = (),
        nodes: Iterable[Node] = (),
    ) -> WorldState:
        by_id: dict[str, Villager] = {}
        for villager in sorted(villagers, key=lambda v: v.id):
            if villager.id in by_id:
                raise ValueError(f"duplicate villager id {villager.id!r}")
            by_id[villager.id] = villager
        nodes_by_id: dict[str, Node] = {}
        for node in nodes:
            if node.id in nodes_by_id:
                raise ValueError(f"duplicate node id {node.id!r}")
            nodes_by_id[node.id] = node
        return cls(
            seed=seed,
            tick=0,
            tilemap=tilemap,
            villagers=by_id,
            modifiers=(),
            rng=random.Random(f"pericles-world-{seed}"),
            nodes=nodes_by_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "tick": self.tick,
            "tilemap": self.tilemap.to_dict(),
            "villagers": [self.villagers[k].to_dict() for k in sorted(self.villagers)],
            "modifiers": [m.to_dict() for m in self.modifiers],
            "rng": _rng_to_json(self.rng),
            "nodes": [self.nodes[k].to_dict() for k in sorted(self.nodes)],
            "buildings": [self.buildings[k].to_dict() for k in sorted(self.buildings)],
            "village_knowledge": sorted(self.village_knowledge),
            "next_building": self.next_building,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorldState:
        villagers = [Villager.from_dict(v) for v in data["villagers"]]
        nodes = [Node.from_dict(n) for n in data["nodes"]]
        buildings = [Building.from_dict(b) for b in data["buildings"]]
        return cls(
            seed=int(data["seed"]),
            tick=int(data["tick"]),
            tilemap=TileMap.from_dict(data["tilemap"]),
            villagers={v.id: v for v in villagers},
            modifiers=tuple(Modifier.from_dict(m) for m in data["modifiers"]),
            rng=_rng_from_json(data["rng"]),
            nodes={n.id: n for n in nodes},
            buildings={b.id: b for b in buildings},
            village_knowledge={str(k) for k in data["village_knowledge"]},
            next_building=int(data["next_building"]),
        )

    def digest(self) -> str:
        return digest(self.to_dict())
