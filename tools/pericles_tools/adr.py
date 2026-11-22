"""Check ADR files for structure, numbering and index completeness (REQ-NFR-008)."""

from __future__ import annotations

import argparse
import re
from collections.abc import Sequence
from pathlib import Path

ADR_FILE = re.compile(r"^(\d{4})-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
INDEX_LINK = re.compile(r"\]\((\d{4}-[^)]+\.md)\)")
SECTIONS = ("Context", "Decision", "Consequences")


def check_adrs(adr_dir: Path) -> list[str]:
    errors: list[str] = []
    files = sorted(p for p in adr_dir.glob("*.md") if p.name != "README.md")
    numbers: list[int] = []
    for path in files:
        match = ADR_FILE.match(path.name)
        if match is None:
            errors.append(f"{path.name}: file name must be NNNN-kebab-title.md")
            continue
        number = match.group(1)
        numbers.append(int(number))
        text = path.read_text(encoding="utf-8")
        first = text.splitlines()[0] if text else ""
        if not first.startswith(f"# ADR-{number}: "):
            errors.append(f"{path.name}: first line must be '# ADR-{number}: <title>'")
        if not re.search(r"^- \*\*Status:\*\* \S", text, re.MULTILINE):
            errors.append(f"{path.name}: missing '- **Status:** ...' line")
        for section in SECTIONS:
            if not re.search(rf"^## {section}\s*$", text, re.MULTILINE):
                errors.append(f"{path.name}: missing '## {section}' section")
    if sorted(numbers) != list(range(1, len(numbers) + 1)):
        found = ", ".join(f"{n:04d}" for n in sorted(numbers))
        errors.append(f"ADR numbers must be contiguous from 0001 (ADRs are never deleted): {found}")
    index = adr_dir / "README.md"
    if not index.exists():
        errors.append("README.md: ADR index is missing")
    else:
        index_text = index.read_text(encoding="utf-8")
        for path in files:
            if f"]({path.name})" not in index_text:
                errors.append(f"README.md: index does not link {path.name}")
        names = {path.name for path in files}
        for target in INDEX_LINK.findall(index_text):
            if target not in names:
                errors.append(f"README.md: index links missing file {target}")
    return errors


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pericles_tools.adr")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("check")
    check.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    errors = check_adrs(args.root / "docs/adr")
    for error in errors:
        print(f"error: {error}")
    print("ADRs OK" if not errors else f"{len(errors)} ADR error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
