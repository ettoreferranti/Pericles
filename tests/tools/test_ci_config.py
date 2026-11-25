from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]


def run_commands(workflow: str) -> str:
    data: dict[str, Any] = yaml.safe_load((ROOT / workflow).read_text(encoding="utf-8"))
    commands = [step.get("run", "") for job in data["jobs"].values() for step in job["steps"]]
    return "\n".join(commands)


@pytest.mark.req("REQ-NFR-005")
def test_ci_runs_every_quality_gate() -> None:
    """AC1: ruff, mypy --strict, pytest, traceability and viewer gates all run in CI."""
    commands = run_commands(".github/workflows/ci.yml")
    for gate in (
        "uv sync --locked",
        "ruff check",
        "ruff format --check",
        "mypy",
        "pytest",
        "pericles_tools.traceability check",
        "pericles_tools.adr check",
        "pnpm install --frozen-lockfile",
        "pnpm lint",
        "pnpm typecheck",
        "pnpm test",
        "pnpm build",
    ):
        assert gate in commands, gate


@pytest.mark.req("REQ-NFR-006")
def test_mutation_runs_incrementally_on_prs_and_fully_nightly() -> None:
    """AC2: changed modules on PRs; full run nightly (Python and viewer)."""
    assert "mutation_gate run --changed-since" in run_commands(".github/workflows/ci.yml")
    nightly = run_commands(".github/workflows/mutation-nightly.yml")
    assert "mutation_gate run" in nightly
    assert "--changed-since" not in nightly
    assert "pnpm mutation" in nightly


def test_mutation_runs_cap_mutmut_workers() -> None:
    """Both mutation runs cap mutmut's workers so they fit the runner's memory."""
    for workflow in (".github/workflows/ci.yml", ".github/workflows/mutation-nightly.yml"):
        assert "mutation_gate run" in run_commands(workflow)
        assert "--max-children 2" in run_commands(workflow)
