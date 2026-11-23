"""Run directories: config, meta, event log, snapshots (REQ-EXP-003)."""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

import pericles
from pericles.core.canonical import canonical_json
from pericles.core.state import WorldState
from pericles.experiment.eventlog import EventLog


class RunDirectoryError(Exception):
    """A run directory is missing, foreign or would be overwritten."""


class RunDirectory:
    SCHEMA_VERSION = 2

    def __init__(self, path: Path) -> None:
        self.path = path
        self._event_log: EventLog | None = None

    @classmethod
    def create(cls, path: Path, config: Mapping[str, Any], seed: int) -> RunDirectory:
        if path.exists() and any(path.iterdir()):
            raise RunDirectoryError(f"{path}: directory is not empty; refusing to reuse it")
        path.mkdir(parents=True, exist_ok=True)
        (path / "config.yaml").write_text(
            yaml.safe_dump(dict(config), sort_keys=True), encoding="utf-8"
        )
        meta = {
            "schema_version": cls.SCHEMA_VERSION,
            "pericles_version": pericles.__version__,
            "python": platform.python_version(),
            "seed": seed,
            "created_utc": datetime.now(UTC).isoformat(),
        }
        (path / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (path / "snapshots").mkdir()
        (path / "llm_cache").mkdir()
        run = cls(path)
        _ = run.event_log
        return run

    @classmethod
    def open(cls, path: Path) -> RunDirectory:
        meta_path = path / "meta.json"
        if not meta_path.exists():
            raise RunDirectoryError(f"{path}: not a run directory (no meta.json)")
        version = json.loads(meta_path.read_text(encoding="utf-8")).get("schema_version")
        if version != cls.SCHEMA_VERSION:
            raise RunDirectoryError(
                f"{path}: schema version {version} is not supported (expected {cls.SCHEMA_VERSION})"
            )
        return cls(path)

    @property
    def config(self) -> dict[str, Any]:
        loaded = yaml.safe_load((self.path / "config.yaml").read_text(encoding="utf-8"))
        return dict(loaded or {})

    @property
    def meta(self) -> dict[str, Any]:
        return dict(json.loads((self.path / "meta.json").read_text(encoding="utf-8")))

    @property
    def event_log(self) -> EventLog:
        if self._event_log is None:
            self._event_log = EventLog(self.path / "events.sqlite")
        return self._event_log

    def save_snapshot(self, state: WorldState) -> Path:
        target = self.path / "snapshots" / f"tick-{state.tick:010d}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(canonical_json(state.to_dict()), encoding="utf-8")
        os.replace(temporary, target)
        return target

    def snapshot_ticks(self) -> list[int]:
        return sorted(
            int(p.stem.removeprefix("tick-")) for p in (self.path / "snapshots").glob("tick-*.json")
        )

    def latest_snapshot(self) -> dict[str, Any] | None:
        ticks = self.snapshot_ticks()
        if not ticks:
            return None
        path = self.path / "snapshots" / f"tick-{ticks[-1]:010d}.json"
        return dict(json.loads(path.read_text(encoding="utf-8")))

    def close(self) -> None:
        if self._event_log is not None:
            self._event_log.close()
            self._event_log = None
