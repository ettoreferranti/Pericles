from pathlib import Path

import pytest

from pericles_tools.markers import TestRef
from pericles_tools.requirements import Requirement
from pericles_tools.traceability import evaluate, main, render_matrix

pytestmark = pytest.mark.req("REQ-NFR-007")


def req(req_id: str, status: str = "Accepted", milestone: str = "M1") -> Requirement:
    return Requirement(
        id=req_id,
        title=f"Title of {req_id}",
        priority="Must",
        milestone=milestone,
        status=status,
        statement="",
        criteria=(("AC1", "x"),),
        source=Path("docs/requirements/x.md"),
        line=1,
    )


def catalog(*reqs: Requirement) -> dict[str, Requirement]:
    return {r.id: r for r in reqs}


OPEN = {"M0": False, "M1": False}


def test_covered_requirement_has_no_errors_or_gaps() -> None:
    report = evaluate(catalog(req("REQ-A-001")), OPEN, [TestRef("REQ-A-001", "t.py::test_a")])
    assert report.errors == ()
    assert report.gaps == ()
    assert report.coverage["REQ-A-001"] == ("t.py::test_a",)


def test_unknown_id_in_test_is_an_error() -> None:
    report = evaluate(catalog(req("REQ-A-001")), OPEN, [TestRef("REQ-A-999", "t.py::test_a")])
    assert any("REQ-A-999" in e and "unknown" in e for e in report.errors)


def test_withdrawn_requirement_referenced_is_an_error() -> None:
    reqs = catalog(req("REQ-A-001", status="Withdrawn"))
    report = evaluate(reqs, OPEN, [TestRef("REQ-A-001", "t.py::test_a")])
    assert any("Withdrawn" in e for e in report.errors)


def test_implemented_without_tests_is_an_error() -> None:
    report = evaluate(catalog(req("REQ-A-001", status="Implemented")), OPEN, [])
    assert any("REQ-A-001" in e and "Implemented" in e for e in report.errors)


def test_done_milestone_without_tests_is_an_error_but_withdrawn_is_exempt() -> None:
    reqs = catalog(req("REQ-A-001", milestone="M0"), req("REQ-A-002", "Withdrawn", "M0"))
    report = evaluate(reqs, {"M0": True, "M1": False}, [])
    assert len(report.errors) == 1
    assert "REQ-A-001" in report.errors[0] and "M0" in report.errors[0]


def test_accepted_without_tests_in_open_milestone_is_a_gap() -> None:
    report = evaluate(catalog(req("REQ-A-001")), OPEN, [])
    assert report.errors == ()
    assert report.gaps == ("REQ-A-001",)


def test_unknown_milestone_is_an_error() -> None:
    report = evaluate(catalog(req("REQ-A-001", milestone="M9")), OPEN, [])
    assert any("M9" in e for e in report.errors)


def test_matrix_lists_every_requirement_with_tests_or_dash() -> None:
    reqs = catalog(req("REQ-A-001"), req("REQ-A-002"))
    report = evaluate(reqs, OPEN, [TestRef("REQ-A-001", "t.py::test_a")])
    matrix = render_matrix(reqs, report)
    assert "| REQ-A-001 | Title of REQ-A-001 | M1 | Accepted | `t.py::test_a` |" in matrix
    assert "| REQ-A-002 | Title of REQ-A-002 | M1 | Accepted | — |" in matrix
    assert "Open gaps: 1" in matrix


def make_repo(root: Path, status: str, with_test: bool) -> None:
    (root / "docs/requirements").mkdir(parents=True)
    (root / "docs/requirements/nfr.md").write_text(
        f"### REQ-NFR-001: Thing\nMust · M0 · {status}\n- AC1: x\n", encoding="utf-8"
    )
    (root / "docs/requirements/milestones.md").write_text(
        "| M0 | Foundations | no |\n", encoding="utf-8"
    )
    (root / "tests").mkdir()
    if with_test:
        (root / "tests/test_x.py").write_text(
            'import pytest\n\n@pytest.mark.req("REQ-NFR-001")\ndef test_x() -> None: ...\n',
            encoding="utf-8",
        )


def test_cli_check_passes_and_fails(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good, bad = tmp_path / "good", tmp_path / "bad"
    make_repo(good, "Implemented", with_test=True)
    make_repo(bad, "Implemented", with_test=False)
    assert main(["check", "--root", str(good)]) == 0
    assert main(["check", "--root", str(bad)]) == 1
    assert "REQ-NFR-001" in capsys.readouterr().out


def test_cli_reports_malformed_catalog_as_failure(tmp_path: Path) -> None:
    make_repo(tmp_path, "Implemented", with_test=True)
    (tmp_path / "docs/requirements/nfr.md").write_text("### REQ-NFR-1: bad\n", encoding="utf-8")
    assert main(["check", "--root", str(tmp_path)]) == 1


def test_cli_matrix_writes_file(tmp_path: Path) -> None:
    make_repo(tmp_path, "Accepted", with_test=False)
    out = tmp_path / "matrix.md"
    assert main(["matrix", "--root", str(tmp_path), "--out", str(out)]) == 0
    assert "| REQ-NFR-001 |" in out.read_text(encoding="utf-8")
