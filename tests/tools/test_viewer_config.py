import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("REQ-NFR-006")
def test_stryker_breaks_below_70_and_excludes_tests() -> None:
    """AC1/AC2: Stryker is configured for the viewer with a break threshold of 70."""
    config = json.loads((ROOT / "viewer/stryker.config.json").read_text(encoding="utf-8"))
    assert config["thresholds"]["break"] == 70
    assert "!src/**/*.test.ts" in config["mutate"]


@pytest.mark.req("REQ-NFR-005")
def test_viewer_exposes_gate_scripts() -> None:
    """AC1: the viewer has lint, typecheck and test scripts for CI."""
    scripts = json.loads((ROOT / "viewer/package.json").read_text(encoding="utf-8"))["scripts"]
    assert {"lint", "typecheck", "test", "build", "mutation"} <= scripts.keys()
