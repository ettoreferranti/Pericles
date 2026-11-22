"""Find @pytest.mark.req(...) links from tests to requirements by static AST analysis."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


class MarkerError(Exception):
    """A req marker is written in a form the traceability check cannot read."""


@dataclass(frozen=True, order=True)
class TestRef:
    __test__ = False  # not a pytest test class

    req_id: str
    nodeid: str


def _is_req(node: ast.expr) -> bool:
    """True for `pytest.mark.req` and `mark.req` (from `from pytest import mark`)."""
    if not (isinstance(node, ast.Attribute) and node.attr == "req"):
        return False
    owner = node.value
    if isinstance(owner, ast.Name):
        return owner.id == "mark"
    return (
        isinstance(owner, ast.Attribute)
        and owner.attr == "mark"
        and isinstance(owner.value, ast.Name)
        and owner.value.id == "pytest"
    )


class _Scanner:
    def __init__(self, path: Path, rel: str) -> None:
        self.path = path
        self.rel = rel
        self.accepted: set[int] = set()
        self.refs: list[TestRef] = []

    def _read(self, node: ast.expr, nodeid: str) -> None:
        if not (isinstance(node, ast.Call) and _is_req(node.func)):
            return
        ids: list[str] = []
        for arg in node.args:
            if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
                raise MarkerError(
                    f"{self.path}:{arg.lineno}: req marker arguments must be string literals"
                )
            ids.append(arg.value)
        if not ids:
            raise MarkerError(
                f"{self.path}:{node.lineno}: req marker needs at least one requirement ID"
            )
        self.accepted.add(id(node))
        self.refs += [TestRef(req_id, nodeid) for req_id in ids]

    def _pytestmark(self, stmt: ast.stmt, nodeid: str) -> None:
        if isinstance(stmt, ast.Assign):
            is_mark = any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets)
            value: ast.expr | None = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            is_mark = isinstance(stmt.target, ast.Name) and stmt.target.id == "pytestmark"
            value = stmt.value
        else:
            return
        if not is_mark or value is None:
            return
        values = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
        for item in values:
            self._read(item, nodeid)

    def scan_body(self, body: list[ast.stmt], prefix: str) -> None:
        for stmt in body:
            self._pytestmark(stmt, prefix)
            if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
                for decorator in stmt.decorator_list:
                    self._read(decorator, f"{prefix}::{stmt.name}")
            elif isinstance(stmt, ast.ClassDef):
                nodeid = f"{prefix}::{stmt.name}"
                for decorator in stmt.decorator_list:
                    self._read(decorator, nodeid)
                self.scan_body(stmt.body, nodeid)

    def reject_unread(self, tree: ast.Module) -> None:
        """Every req marker must be one this scanner read; anything else is an error."""
        called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_req(node.func) and id(node) not in self.accepted:
                raise MarkerError(
                    f"{self.path}:{node.lineno}: req marker in an unsupported position; "
                    "use a decorator or a pytestmark assignment"
                )
            if isinstance(node, ast.Attribute) and _is_req(node) and id(node) not in called:
                raise MarkerError(
                    f"{self.path}:{node.lineno}: req marker must be called with requirement IDs"
                )


def scan_file(path: Path, root: Path) -> list[TestRef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    scanner = _Scanner(path, path.relative_to(root).as_posix())
    scanner.scan_body(tree.body, scanner.rel)
    scanner.reject_unread(tree)
    return scanner.refs


def scan_tests(test_dir: Path, root: Path) -> list[TestRef]:
    files = sorted(
        p
        for p in test_dir.rglob("*.py")
        if p.name.startswith("test_") or p.name.endswith("_test.py")
    )
    return [ref for path in files for ref in scan_file(path, root)]
