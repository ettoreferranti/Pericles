import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from pericles_tools.mutation_gate import (
    THRESHOLDS,
    Score,
    failures,
    has_mutable_code,
    main,
    module_globs,
    package_of,
    parse_results,
    scores,
)

pytestmark = pytest.mark.req("REQ-NFR-006")

RESULTS = """
    pericles.core.world.x_step__mutmut_1: killed
    pericles.core.world.xǁWorldǁtick__mutmut_2: survived
    pericles.core.world.x_step__mutmut_3: timeout
    pericles.core.world.x_step__mutmut_4: not checked
    pericles.llm.gateway.x_call__mutmut_1: no tests
    pericles.llm.gateway.x_call__mutmut_2: killed
    pericles.experiment.run.x_go__mutmut_1: survived
"""


def test_thresholds_match_the_requirement() -> None:
    """AC2: core ≥ 80%, agents and llm ≥ 70%."""
    assert THRESHOLDS == {"pericles.core": 0.80, "pericles.agents": 0.70, "pericles.llm": 0.70}


def test_parse_results_and_package_of() -> None:
    results = parse_results(RESULTS)
    assert results["pericles.core.world.xǁWorldǁtick__mutmut_2"] == "survived"
    assert results["pericles.llm.gateway.x_call__mutmut_1"] == "no tests"
    assert package_of("pericles.core.world.xǁWorldǁtick__mutmut_2") == "pericles.core"


def test_scores_count_statuses_and_ignore_unchecked() -> None:
    result = scores(parse_results(RESULTS), THRESHOLDS)
    assert result["pericles.core"] == Score(killed=2, survived=1)
    assert result["pericles.llm"] == Score(killed=1, survived=1)
    assert result["pericles.agents"] == Score(killed=0, survived=0)
    assert "pericles.experiment" not in result


def test_score_ratio() -> None:
    assert Score(killed=3, survived=1).ratio == 0.75
    assert Score(killed=0, survived=0).ratio == 1.0


def test_failures_only_for_packages_below_threshold_with_mutants() -> None:
    result = {
        "pericles.core": Score(killed=79, survived=21),
        "pericles.llm": Score(killed=7, survived=3),
        "pericles.agents": Score(killed=0, survived=0),
    }
    messages = failures(result, THRESHOLDS)
    assert len(messages) == 1
    assert "pericles.core" in messages[0] and "79.0%" in messages[0]


def test_exact_threshold_passes() -> None:
    assert failures({"pericles.core": Score(killed=80, survived=20)}, THRESHOLDS) == []


def test_module_globs_from_changed_files() -> None:
    changed = [
        "src/pericles/core/world.py",
        "src/pericles/agents/__init__.py",
        "src/pericles/experiment/run.py",
        "tests/pericles/test_world.py",
        "src/pericles/core/content.yaml",
    ]
    assert module_globs(changed) == ["pericles.core.world.*", "pericles.agents.x*"]


def test_has_mutable_code(tmp_path: Path) -> None:
    empty = tmp_path / "a.py"
    empty.write_text('"""Docstring only."""\n__version__ = "1"\n', encoding="utf-8")
    code = tmp_path / "b.py"
    code.write_text("def f() -> int:\n    return 1\n", encoding="utf-8")
    assert has_mutable_code([empty]) is False
    assert has_mutable_code([empty, code]) is True


class FakeRunner:
    def __init__(self, results: str, run_code: int = 0, diff: str = "") -> None:
        self.results, self.run_code, self.diff = results, run_code, diff
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(list(args))
        if args[:2] == ["git", "diff"]:
            return subprocess.CompletedProcess(list(args), 0, self.diff, "")
        if args[:2] == ["mutmut", "run"]:
            return subprocess.CompletedProcess(list(args), self.run_code, "", "")
        return subprocess.CompletedProcess(list(args), 0, self.results, "")


def make_src(root: Path, with_code: bool) -> None:
    pkg = root / "src/pericles/core"
    pkg.mkdir(parents=True)
    body = "def f() -> int:\n    return 1\n" if with_code else '"""Empty."""\n'
    (pkg / "world.py").write_text(body, encoding="utf-8")


def test_main_skips_when_nothing_to_mutate(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=False)
    runner = FakeRunner(results="")
    assert main(["run"], runner=runner, root=tmp_path) == 0
    assert not any(call[0] == "mutmut" for call in runner.calls)


def test_main_fails_when_mutmut_produces_no_results_for_real_code(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=True)
    assert main(["run"], runner=FakeRunner(results="", run_code=1), root=tmp_path) == 1


def test_main_fails_below_threshold_and_passes_above(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=True)
    low = "    pericles.core.world.x_f__mutmut_1: survived\n"
    high = "    pericles.core.world.x_f__mutmut_1: killed\n"
    assert main(["run"], runner=FakeRunner(results=low), root=tmp_path) == 1
    assert main(["run"], runner=FakeRunner(results=high), root=tmp_path) == 0


def test_main_changed_since_runs_only_changed_modules(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=True)
    runner = FakeRunner(
        results="    pericles.core.world.x_f__mutmut_1: killed\n",
        diff="src/pericles/core/world.py\nREADME.md\n",
    )
    assert main(["run", "--changed-since", "origin/main"], runner=runner, root=tmp_path) == 0
    assert ["git", "diff", "--name-only", "origin/main...HEAD"] in runner.calls
    assert ["mutmut", "run", "pericles.core.world.*"] in runner.calls


def test_main_changed_since_with_no_relevant_changes_passes(tmp_path: Path) -> None:
    make_src(tmp_path, with_code=True)
    runner = FakeRunner(results="", diff="README.md\n")
    assert main(["run", "--changed-since", "origin/main"], runner=runner, root=tmp_path) == 0
    assert not any(call[0] == "mutmut" for call in runner.calls)
