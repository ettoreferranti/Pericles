import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("REQ-NFR-002")
def test_python_floor_is_3_12() -> None:
    """AC1: the declared Python floor is 3.12."""
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert pyproject["project"]["requires-python"] == ">=3.12"
