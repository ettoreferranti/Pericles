"""Run mutmut and enforce per-package mutation-score thresholds (REQ-NFR-006, ADR-0008)."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

THRESHOLDS: dict[str, float] = {
    "pericles.core": 0.80,
    "pericles.agents": 0.70,
    "pericles.llm": 0.70,
}
KILLED = frozenset({"killed", "timeout", "segfault"})
SURVIVED = frozenset({"survived", "no tests", "suspicious"})
NO_TESTS_FOUND = "could not find any test case for any mutant"
RESULT_LINE = re.compile(r"^\s*(\S+__mutmut_\d+): (.+?)\s*$")

Runner = Callable[[Sequence[str]], "subprocess.CompletedProcess[str]"]


@dataclass(frozen=True)
class Score:
    killed: int
    survived: int

    @property
    def total(self) -> int:
        return self.killed + self.survived

    @property
    def ratio(self) -> float:
        return 1.0 if self.total == 0 else self.killed / self.total


def parse_results(text: str) -> dict[str, str]:
    results: dict[str, str] = {}
    for line in text.splitlines():
        match = RESULT_LINE.match(line)
        if match is not None:
            results[match.group(1)] = match.group(2)
    return results


def package_of(mutant: str) -> str:
    return ".".join(mutant.split(".")[:2])


def scores(results: Mapping[str, str], packages: Iterable[str]) -> dict[str, Score]:
    counts = {pkg: [0, 0] for pkg in packages}
    for mutant, status in results.items():
        pkg = package_of(mutant)
        if pkg not in counts:
            continue
        if status in KILLED:
            counts[pkg][0] += 1
        elif status in SURVIVED:
            counts[pkg][1] += 1
    return {pkg: Score(killed=k, survived=s) for pkg, (k, s) in counts.items()}


def failures(result: Mapping[str, Score], thresholds: Mapping[str, float]) -> list[str]:
    messages: list[str] = []
    for pkg in sorted(result):
        score = result[pkg]
        if score.total and score.ratio < thresholds[pkg]:
            messages.append(
                f"{pkg}: mutation score {score.ratio:.1%} below {thresholds[pkg]:.0%} "
                f"({score.killed} killed, {score.survived} survived)"
            )
    return messages


def module_globs(changed_files: Iterable[str]) -> list[str]:
    globs: list[str] = []
    for name in changed_files:
        if not (name.startswith("src/pericles/") and name.endswith(".py")):
            continue
        module = name.removeprefix("src/").removesuffix(".py").replace("/", ".")
        if package_of(module) not in THRESHOLDS:
            continue
        if module.endswith(".__init__"):
            globs.append(module.removesuffix(".__init__") + ".x*")
        else:
            globs.append(module + ".*")
    return globs


def has_mutable_code(files: Iterable[Path]) -> bool:
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) for n in ast.walk(tree)):
            return True
    return False


def _is_mutation_tested(name: str) -> bool:
    if not (name.startswith("src/pericles/") and name.endswith(".py")):
        return False
    module = name.removeprefix("src/").removesuffix(".py").replace("/", ".")
    return package_of(module) in THRESHOLDS


def _run(args: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), capture_output=True, text=True, check=False)


def _package_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for pkg in THRESHOLDS:
        files += sorted((root / "src" / Path(*pkg.split("."))).rglob("*.py"))
    return files


def main(argv: Sequence[str] | None = None, runner: Runner = _run, root: Path = Path(".")) -> int:
    parser = argparse.ArgumentParser(prog="pericles_tools.mutation_gate")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--changed-since", default=None, help="git ref; mutate only changed modules")
    run.add_argument("--max-children", type=int, default=None, help="cap mutmut's parallel workers")
    args = parser.parse_args(argv)

    globs: list[str] = []
    targets = _package_files(root)
    if args.changed_since is not None:
        diff = runner(["git", "diff", "--name-only", f"{args.changed_since}...HEAD"])
        if diff.returncode != 0:
            print(f"mutation gate: git diff against {args.changed_since} failed: {diff.stderr}")
            return 1
        changed = diff.stdout.split()
        globs = module_globs(changed)
        if not globs:
            print("mutation gate: no mutation-tested modules changed")
            return 0
        targets = [root / n for n in changed if _is_mutation_tested(n)]
    if not has_mutable_code(p for p in targets if p.exists()):
        print("mutation gate: no functions to mutate yet")
        return 0

    workers = [] if args.max_children is None else ["--max-children", str(args.max_children)]
    run_proc = runner(["mutmut", "run", *workers, *globs])
    results = parse_results(runner(["mutmut", "results", "--all", "true"]).stdout)
    in_scope = {
        name: status
        for name, status in results.items()
        if package_of(name) in THRESHOLDS
        and (not globs or any(fnmatchcase(name, glob) for glob in globs))
    }
    if not in_scope:
        if run_proc.returncode == 0 or NO_TESTS_FOUND in run_proc.stdout:
            print("mutation gate: mutmut generated no mutants for the selected code")
            return 0
        print(f"mutation gate: mutmut produced no results (exit {run_proc.returncode})")
        print(run_proc.stdout[-2000:], run_proc.stderr[-2000:])
        return 1
    unchecked = sorted(n for n, st in in_scope.items() if st not in KILLED | SURVIVED)
    if unchecked:
        print(f"mutation gate: {len(unchecked)} mutant(s) not checked (exit {run_proc.returncode})")
        print("\n".join(f"  {n}: {in_scope[n]}" for n in unchecked[:20]))
        return 1
    result = scores(in_scope, THRESHOLDS)
    for pkg in sorted(result):
        score = result[pkg]
        if score.total:
            need = THRESHOLDS[pkg]
            print(f"{pkg}: {score.ratio:.1%} ({score.killed}/{score.total}), need {need:.0%}")
    messages = failures(result, THRESHOLDS)
    for message in messages:
        print(f"error: {message}")
    return 1 if messages else 0


if __name__ == "__main__":
    raise SystemExit(main())
