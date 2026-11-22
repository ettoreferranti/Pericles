from pathlib import Path

import pytest

from pericles_tools.requirements import (
    RequirementsError,
    load_catalog,
    load_milestones,
    parse_file,
)

pytestmark = pytest.mark.req("REQ-NFR-007")

SAMPLE = """# SIM: Simulation

### REQ-SIM-001: Seeded map generation
Must · M1 · Accepted
The engine generates a map.
- AC1: Same seed, same map.
- AC2: Different seeds differ.

### REQ-SIM-002: Tick loop
Should · M1 · Implemented
- AC1: Deterministic.
"""

MILESTONES = """# Milestones

| Milestone | Title | Done |
|-----------|-------|------|
| M0 | Foundations | yes |
| M1 | Headless sim | no |
"""


def write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_parses_meta_statement_and_criteria(tmp_path: Path) -> None:
    reqs = parse_file(write(tmp_path, "sim.md", SAMPLE))
    assert [r.id for r in reqs] == ["REQ-SIM-001", "REQ-SIM-002"]
    first = reqs[0]
    assert first.title == "Seeded map generation"
    assert (first.priority, first.milestone, first.status) == ("Must", "M1", "Accepted")
    assert first.statement == "The engine generates a map."
    assert first.criteria == (("AC1", "Same seed, same map."), ("AC2", "Different seeds differ."))
    assert first.area == "SIM"
    assert first.line == 3
    assert reqs[1].statement == ""
    assert reqs[1].status == "Implemented"


def test_tolerates_crlf_and_trailing_whitespace(tmp_path: Path) -> None:
    reqs = parse_file(write(tmp_path, "sim.md", SAMPLE.replace("\n", "  \r\n")))
    assert reqs[0].title == "Seeded map generation"
    assert reqs[0].criteria[0] == ("AC1", "Same seed, same map.")
    assert reqs[0].status == "Accepted"


def test_malformed_meta_line_reports_file_and_line(tmp_path: Path) -> None:
    text = SAMPLE.replace("Must · M1 · Accepted", "Must - M1 - Accepted")
    with pytest.raises(RequirementsError, match=r"sim\.md:4:"):
        parse_file(write(tmp_path, "sim.md", text))


def test_malformed_heading_is_an_error(tmp_path: Path) -> None:
    text = SAMPLE.replace("### REQ-SIM-002: Tick loop", "### REQ-SIM-2: Tick loop")
    with pytest.raises(RequirementsError, match=r"sim\.md:9: malformed requirement heading"):
        parse_file(write(tmp_path, "sim.md", text))


def test_requirement_without_criteria_is_an_error(tmp_path: Path) -> None:
    text = "### REQ-SIM-001: X\nMust · M1 · Accepted\nJust a statement.\n"
    with pytest.raises(RequirementsError, match="no acceptance criteria"):
        parse_file(write(tmp_path, "sim.md", text))


def test_duplicate_criterion_is_an_error(tmp_path: Path) -> None:
    text = "### REQ-SIM-001: X\nMust · M1 · Accepted\n- AC1: a\n- AC1: b\n"
    with pytest.raises(RequirementsError, match="duplicate AC1"):
        parse_file(write(tmp_path, "sim.md", text))


def test_catalog_rejects_duplicate_ids_across_files(tmp_path: Path) -> None:
    write(tmp_path, "sim.md", SAMPLE)
    write(tmp_path, "eco.md", "### REQ-SIM-001: Again\nMust · M3 · Accepted\n- AC1: x\n")
    with pytest.raises(RequirementsError, match=r"duplicate REQ-SIM-001.*eco\.md.*sim\.md"):
        load_catalog(tmp_path)


def test_catalog_skips_index_milestones_and_matrix(tmp_path: Path) -> None:
    write(tmp_path, "sim.md", SAMPLE)
    write(tmp_path, "README.md", "### REQ-BAD-1: not a requirement\n")
    write(tmp_path, "milestones.md", MILESTONES)
    write(tmp_path, "traceability.md", "### REQ-BAD-1: generated\n")
    assert sorted(load_catalog(tmp_path)) == ["REQ-SIM-001", "REQ-SIM-002"]


def test_load_milestones(tmp_path: Path) -> None:
    assert load_milestones(write(tmp_path, "milestones.md", MILESTONES)) == {
        "M0": True,
        "M1": False,
    }


def test_malformed_milestone_row_is_an_error(tmp_path: Path) -> None:
    text = MILESTONES.replace("| M1 | Headless sim | no |", "| M1 | Headless sim | maybe |")
    with pytest.raises(RequirementsError, match=r"milestones\.md:6:"):
        load_milestones(write(tmp_path, "milestones.md", text))
