from collections.abc import Sequence
from pathlib import Path

import pytest

from pericles_tools.backlog import (
    MILESTONES,
    issue_spec,
    label_commands,
    main,
    plan_sync,
    sync,
)
from pericles_tools.requirements import Requirement


def req(req_id: str, status: str = "Accepted", milestone: str = "M1") -> Requirement:
    return Requirement(
        id=req_id,
        title="Seeded map generation",
        priority="Must",
        milestone=milestone,
        status=status,
        statement="The engine generates a map.",
        criteria=(("AC1", "Same seed, same map."), ("AC2", "Different seeds differ.")),
        source=Path("docs/requirements/sim.md"),
        line=3,
    )


def test_issue_spec_contents() -> None:
    spec = issue_spec(req("REQ-SIM-001"))
    assert spec.title == "REQ-SIM-001: Seeded map generation"
    assert spec.labels == ("type:requirement", "area:sim", "priority:must")
    assert spec.milestone == "M1 Headless sim"
    assert "- [ ] AC1: Same seed, same map." in spec.body
    assert "docs/requirements/sim.md" in spec.body
    assert "The engine generates a map." in spec.body


def test_milestone_titles_cover_m0_to_m5() -> None:
    assert sorted(MILESTONES) == ["M0", "M1", "M2", "M3", "M4", "M5"]


def test_label_commands_are_idempotent_force_creates() -> None:
    commands = label_commands([req("REQ-SIM-001"), req("REQ-ECO-001")])
    names = [c[2] for c in commands]
    assert names == ["area:eco", "area:sim", "priority:must", "type:requirement"]
    assert all(c[:2] == ["label", "create"] and "--force" in c for c in commands)


def test_plan_creates_missing_milestones_and_issues_only() -> None:
    reqs = {
        r.id: r for r in [req("REQ-SIM-001"), req("REQ-SIM-002"), req("REQ-SIM-003", "Withdrawn")]
    }
    commands = plan_sync(
        reqs,
        existing_titles=["REQ-SIM-001: an older title"],
        existing_milestones=["M1 Headless sim"],
    )
    issue_cmds = [c for c in commands if c[:2] == ["issue", "create"]]
    milestone_cmds = [c for c in commands if c[0] == "api"]
    assert len(issue_cmds) == 1
    assert "REQ-SIM-002: Seeded map generation" in issue_cmds[0]
    assert milestone_cmds == []


def test_plan_creates_milestone_before_issues() -> None:
    commands = plan_sync({"REQ-SIM-001": req("REQ-SIM-001")}, [], [])
    kinds = [c[0] for c in commands if c[0] in ("api", "issue")]
    assert kinds == ["api", "issue"]
    assert "title=M1 Headless sim" in commands[[c[0] for c in commands].index("api")]


class FakeGh:
    def __init__(self) -> None:
        self.titles: list[str] = []
        self.milestones: list[str] = []
        self.calls: list[list[str]] = []

    def __call__(self, args: Sequence[str]) -> str:
        args = list(args)
        self.calls.append(args)
        if args[:2] == ["issue", "list"]:
            return "\n".join(self.titles)
        if args[0] == "api" and "--jq" in args:
            return "\n".join(self.milestones)
        if args[:2] == ["issue", "create"]:
            self.titles.append(args[args.index("--title") + 1])
        if args[0] == "api" and "-f" in args:
            self.milestones.append(args[args.index("-f") + 1].removeprefix("title="))
        return ""


def test_sync_is_idempotent() -> None:
    gh = FakeGh()
    reqs = {r.id: r for r in [req("REQ-SIM-001"), req("REQ-SIM-002", milestone="M2")]}
    first = sync(gh, reqs, apply=True)
    assert sum(c[:2] == ["issue", "create"] for c in first) == 2
    second = sync(gh, reqs, apply=True)
    assert not any(c[:2] == ["issue", "create"] or c[0] == "api" for c in second)


def test_dry_run_does_not_create(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    (tmp_path / "docs/requirements").mkdir(parents=True)
    (tmp_path / "docs/requirements/sim.md").write_text(
        "### REQ-SIM-001: X\nMust · M1 · Accepted\n- AC1: y\n", encoding="utf-8"
    )
    gh = FakeGh()
    assert main(["--root", str(tmp_path)], gh=gh) == 0
    assert not any(c[:2] in (["issue", "create"], ["label", "create"]) for c in gh.calls)
    assert "dry run" in capsys.readouterr().out
