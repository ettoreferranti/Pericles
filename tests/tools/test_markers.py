from pathlib import Path

import pytest

from pericles_tools.markers import MarkerError, TestRef, scan_file, scan_tests

pytestmark = pytest.mark.req("REQ-NFR-007")


def write(root: Path, rel: str, text: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_function_decorator(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "tests/test_a.py",
        'import pytest\n\n@pytest.mark.req("REQ-SIM-001")\ndef test_x() -> None: ...\n',
    )
    assert scan_file(path, tmp_path) == [TestRef("REQ-SIM-001", "tests/test_a.py::test_x")]


def test_multiple_ids_in_one_marker_and_stacked_markers(tmp_path: Path) -> None:
    src = (
        "import pytest\n\n"
        '@pytest.mark.req("REQ-SIM-001", "REQ-SIM-002")\n'
        '@pytest.mark.req("REQ-ECO-001")\n'
        "@pytest.mark.slow\n"
        "def test_x() -> None: ...\n"
    )
    refs = scan_file(write(tmp_path, "tests/test_a.py", src), tmp_path)
    assert sorted(r.req_id for r in refs) == ["REQ-ECO-001", "REQ-SIM-001", "REQ-SIM-002"]


def test_module_level_pytestmark_single_and_list(tmp_path: Path) -> None:
    single = write(
        tmp_path, "tests/test_s.py", 'import pytest\npytestmark = pytest.mark.req("REQ-A-001")\n'
    )
    listed = write(
        tmp_path,
        "tests/test_l.py",
        'import pytest\npytestmark = [pytest.mark.slow, pytest.mark.req("REQ-B-001")]\n',
    )
    assert scan_file(single, tmp_path) == [TestRef("REQ-A-001", "tests/test_s.py")]
    assert scan_file(listed, tmp_path) == [TestRef("REQ-B-001", "tests/test_l.py")]


def test_class_decorator_and_methods(tmp_path: Path) -> None:
    src = (
        "import pytest\n\n"
        '@pytest.mark.req("REQ-A-001")\n'
        "class TestThing:\n"
        '    @pytest.mark.req("REQ-A-002")\n'
        "    def test_m(self) -> None: ...\n"
    )
    refs = scan_file(write(tmp_path, "tests/test_c.py", src), tmp_path)
    assert refs == [
        TestRef("REQ-A-001", "tests/test_c.py::TestThing"),
        TestRef("REQ-A-002", "tests/test_c.py::TestThing::test_m"),
    ]


def test_non_literal_argument_is_an_error(tmp_path: Path) -> None:
    src = 'import pytest\nID = "REQ-A-001"\n\n@pytest.mark.req(ID)\ndef test_x() -> None: ...\n'
    with pytest.raises(MarkerError, match=r"test_a\.py:4: .*string literals"):
        scan_file(write(tmp_path, "tests/test_a.py", src), tmp_path)


def test_marker_without_ids_is_an_error(tmp_path: Path) -> None:
    src = "import pytest\n\n@pytest.mark.req()\ndef test_x() -> None: ...\n"
    with pytest.raises(MarkerError, match="at least one requirement ID"):
        scan_file(write(tmp_path, "tests/test_a.py", src), tmp_path)


def test_scan_tests_finds_both_naming_styles_recursively(tmp_path: Path) -> None:
    mark = 'import pytest\n\n@pytest.mark.req("REQ-A-001")\ndef test_x() -> None: ...\n'
    write(tmp_path, "tests/sub/test_one.py", mark)
    write(tmp_path, "tests/two_test.py", mark)
    write(tmp_path, "tests/helpers.py", mark)
    nodeids = [r.nodeid for r in scan_tests(tmp_path / "tests", tmp_path)]
    assert nodeids == ["tests/sub/test_one.py::test_x", "tests/two_test.py::test_x"]
