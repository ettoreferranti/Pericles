import random
import re
from collections import deque
from dataclasses import replace
from typing import Any

import pytest

from pericles.core.content.registry import Registry
from pericles.core.geometry import Coord
from pericles.core.mapgen import (
    _EPS,
    Band,
    MapParams,
    TileMap,
    Vein,
    generate_map,
    start_area,
    value_noise,
)

pytestmark = pytest.mark.req("REQ-SIM-001")


def test_same_seed_same_map(registry: Registry, map_params: MapParams) -> None:
    """AC1: same seed and parameters produce an identical map."""
    a = generate_map(7, map_params, registry)
    b = generate_map(7, map_params, registry)
    assert a.digest() == b.digest()
    assert a.terrain == b.terrain


def test_different_seeds_differ(registry: Registry, map_params: MapParams) -> None:
    """AC2."""
    digests = {generate_map(seed, map_params, registry).digest() for seed in range(5)}
    assert len(digests) == 5


def test_full_size_proportions_within_five_points(
    registry: Registry, map_params: MapParams
) -> None:
    """AC3: every requested terrain is present, within ±5 percentage points."""
    params = replace(map_params, width=128, height=128, start_radius=10)
    tilemap = generate_map(3, params, registry)
    counts = tilemap.counts()
    n = 128 * 128
    expected = {band.terrain: band.share for band in params.bands}
    for vein in params.veins:
        expected[vein.terrain] = vein.share
        expected[vein.host] -= vein.share
    assert set(counts) == set(expected)
    for terrain, share in expected.items():
        assert counts[terrain] > 0
        assert abs(counts[terrain] / n - share) <= 0.05, terrain


def test_every_tile_is_assigned(registry: Registry, map_params: MapParams) -> None:
    tilemap = generate_map(1, map_params, registry)
    assert len(tilemap.terrain) == 64 * 64
    assert all(t in registry.terrains for t in tilemap.terrain)
    assert len(tilemap.elevation) == 64 * 64
    assert all(0.0 <= e <= 1.0 for e in tilemap.elevation)


@pytest.mark.parametrize("seed", range(10))
def test_start_area_is_walkable_and_connected(
    registry: Registry, map_params: MapParams, seed: int
) -> None:
    """AC4: all walkable tiles of the starting area are mutually reachable."""
    tilemap = generate_map(seed, map_params, registry)
    area = set(start_area(64, 64, map_params.start_radius))
    assert all(registry.terrains[tilemap.terrain_at(c)].walkable for c in area)
    seen = {tilemap.start()}
    queue = deque([tilemap.start()])
    while queue:
        for nb in queue.popleft().neighbours4():
            if nb in area and nb not in seen:
                seen.add(nb)
                queue.append(nb)
    assert seen == area


def test_start_area_shape_and_clipping() -> None:
    area = start_area(5, 5, 1)
    assert area == [Coord(2, 1), Coord(1, 2), Coord(2, 2), Coord(3, 2), Coord(2, 3)]
    assert len(start_area(3, 3, 10)) == 9
    assert start_area(1, 1, 0) == [Coord(0, 0)]


def test_tiny_and_non_square_maps(registry: Registry, map_params: MapParams) -> None:
    for width, height in [(1, 1), (2, 9), (17, 5)]:
        params = replace(map_params, width=width, height=height, start_radius=50)
        tilemap = generate_map(0, params, registry)
        assert len(tilemap.terrain) == width * height
        assert all(registry.terrains[t].walkable for t in tilemap.terrain)


def test_tilemap_accessors_and_round_trip(registry: Registry, map_params: MapParams) -> None:
    tilemap = generate_map(5, map_params, registry)
    assert tilemap.in_bounds(Coord(0, 0)) and tilemap.in_bounds(Coord(63, 63))
    assert not tilemap.in_bounds(Coord(64, 0)) and not tilemap.in_bounds(Coord(0, -1))
    assert tilemap.terrain_at(Coord(3, 2)) == tilemap.terrain[2 * 64 + 3]
    assert tilemap.start() == Coord(32, 32)
    clone = TileMap.from_dict(tilemap.to_dict())
    assert clone.digest() == tilemap.digest()
    assert clone.terrain == tilemap.terrain and clone.elevation == tilemap.elevation


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"bands": (Band("grass", 0.5), Band("water", 0.4))}, "sum to 1"),
        ({"bands": (Band("grass", 1.2), Band("water", -0.2))}, "non-negative"),
        ({"bands": (Band("grass", float("nan")),)}, "finite"),
        ({"veins": (Vein("iron_vein", float("inf"), "rock"),)}, "finite"),
        ({"veins": (Vein("iron_vein", -0.01, "rock"),)}, "share must be non-negative"),
        ({"bands": ()}, "at least one band"),
        ({"bands": (Band("lava", 1.0),)}, "unknown terrain 'lava'"),
        ({"veins": (Vein("iron_vein", 0.01, "desert"),)}, "host 'desert' is not a band"),
        ({"veins": (Vein("iron_vein", 0.5, "rock"),)}, "more than their host"),
        ({"start_terrain": "water"}, "start_terrain 'water' is not walkable"),
        ({"width": 0}, "width and height"),
        ({"start_radius": -1}, "start_radius"),
        ({"feature_size": 0}, "feature_size"),
        ({"octaves": 0}, "octaves"),
    ],
)
def test_invalid_parameters_are_rejected(
    registry: Registry, map_params: MapParams, change: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        generate_map(0, replace(map_params, **change), registry)  # type: ignore[arg-type]


def test_golden_map_digest(registry: Registry, map_params: MapParams) -> None:
    """AC1: the generator output is pinned, so any change to the algorithm is deliberate."""
    expected = "b24fcc747423788c5bb93d70a2d1d3088a7f0c8ac1945d7dde34d806f268b031"
    assert generate_map(7, map_params, registry).digest() == expected


def test_value_noise_golden_values() -> None:
    """AC1: noise is pinned for several octaves, including octaves whose cell size reaches 1."""
    a = value_noise(random.Random(1), 5, 4, 2, 3, persistence=0.5, lacunarity=2)
    assert a[:4] == pytest.approx(
        [0.2560550952206876, 0.6097787646439838, 0.7665138949358499, 0.5474850627547078]
    )
    assert a[-1] == pytest.approx(0.7038264769912655)
    b = value_noise(random.Random(1), 3, 3, 1, 6, persistence=0.5, lacunarity=2)
    assert b[:4] == pytest.approx(
        [0.2536509619027013, 0.577034648626269, 0.5891847802397457, 0.43208649189041837]
    )
    assert all(0.0 <= v <= 1.0 for v in a + b)


def test_bands_follow_elevation_order(registry: Registry, map_params: MapParams) -> None:
    """Bands are assigned low elevation first: mean elevation rises band by band."""
    params = replace(map_params, veins=(), start_radius=0)
    tilemap = generate_map(2, params, registry)
    centre = tilemap.start().y * tilemap.width + tilemap.start().x
    means = []
    for band in params.bands:
        values = [
            e
            for i, (t, e) in enumerate(zip(tilemap.terrain, tilemap.elevation, strict=True))
            if t == band.terrain and i != centre
        ]
        means.append(sum(values) / len(values))
    assert means == sorted(means)
    assert tilemap.elevation == [round(e, 6) for e in tilemap.elevation]


def test_vein_shares_are_exact_and_replace_hosts(registry: Registry, map_params: MapParams) -> None:
    tilemap = generate_map(4, replace(map_params, start_radius=0), registry)
    counts = tilemap.counts()
    assert counts["iron_vein"] == round(0.02 * 64 * 64)
    assert counts["gold_vein"] == round(0.005 * 64 * 64)


def test_tilemap_rejects_mismatched_sizes() -> None:
    message = "^terrain and elevation must have width \\* height entries$"
    with pytest.raises(ValueError, match=message):
        TileMap(2, 2, ["a"] * 4, [0.0] * 3)
    with pytest.raises(ValueError, match=message):
        TileMap(2, 2, ["a"] * 3, [0.0] * 4)


def test_tilemap_bounds_and_start(registry: Registry, map_params: MapParams) -> None:
    tilemap = generate_map(0, replace(map_params, width=17, height=5, start_radius=2), registry)
    assert tilemap.start() == Coord(8, 2)
    assert tilemap.in_bounds(Coord(16, 4)) and not tilemap.in_bounds(Coord(0, 5))
    assert not tilemap.in_bounds(Coord(17, 0)) and not tilemap.in_bounds(Coord(-1, 0))
    with pytest.raises(IndexError, match=re.escape("outside a 17x5 map")):
        tilemap.terrain_at(Coord(0, 5))


def test_boundary_parameters_are_accepted(registry: Registry, map_params: MapParams) -> None:
    """Zero radius, size-1 features, one octave, zero shares and exactly-full veins are legal."""
    generate_map(0, replace(map_params, start_radius=0, feature_size=1, octaves=1), registry)
    only_grass = (Band("grass", 1.0), Band("water", 0.0))
    generate_map(0, replace(map_params, bands=only_grass, veins=()), registry)
    full = (Vein("iron_vein", 0.0, "rock"), Vein("gold_vein", 0.10, "rock"))
    generate_map(0, replace(map_params, veins=full), registry)
    over = (Vein("iron_vein", 0.1 + 5e-10, "rock"),)
    generate_map(0, replace(map_params, veins=over), registry)
    zero_band = (Band("grass", 0.0), Band("water", 1.0))
    generate_map(0, replace(map_params, bands=zero_band, veins=()), registry)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"width": 0}, "width and height must be at least 1"),
        ({"height": 0}, "width and height must be at least 1"),
        ({"start_radius": -1}, "start_radius must be non-negative"),
        ({"feature_size": 0}, "feature_size must be at least 1"),
        ({"octaves": 0}, "octaves must be at least 1"),
        ({"start_terrain": "lava"}, "unknown terrain 'lava'"),
        ({"veins": (Vein("mithril", 0.01, "rock"),)}, "unknown terrain 'mithril'"),
        ({"bands": ()}, "map needs at least one band"),
        ({"bands": (Band("grass", float("nan")),)}, "shares must be finite numbers"),
        ({"bands": (Band("grass", 1.2), Band("water", -0.2))}, "band shares must be non-negative"),
        ({"bands": (Band("grass", 0.5), Band("water", 0.4))}, "band shares must sum to 1"),
        (
            {"veins": (Vein("iron_vein", -0.01, "rock"),)},
            "vein 'iron_vein': share must be non-negative",
        ),
        (
            {"veins": (Vein("iron_vein", 0.06, "rock"), Vein("gold_vein", 0.06, "rock"))},
            "veins on 'rock' take more than their host band's share",
        ),
    ],
)
def test_invalid_parameter_messages_are_exact(
    registry: Registry, map_params: MapParams, change: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=f"^{re.escape(message)}$"):
        generate_map(0, replace(map_params, **change), registry)  # type: ignore[arg-type]


def test_golden_digest_with_unit_feature_size(registry: Registry, map_params: MapParams) -> None:
    """AC1: veins use half the feature size but never less than one tile."""
    params = replace(map_params, feature_size=1)
    expected = "3867c47c9d20e106a70baf731696c25cf9919ad82ed113e3731204560e269b20"
    assert generate_map(7, params, registry).digest() == expected


def test_tolerance_boundaries_are_inclusive(registry: Registry, map_params: MapParams) -> None:
    """Shares may be off by exactly the tolerance, but not by more."""
    ok = (Band("grass", 1.0), Band("water", _EPS))
    generate_map(0, replace(map_params, bands=ok, veins=()), registry)
    bad = (Band("grass", 1.0), Band("water", 2 * _EPS))
    with pytest.raises(ValueError, match="sum to 1"):
        generate_map(0, replace(map_params, bands=bad, veins=()), registry)
    low = (Band("grass", 1.0 - 2 * _EPS),)
    with pytest.raises(ValueError, match="sum to 1"):
        generate_map(0, replace(map_params, bands=low, veins=()), registry)
    bands = (Band("grass", 0.5), Band("rock", 0.5))
    edge = (Vein("iron_vein", 0.5 + _EPS, "rock"),)
    generate_map(0, replace(map_params, bands=bands, veins=edge), registry)
    over = (Vein("iron_vein", 0.5 + 2 * _EPS, "rock"),)
    with pytest.raises(ValueError, match="more than their host"):
        generate_map(0, replace(map_params, bands=bands, veins=over), registry)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"persistence": 0.0}, r"^persistence must be in \(0, 1\]$"),
        ({"persistence": 1.5}, r"^persistence must be in \(0, 1\]$"),
        ({"lacunarity": 0}, "^lacunarity must be at least 1$"),
        ({"vein_feature_divisor": 0}, "^vein_feature_divisor must be at least 1$"),
    ],
)
def test_noise_parameters_are_validated(
    map_params: MapParams, registry: Registry, change: dict[str, Any], message: str
) -> None:
    """The noise tuning values are parameters, validated like the others."""
    with pytest.raises(ValueError, match=message):
        generate_map(7, replace(map_params, **change), registry)


def test_noise_parameters_change_the_map(map_params: MapParams, registry: Registry) -> None:
    """Persistence really feeds the noise (it is not a dead parameter)."""
    base = generate_map(7, map_params, registry).digest()
    rougher = generate_map(7, replace(map_params, persistence=0.9), registry).digest()
    assert rougher != base


def test_noise_parameters_accept_their_lower_bounds(
    map_params: MapParams, registry: Registry
) -> None:
    """The documented bounds are inclusive: persistence 1, lacunarity 1 and divisor 1 are valid."""
    edge = replace(map_params, persistence=1.0, lacunarity=1, vein_feature_divisor=1)
    assert generate_map(7, edge, registry).width == map_params.width
