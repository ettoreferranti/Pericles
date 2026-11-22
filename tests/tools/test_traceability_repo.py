from pathlib import Path

import pytest

from pericles_tools.markers import scan_tests
from pericles_tools.requirements import load_catalog, load_milestones
from pericles_tools.traceability import evaluate

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("REQ-NFR-007")
def test_repository_catalog_and_tests_are_consistent() -> None:
    """AC1/AC2: the real catalog parses and satisfies the traceability rules."""
    reqs = load_catalog(ROOT / "docs/requirements")
    milestones = load_milestones(ROOT / "docs/requirements/milestones.md")
    report = evaluate(reqs, milestones, scan_tests(ROOT / "tests", ROOT))
    assert report.errors == ()
    assert len(reqs) >= 89
