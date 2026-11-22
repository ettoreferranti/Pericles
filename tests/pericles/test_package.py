import importlib

import pytest

import pericles

SUBPACKAGES = ("core", "agents", "llm", "experiment", "server", "analysis")


@pytest.mark.req("REQ-NFR-002")
def test_package_exposes_version() -> None:
    """AC1: the core package installs and imports on the supported Python versions."""
    assert isinstance(pericles.__version__, str)
    assert pericles.__version__


@pytest.mark.req("REQ-NFR-002")
@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackages_import(name: str) -> None:
    """AC1: every architectural package from spec §3.1 exists and imports."""
    module = importlib.import_module(f"pericles.{name}")
    assert module.__name__ == f"pericles.{name}"
