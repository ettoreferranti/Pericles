"""Run directories: config, meta, event log, snapshots (REQ-EXP-003)."""

from __future__ import annotations

import json
import os
import platform
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

import pericles
from pericles.core.canonical import canonical_json
from pericles.core.state import WorldState
from pericles.experiment.eventlog import EventLog


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_durably(target: Path, text: str) -> None:
    """Write to a temporary file, fsync it, rename it into place and fsync the directory."""
    temporary = target.with_suffix(target.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, target)
    _fsync_dir(target.parent)


@dataclass(frozen=True)
class Snapshot:
    tick: int
    world: dict[str, Any]
    agents: dict[str, Any]


class RunDirectoryError(Exception):
    """A run directory is missing, foreign or would be overwritten."""


class RunDirectory:
    SCHEMA_VERSION = 3

    def __init__(self, path: Path) -> None:
        self.path = path
        self._event_log: EventLog | None = None
        self.skipped: list[Path] = []

    @classmethod
    def create(cls, path: Path, config: Mapping[str, Any], seed: int) -> RunDirectory:
        if path.exists() and any(path.iterdir()):
            raise RunDirectoryError(f"{path}: directory is not empty; refusing to reuse it")
        path.mkdir(parents=True, exist_ok=True)
        _write_durably(path / "config.yaml", yaml.safe_dump(dict(config), sort_keys=True))
        meta = {
            "schema_version": cls.SCHEMA_VERSION,
            "pericles_version": pericles.__version__,
            "python": platform.python_version(),
            "seed": seed,
            "created_utc": datetime.now(UTC).isoformat(),
        }
        _write_durably(path / "meta.json", json.dumps(meta, indent=2))
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
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            version = meta.get("schema_version")
        except (OSError, ValueError, AttributeError) as error:
            raise RunDirectoryError(f"{path}: meta.json is unreadable ({error})") from error
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

    def _snapshot_path(self, tick: int) -> Path:
        return self.path / "snapshots" / f"tick-{tick:010d}.json"

    def save_snapshot(self, state: WorldState, agents: Mapping[str, Any] | None = None) -> Path:
        target = self._snapshot_path(state.tick)
        payload = {"world": state.to_dict(), "agents": dict(agents or {})}
        _write_durably(target, canonical_json(payload))
        return target

    def snapshot_ticks(self) -> list[int]:
        return sorted(
            int(p.stem.removeprefix("tick-")) for p in (self.path / "snapshots").glob("tick-*.json")
        )

    def snapshots(self) -> Iterator[Snapshot]:
        """Usable snapshots, newest first; unreadable or mislabelled ones go to `skipped`."""
        for tick in reversed(self.snapshot_ticks()):
            path = self._snapshot_path(tick)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                snapshot = Snapshot(tick, dict(payload["world"]), dict(payload["agents"]))
                usable = snapshot.world.get("tick") == tick
            except (OSError, ValueError, KeyError, TypeError):
                usable = False
            if not usable:
                self.skipped.append(path)
                continue
            yield snapshot

    def latest_snapshot(self) -> Snapshot | None:
        return next(self.snapshots(), None)

    def close(self) -> None:
        if self._event_log is not None:
            self._event_log.close()
            self._event_log = None
