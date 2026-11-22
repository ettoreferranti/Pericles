import pytest

from pericles.core.content.registry import Registry, base_pack_path, load_registry


@pytest.fixture(scope="session")
def registry() -> Registry:
    return load_registry([base_pack_path()])
