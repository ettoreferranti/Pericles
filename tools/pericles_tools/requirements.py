"""Parse the requirements catalog in docs/requirements/ (see its README for the format)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

HEADING = re.compile(r"^### (REQ-[A-Z]+-\d{3}): (.+?)\s*$")
META = re.compile(r"^(Must|Should|Could) · (M\d+) · (Proposed|Accepted|Implemented|Withdrawn)\s*$")
CRITERION = re.compile(r"^- (AC\d+): (.+?)\s*$")
NEAR_HEADING = re.compile(r"^\s*#+\s*REQ-")
NEAR_CRITERION = re.compile(r"^\s*[-*+]\s*AC\d")
ANY_HEADING = re.compile(r"^\s*#")
MILESTONE_ROW = re.compile(r"^\|\s*(M\d+)\s*\|\s*(.+?)\s*\|\s*(yes|no)\s*\|\s*$")
SKIP_FILES = frozenset({"README.md", "milestones.md", "traceability.md"})


class RequirementsError(Exception):
    """The requirements catalog is malformed."""


@dataclass(frozen=True)
class Requirement:
    id: str
    title: str
    priority: str
    milestone: str
    status: str
    statement: str
    criteria: tuple[tuple[str, str], ...]
    source: Path
    line: int

    @property
    def area(self) -> str:
        return self.id.split("-")[1]


def parse_file(path: Path) -> list[Requirement]:
    lines = path.read_text(encoding="utf-8").splitlines()
    reqs: list[Requirement] = []
    i = 0
    while i < len(lines):
        heading = HEADING.match(lines[i])
        if heading is None:
            if NEAR_HEADING.match(lines[i]):
                raise RequirementsError(
                    f"{path}:{i + 1}: malformed requirement heading: {lines[i].strip()!r}"
                )
            i += 1
            continue
        req_id, title = heading.group(1), heading.group(2)
        start = i + 1
        meta = META.match(lines[i + 1]) if i + 1 < len(lines) else None
        if meta is None:
            raise RequirementsError(
                f"{path}:{i + 2}: expected 'Priority · Milestone · Status' after {req_id}"
            )
        i += 2
        statement: list[str] = []
        criteria: list[tuple[str, str]] = []
        while i < len(lines) and not ANY_HEADING.match(lines[i]):
            criterion = CRITERION.match(lines[i])
            if criterion is not None:
                ac_id = criterion.group(1)
                if any(existing == ac_id for existing, _ in criteria):
                    raise RequirementsError(f"{path}:{i + 1}: duplicate {ac_id} in {req_id}")
                criteria.append((ac_id, criterion.group(2)))
            elif NEAR_CRITERION.match(lines[i]):
                raise RequirementsError(
                    f"{path}:{i + 1}: malformed acceptance criterion in {req_id}: "
                    f"{lines[i].strip()!r} (expected '- ACn: text')"
                )
            elif lines[i].strip() and not criteria:
                statement.append(lines[i].strip())
            i += 1
        if not criteria:
            raise RequirementsError(f"{path}:{start}: {req_id} has no acceptance criteria")
        reqs.append(
            Requirement(
                id=req_id,
                title=title,
                priority=meta.group(1),
                milestone=meta.group(2),
                status=meta.group(3),
                statement=" ".join(statement),
                criteria=tuple(criteria),
                source=path,
                line=start,
            )
        )
    return reqs


def load_catalog(directory: Path) -> dict[str, Requirement]:
    catalog: dict[str, Requirement] = {}
    for path in sorted(directory.glob("*.md")):
        if path.name in SKIP_FILES:
            continue
        for req in parse_file(path):
            if req.id in catalog:
                other = catalog[req.id]
                raise RequirementsError(
                    f"duplicate {req.id}: {other.source}:{other.line} and {req.source}:{req.line}"
                )
            catalog[req.id] = req
    return catalog


def load_milestones(path: Path) -> dict[str, bool]:
    milestones: dict[str, bool] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not re.match(r"^\|\s*M\d", line):
            continue
        row = MILESTONE_ROW.match(line)
        if row is None:
            raise RequirementsError(
                f"{path}:{number}: expected '| M<n> | <title> | yes|no |', got {line.strip()!r}"
            )
        milestones[row.group(1)] = row.group(3) == "yes"
    return milestones
