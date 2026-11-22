"""Load and validate one content pack directory (REQ-SIM-005 AC1)."""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from pericles.core.content.schema import SECTIONS, Model, PackFile


class ContentError(Exception):
    """Content is invalid; the message names file, definition and field."""


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects a repeated mapping key instead of keeping the last."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if isinstance(key, Hashable):
                if key in seen:
                    line = key_node.start_mark.line + 1
                    raise _DuplicateKeyError(line, key)
                seen.add(key)
        return super().construct_mapping(node, deep=deep)


class _DuplicateKeyError(Exception):
    def __init__(self, line: int, key: object) -> None:
        super().__init__(f"{line}: duplicate key {key!r}")
        self.line = line
        self.key = key


@dataclass(frozen=True)
class Pack:
    name: str
    path: Path
    defs: Mapping[str, Mapping[str, Model]]


def load_pack(path: Path) -> Pack:
    if not path.is_dir():
        raise ContentError(f"{path}: content pack must be a directory")
    files = sorted(path.glob("*.yaml"))
    if not files:
        raise ContentError(f"{path}: content pack has no .yaml files")
    defs: dict[str, dict[str, Model]] = {section: {} for section in SECTIONS}
    for file in files:
        raw = _read_yaml(file)
        try:
            parsed = PackFile.model_validate(raw)
        except ValidationError as exc:
            raise ContentError(_describe(file, raw, exc)) from None
        for section in SECTIONS:
            for definition in getattr(parsed, section):
                if definition.id in defs[section]:
                    raise ContentError(
                        f"{file}: {section}[{definition.id}]: duplicate id within pack "
                        f"{path.name!r}"
                    )
                defs[section][definition.id] = definition
    return Pack(name=path.name, path=path, defs=defs)


def _read_yaml(file: Path) -> dict[str, Any]:
    try:
        raw = yaml.load(file.read_text(encoding="utf-8"), Loader=_UniqueKeyLoader)
    except _DuplicateKeyError as exc:
        raise ContentError(f"{file}:{exc.line}: duplicate key {exc.key!r}") from None
    except yaml.YAMLError as exc:
        raise ContentError(f"{file}: invalid YAML: {exc}") from None
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ContentError(
            f"{file}: top level must be a mapping of sections, got {type(raw).__name__}"
        )
    return raw


def _describe(file: Path, raw: dict[str, Any], exc: ValidationError) -> str:
    return "\n".join(
        f"{file}: {_location(raw, error['loc'])}: {error['msg']}" for error in exc.errors()
    )


def _location(raw: dict[str, Any], loc: Sequence[int | str]) -> str:
    """Render a pydantic location, replacing list indexes by definition ids."""
    parts: list[str] = []
    node: Any = raw
    for key in loc:
        if isinstance(key, int) and isinstance(node, list) and 0 <= key < len(node):
            item = node[key]
            ident = item.get("id") if isinstance(item, dict) else None
            label = f"[{ident}]" if isinstance(ident, str) else f"[{key}]"
            if parts:
                parts[-1] += label
            else:
                parts.append(label)
            node = item
        else:
            parts.append(str(key))
            node = node.get(key) if isinstance(node, dict) else None
    return ".".join(parts)
