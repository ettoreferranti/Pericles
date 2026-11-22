import pytest

from pericles.core.content.registry import Registry, base_pack_path, load_registry
from pericles.core.mapgen import Band, MapParams, TileMap, Vein, generate_map


@pytest.fixture(scope="session")
def registry() -> Registry:
    return load_registry([base_pack_path()])


@pytest.fixture
def map_params() -> MapParams:
    return MapParams(
        width=64,
        height=64,
        bands=(
            Band("water", 0.12),
            Band("fertile_soil", 0.18),
            Band("grass", 0.35),
            Band("forest", 0.25),
            Band("rock", 0.10),
        ),
        veins=(Vein("iron_vein", 0.02, "rock"), Vein("gold_vein", 0.005, "rock")),
        start_terrain="grass",
        start_radius=6,
    )


@pytest.fixture
def small_map(registry: Registry) -> TileMap:
    params = MapParams(
        width=24,
        height=24,
        bands=(Band("water", 0.15), Band("grass", 0.6), Band("forest", 0.25)),
        start_terrain="grass",
        start_radius=5,
        feature_size=8,
    )
    return generate_map(11, params, registry)
