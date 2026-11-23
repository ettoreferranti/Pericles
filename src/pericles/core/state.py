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


def _optional_str(value: Any) -> str | None:
    return None if value is None else str(value)


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
class Pregnancy:
    father: str
    due_tick: int

    def to_dict(self) -> dict[str, Any]:
        return {"father": self.father, "due_tick": self.due_tick}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Pregnancy:
        return cls(str(data["father"]), int(data["due_tick"]))


@dataclass(frozen=True)
class Proposal:
    """An open couple proposal to `target`, lapsing after `expires_tick` (ADR-0015 §6)."""

    target: str
    expires_tick: int

    def to_dict(self) -> dict[str, Any]:
        return {"target": self.target, "expires_tick": self.expires_tick}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Proposal:
        return cls(str(data["target"]), int(data["expires_tick"]))


@dataclass(frozen=True)
class Deceased:
    """What the world remembers of a dead villager: lineage and the model they ran on."""

    id: str
    name: str
    sex: str | None
    born_tick: int
    died_tick: int
    cause: str
    parents: tuple[str, ...]
    model: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "sex": self.sex,
            "born_tick": self.born_tick,
            "died_tick": self.died_tick,
            "cause": self.cause,
            "parents": list(self.parents),
            "model": self.model,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Deceased:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            sex=_optional_str(data["sex"]),
            born_tick=int(data["born_tick"]),
            died_tick=int(data["died_tick"]),
            cause=str(data["cause"]),
            parents=tuple(str(p) for p in data["parents"]),
            model=_optional_str(data["model"]),
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
    sex: str | None = None
    born_tick: int = 0
    adult: bool = True
    needs: dict[str, float] = field(default_factory=dict)
    damage: float = 0.0
    home: str | None = None
    partner: str | None = None
    parents: tuple[str, ...] = ()
    pregnancy: Pregnancy | None = None
    last_birth_tick: int | None = None
    model: str | None = None
    witnessed: list[dict[str, Any]] = field(default_factory=list)
    memories: list[dict[str, Any]] = field(default_factory=list)

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
            "sex": self.sex,
            "born_tick": self.born_tick,
            "adult": self.adult,
            "needs": dict(sorted(self.needs.items())),
            "damage": self.damage,
            "home": self.home,
            "partner": self.partner,
            "parents": list(self.parents),
            "pregnancy": None if self.pregnancy is None else self.pregnancy.to_dict(),
            "last_birth_tick": self.last_birth_tick,
            "model": self.model,
            "witnessed": [dict(record) for record in self.witnessed],
            "memories": [dict(record) for record in self.memories],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Villager:
        activity = data["activity"]
        pregnancy = data["pregnancy"]
        last_birth = data["last_birth_tick"]
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
            sex=_optional_str(data["sex"]),
            born_tick=int(data["born_tick"]),
            adult=bool(data["adult"]),
            needs={str(k): float(v) for k, v in data["needs"].items()},
            damage=float(data["damage"]),
            home=_optional_str(data["home"]),
            partner=_optional_str(data["partner"]),
            parents=tuple(str(p) for p in data["parents"]),
            pregnancy=None if pregnancy is None else Pregnancy.from_dict(pregnancy),
            last_birth_tick=None if last_birth is None else int(last_birth),
            model=_optional_str(data["model"]),
            witnessed=[dict(record) for record in data["witnessed"]],
            memories=[dict(record) for record in data["memories"]],
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
    dead: dict[str, Deceased] = field(default_factory=dict)
    proposals: dict[str, Proposal] = field(default_factory=dict)
    next_villager: int = 0

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
            "dead": [self.dead[k].to_dict() for k in sorted(self.dead)],
            "proposals": {k: self.proposals[k].to_dict() for k in sorted(self.proposals)},
            "next_villager": self.next_villager,
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
            dead={d.id: d for d in (Deceased.from_dict(x) for x in data["dead"])},
            proposals={str(k): Proposal.from_dict(v) for k, v in data["proposals"].items()},
            next_villager=int(data["next_villager"]),
        )

    def digest(self) -> str:
        return digest(self.to_dict())
