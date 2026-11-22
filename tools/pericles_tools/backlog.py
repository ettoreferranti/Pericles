"""Sync GitHub labels, milestones and one issue per requirement (dry run by default)."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pericles_tools.requirements import Requirement, load_catalog

MILESTONES: dict[str, str] = {
    "M0": "M0 Foundations",
    "M1": "M1 Headless sim",
    "M2": "M2 LLM minds",
    "M3": "M3 Society",
    "M4": "M4 Experiments",
    "M5": "M5 Viewer",
}
LABEL_COLORS = {"type": "5319e7", "area": "1d76db", "priority": "fbca04"}

Gh = Callable[[Sequence[str]], str]


@dataclass(frozen=True)
class IssueSpec:
    title: str
    body: str
    labels: tuple[str, ...]
    milestone: str


def _labels(req: Requirement) -> tuple[str, ...]:
    return ("type:requirement", f"area:{req.area.lower()}", f"priority:{req.priority.lower()}")


def issue_spec(req: Requirement) -> IssueSpec:
    criteria = "\n".join(f"- [ ] {ac}: {text}" for ac, text in req.criteria)
    statement = f"{req.statement}\n\n" if req.statement else ""
    body = (
        f"**Requirement:** {req.id}: {req.title}\n"
        f"**Priority:** {req.priority} · **Milestone:** {req.milestone} · "
        f"**Source:** `{req.source.as_posix()}`\n\n"
        f"{statement}### Acceptance criteria\n\n{criteria}\n\n"
        "Tests must reference this requirement with "
        f'`@pytest.mark.req("{req.id}")`.\n'
    )
    return IssueSpec(f"{req.id}: {req.title}", body, _labels(req), MILESTONES[req.milestone])


def label_commands(reqs: Iterable[Requirement]) -> list[list[str]]:
    names = sorted({label for req in reqs for label in _labels(req)})
    return [
        ["label", "create", name, "--color", LABEL_COLORS[name.split(":")[0]], "--force"]
        for name in names
    ]


def plan_sync(
    reqs: Mapping[str, Requirement],
    existing_titles: Iterable[str],
    existing_milestones: Iterable[str],
) -> list[list[str]]:
    active = [reqs[k] for k in sorted(reqs) if reqs[k].status != "Withdrawn"]
    existing_ids = {title.split(":", 1)[0].strip() for title in existing_titles}
    have_milestones = set(existing_milestones)
    commands = label_commands(active)
    for key in sorted({req.milestone for req in active}):
        title = MILESTONES[key]
        if title not in have_milestones:
            commands.append(["api", "repos/{owner}/{repo}/milestones", "-f", f"title={title}"])
    for req in active:
        if req.id in existing_ids:
            continue
        spec = issue_spec(req)
        command = ["issue", "create", "--title", spec.title, "--body", spec.body]
        for label in spec.labels:
            command += ["--label", label]
        commands.append([*command, "--milestone", spec.milestone])
    return commands


def sync(gh: Gh, reqs: Mapping[str, Requirement], apply: bool) -> list[list[str]]:
    titles = gh(
        [
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            "1000",
            "--json",
            "title",
            "--jq",
            ".[].title",
        ]
    ).splitlines()
    milestones = gh(
        ["api", "repos/{owner}/{repo}/milestones?state=all", "--paginate", "--jq", ".[].title"]
    ).splitlines()
    commands = plan_sync(reqs, titles, milestones)
    if apply:
        for command in commands:
            gh(command)
    return commands


def _gh(args: Sequence[str]) -> str:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=True).stdout


def main(argv: Sequence[str] | None = None, gh: Gh = _gh) -> int:
    parser = argparse.ArgumentParser(prog="pericles_tools.backlog")
    parser.add_argument("--apply", action="store_true", help="create on GitHub (default: dry run)")
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    reqs = load_catalog(args.root / "docs/requirements")
    commands = sync(gh, reqs, apply=args.apply)
    issues = sum(c[:2] == ["issue", "create"] for c in commands)
    milestones = sum(c[0] == "api" for c in commands)
    mode = "applied" if args.apply else "dry run"
    print(f"{mode}: {issues} issue(s), {milestones} milestone(s), labels refreshed")
    if not args.apply:
        for command in commands:
            if command[:2] == ["issue", "create"]:
                print(f"  would create: {command[3]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
