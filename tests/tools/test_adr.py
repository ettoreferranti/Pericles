from pathlib import Path

import pytest

from pericles_tools.adr import check_adrs, main

pytestmark = pytest.mark.req("REQ-NFR-008")

ROOT = Path(__file__).resolve().parents[2]


def adr_text(number: str, title: str = "Title") -> str:
    return (
        f"# ADR-{number}: {title}\n\n- **Status:** Accepted\n- **Date:** 2026-11-22\n\n"
        "## Context\n\nc\n\n## Decision\n\nd\n\n## Consequences\n\nq\n"
    )


def make(tmp_path: Path, numbers: list[str], index: list[str] | None = None) -> Path:
    for n in numbers:
        (tmp_path / f"{n}-some-title.md").write_text(adr_text(n), encoding="utf-8")
    linked = numbers if index is None else index
    rows = "\n".join(f"| [{n}]({n}-some-title.md) | Title | Accepted |" for n in linked)
    (tmp_path / "README.md").write_text(f"# ADRs\n\n{rows}\n", encoding="utf-8")
    return tmp_path


def test_valid_set_passes(tmp_path: Path) -> None:
    assert check_adrs(make(tmp_path, ["0001", "0002"])) == []


def test_missing_index_entry_fails(tmp_path: Path) -> None:
    errors = check_adrs(make(tmp_path, ["0001", "0002"], index=["0001"]))
    assert errors == ["README.md: index does not link 0002-some-title.md"]


def test_numbering_gap_fails(tmp_path: Path) -> None:
    errors = check_adrs(make(tmp_path, ["0001", "0003"]))
    assert any("contiguous" in e for e in errors)


def test_heading_must_match_file_number(tmp_path: Path) -> None:
    make(tmp_path, ["0001"])
    (tmp_path / "0001-some-title.md").write_text(adr_text("0002"), encoding="utf-8")
    assert any("# ADR-0001: " in e for e in check_adrs(tmp_path))


@pytest.mark.parametrize("missing", ["## Context", "## Decision", "## Consequences", "**Status:**"])
def test_required_parts(tmp_path: Path, missing: str) -> None:
    make(tmp_path, ["0001"])
    path = tmp_path / "0001-some-title.md"
    path.write_text(path.read_text(encoding="utf-8").replace(missing, "## Other"), encoding="utf-8")
    assert check_adrs(tmp_path) != []


def test_bad_file_name_fails(tmp_path: Path) -> None:
    make(tmp_path, ["0001"])
    (tmp_path / "Decision About X.md").write_text(adr_text("0002"), encoding="utf-8")
    assert any("NNNN-kebab-title.md" in e for e in check_adrs(tmp_path))


def test_repository_adrs_pass() -> None:
    """AC1: the real ADR set is well-formed and fully indexed."""
    assert check_adrs(ROOT / "docs/adr") == []
    assert main(["check", "--root", str(ROOT)]) == 0


def test_index_link_to_deleted_adr_fails(tmp_path: Path) -> None:
    make(tmp_path, ["0001", "0002"])
    (tmp_path / "0002-some-title.md").unlink()
    assert check_adrs(tmp_path) == ["README.md: index links missing file 0002-some-title.md"]
