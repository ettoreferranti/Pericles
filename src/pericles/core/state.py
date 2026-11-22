"""The complete, serialisable world state (ADR-0013)."""

from __future__ import annotations

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pericles.core.canonical import digest
from pericles.core.geometry import Coord
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import Modifier


@dataclass
class Villager:
    id: str
    name: str
    pos: Coord
    path: list[Coord] = field(default_factory=list)
    move_progress: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "pos": list(self.pos),
            "path": [list(c) for c in self.path],
            "move_progress": self.move_progress,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Villager:
        return cls(
            id=str(data["id"]),
            name=str(data["name"]),
            pos=Coord(*data["pos"]),
            path=[Coord(*c) for c in data["path"]],
            move_progress=float(data["move_progress"]),
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

    @classmethod
    def new(cls, seed: int, tilemap: TileMap, villagers: Iterable[Villager] = ()) -> WorldState:
        by_id: dict[str, Villager] = {}
        for villager in sorted(villagers, key=lambda v: v.id):
            if villager.id in by_id:
                raise ValueError(f"duplicate villager id {villager.id!r}")
            by_id[villager.id] = villager
        return cls(
            seed=seed,
            tick=0,
            tilemap=tilemap,
            villagers=by_id,
            modifiers=(),
            rng=random.Random(f"pericles-world-{seed}"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "tick": self.tick,
            "tilemap": self.tilemap.to_dict(),
            "villagers": [self.villagers[k].to_dict() for k in sorted(self.villagers)],
            "modifiers": [m.to_dict() for m in self.modifiers],
            "rng": _rng_to_json(self.rng),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorldState:
        villagers = [Villager.from_dict(v) for v in data["villagers"]]
        return cls(
            seed=int(data["seed"]),
            tick=int(data["tick"]),
            tilemap=TileMap.from_dict(data["tilemap"]),
            villagers={v.id: v for v in villagers},
            modifiers=tuple(Modifier.from_dict(m) for m in data["modifiers"]),
            rng=_rng_from_json(data["rng"]),
        )

    def digest(self) -> str:
        return digest(self.to_dict())
