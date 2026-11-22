"""Seeded procedural tile maps (REQ-SIM-001)."""

from __future__ import annotations

import math
import random
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pericles.core.canonical import digest
from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord

_EPS = 2.0**-30  # a power of two, so boundary sums are exact in floating point


@dataclass(frozen=True)
class Band:
    terrain: str
    share: float


@dataclass(frozen=True)
class Vein:
    terrain: str
    share: float
    host: str


@dataclass(frozen=True)
class MapParams:
    width: int
    height: int
    bands: tuple[Band, ...]
    start_terrain: str
    veins: tuple[Vein, ...] = ()
    start_radius: int = 8
    feature_size: int = 16
    octaves: int = 3


class TileMap:
    def __init__(self, width: int, height: int, terrain: list[str], elevation: list[float]):
        if len(terrain) != width * height or len(elevation) != width * height:
            raise ValueError("terrain and elevation must have width * height entries")
        self.width = width
        self.height = height
        self.terrain = terrain
        self.elevation = elevation

    def in_bounds(self, c: Coord) -> bool:
        return 0 <= c.x < self.width and 0 <= c.y < self.height

    def terrain_at(self, c: Coord) -> str:
        if not self.in_bounds(c):
            raise IndexError(f"{c} is outside a {self.width}x{self.height} map")
        return self.terrain[c.y * self.width + c.x]

    def counts(self) -> dict[str, int]:
        return dict(Counter(self.terrain))

    def start(self) -> Coord:
        return Coord(self.width // 2, self.height // 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "terrain": list(self.terrain),
            "elevation": list(self.elevation),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TileMap:
        return cls(
            int(data["width"]),
            int(data["height"]),
            [str(t) for t in data["terrain"]],
            [float(e) for e in data["elevation"]],
        )

    def digest(self) -> str:
        return digest(self.to_dict())


def start_area(width: int, height: int, radius: int) -> list[Coord]:
    cx, cy = width // 2, height // 2
    return [
        Coord(x, y)
        for y in range(height)
        for x in range(width)
        if (x - cx) ** 2 + (y - cy) ** 2 <= radius * radius
    ]


def _smooth(t: float) -> float:
    return t * t * (3.0 - 2.0 * t)


def value_noise(
    rng: random.Random, width: int, height: int, feature_size: int, octaves: int
) -> list[float]:
    """Multi-octave value noise in [0, 1], fully determined by `rng`."""
    result = [0.0] * (width * height)
    amplitude = 1.0  # pragma: no mutate  (a uniform scale cancels in the normalisation)
    total, cell = 0.0, feature_size
    for _ in range(octaves):
        cell = max(1, cell)
        grid_w = width // cell + 2
        lattice = [rng.random() for _ in range(grid_w * (height // cell + 2))]
        for y in range(height):
            gy, fy = divmod(y, cell)
            ty = _smooth(fy / cell)
            for x in range(width):
                gx, fx = divmod(x, cell)
                tx = _smooth(fx / cell)
                i = gy * grid_w + gx
                top = lattice[i] + (lattice[i + 1] - lattice[i]) * tx
                bottom = lattice[i + grid_w] + (lattice[i + grid_w + 1] - lattice[i + grid_w]) * tx
                result[y * width + x] += amplitude * (top + (bottom - top) * ty)
        total += amplitude
        amplitude *= 0.5
        cell //= 2
    return [v / total for v in result]


def _validate(params: MapParams, registry: Registry) -> None:
    if params.width < 1 or params.height < 1:
        raise ValueError("width and height must be at least 1")
    if params.start_radius < 0:
        raise ValueError("start_radius must be non-negative")
    if params.feature_size < 1:
        raise ValueError("feature_size must be at least 1")
    if params.octaves < 1:
        raise ValueError("octaves must be at least 1")
    if not params.bands:
        raise ValueError("map needs at least one band")
    shares = [b.share for b in params.bands] + [v.share for v in params.veins]
    if not all(math.isfinite(share) for share in shares):
        raise ValueError("shares must be finite numbers")
    if any(band.share < 0 for band in params.bands):
        raise ValueError("band shares must be non-negative")
    if abs(sum(band.share for band in params.bands) - 1.0) > _EPS:
        raise ValueError("band shares must sum to 1")
    names = [b.terrain for b in params.bands] + [v.terrain for v in params.veins]
    for name in [*names, params.start_terrain]:
        if name not in registry.terrains:
            raise ValueError(f"unknown terrain {name!r}")
    band_share = {band.terrain: band.share for band in params.bands}
    vein_share: dict[str, float] = {}
    for vein in params.veins:
        if vein.host not in band_share:
            raise ValueError(f"vein {vein.terrain!r}: host {vein.host!r} is not a band")
        if vein.share < 0:
            raise ValueError(f"vein {vein.terrain!r}: share must be non-negative")
        vein_share[vein.host] = vein_share.get(vein.host, 0.0) + vein.share
    for host, share in vein_share.items():
        if share > band_share[host] + _EPS:
            raise ValueError(f"veins on {host!r} take more than their host band's share")
    if not registry.terrains[params.start_terrain].walkable:
        raise ValueError(f"start_terrain {params.start_terrain!r} is not walkable")


def generate_map(seed: int, params: MapParams, registry: Registry) -> TileMap:
    _validate(params, registry)
    width, height = params.width, params.height
    n = width * height
    rng = random.Random(seed)
    elevation = value_noise(rng, width, height, params.feature_size, params.octaves)
    order = sorted(range(n), key=lambda i: (elevation[i], i))
    terrain = [""] * n  # pragma: no mutate  (placeholder; every tile is reassigned)
    start, cumulative = 0, 0.0
    for band in params.bands:
        cumulative += band.share
        end = min(n, round(cumulative * n))
        for i in order[start:end]:
            terrain[i] = band.terrain
        start = max(start, end)
    for vein in params.veins:
        noise = value_noise(rng, width, height, max(1, params.feature_size // 2), params.octaves)
        hosts = sorted(
            (i for i in range(n) if terrain[i] == vein.host), key=lambda i: (-noise[i], i)
        )
        for i in hosts[: min(len(hosts), round(vein.share * n))]:
            terrain[i] = vein.terrain
    for c in start_area(width, height, params.start_radius):
        i = c.y * width + c.x
        if not registry.terrains[terrain[i]].walkable:
            terrain[i] = params.start_terrain
    return TileMap(width, height, terrain, [round(e, 6) for e in elevation])
