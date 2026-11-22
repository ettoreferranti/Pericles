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


def _is_req(func: ast.expr) -> bool:
    return (
        isinstance(func, ast.Attribute)
        and func.attr == "req"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
        and isinstance(func.value.value, ast.Name)
        and func.value.value.id == "pytest"
    )


def _ids(node: ast.expr, path: Path) -> list[str]:
    if not (isinstance(node, ast.Call) and _is_req(node.func)):
        return []
    ids: list[str] = []
    for arg in node.args:
        if not (isinstance(arg, ast.Constant) and isinstance(arg.value, str)):
            raise MarkerError(f"{path}:{arg.lineno}: req marker arguments must be string literals")
        ids.append(arg.value)
    if not ids:
        raise MarkerError(f"{path}:{node.lineno}: req marker needs at least one requirement ID")
    return ids


def _refs(decorators: list[ast.expr], nodeid: str, path: Path) -> list[TestRef]:
    return [TestRef(req_id, nodeid) for d in decorators for req_id in _ids(d, path)]


def _scan_body(body: list[ast.stmt], prefix: str, path: Path) -> list[TestRef]:
    refs: list[TestRef] = []
    for stmt in body:
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef):
            refs += _refs(stmt.decorator_list, f"{prefix}::{stmt.name}", path)
        elif isinstance(stmt, ast.ClassDef):
            nodeid = f"{prefix}::{stmt.name}"
            refs += _refs(stmt.decorator_list, nodeid, path)
            refs += _scan_body(stmt.body, nodeid, path)
    return refs


def scan_file(path: Path, root: Path) -> list[TestRef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    rel = path.relative_to(root).as_posix()
    refs: list[TestRef] = []
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets
        ):
            value = stmt.value
            values = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
            refs += _refs(values, rel, path)
    return refs + _scan_body(tree.body, rel, path)


def scan_tests(test_dir: Path, root: Path) -> list[TestRef]:
    files = sorted(
        p
        for p in test_dir.rglob("*.py")
        if p.name.startswith("test_") or p.name.endswith("_test.py")
    )
    return [ref for path in files for ref in scan_file(path, root)]
