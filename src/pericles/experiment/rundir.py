"""Run directories: config, meta, event log, snapshots (REQ-EXP-003)."""

from __future__ import annotations

import json
import os
import platform
import re
import sqlite3
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import yaml

import pericles
from pericles.analysis.metrics import Row
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


METRICS = "metrics.parquet"
SNAPSHOT_NAME = re.compile(r"tick-(\d{10})\.json")


class RunDirectoryError(Exception):
    """A run directory is missing, foreign or would be overwritten."""


class RunDirectory:
    SCHEMA_VERSION = 3

    def __init__(self, path: Path) -> None:
        self.path = path
        self._event_log: EventLog | None = None
        self.skipped: list[Path] = []

    @classmethod
    def create(
        cls,
        path: Path,
        config: Mapping[str, Any],
        seed: int,
        extra: Mapping[str, Any] | None = None,
    ) -> RunDirectory:
        if path.exists() and not path.is_dir():
            raise RunDirectoryError(f"{path}: not a directory")
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
        meta.update(dict(extra or {}))
        _write_durably(path / "meta.json", json.dumps(meta, indent=2))
        for name in ("snapshots", "llm_cache"):
            (path / name).mkdir()
            _fsync_dir(path / name)
        _fsync_dir(path)
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
            try:
                log = EventLog(self.path / "events.sqlite")
                log.last_tick()
            except sqlite3.DatabaseError as error:
                raise RunDirectoryError(
                    f"{self.path}: events.sqlite is unreadable ({error})"
                ) from None
            self._event_log = log
        return self._event_log

    def skip(self, path: Path) -> None:
        """Record an unusable snapshot file once."""
        if path not in self.skipped:
            self.skipped.append(path)

    def snapshot_path(self, tick: int) -> Path:
        return self.path / "snapshots" / f"tick-{tick:010d}.json"

    def save_snapshot(self, state: WorldState, agents: Mapping[str, Any] | None = None) -> Path:
        target = self.snapshot_path(state.tick)
        payload = {"world": state.to_dict(), "agents": dict(agents or {})}
        _write_durably(target, canonical_json(payload))
        return target

    def _snapshot_files(self) -> tuple[list[int], list[Path]]:
        """Ticks of well-named snapshot files, and the stray `tick-*.json` names."""
        ticks: list[int] = []
        strays: list[Path] = []
        for path in sorted((self.path / "snapshots").glob("tick-*.json")):
            match = SNAPSHOT_NAME.fullmatch(path.name)
            if match:
                ticks.append(int(match.group(1)))
            else:
                strays.append(path)
        return sorted(ticks), strays

    def snapshot_ticks(self) -> list[int]:
        return self._snapshot_files()[0]

    def snapshots(self) -> Iterator[Snapshot]:
        """Usable snapshots, newest first; unreadable or mislabelled ones go to `skipped`."""
        ticks, strays = self._snapshot_files()
        for stray in strays:
            self.skip(stray)
        for tick in reversed(ticks):
            path = self.snapshot_path(tick)
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                snapshot = Snapshot(tick, dict(payload["world"]), dict(payload["agents"]))
                usable = snapshot.world.get("tick") == tick
            except (OSError, ValueError, KeyError, TypeError):
                usable = False
            if not usable:
                self.skip(path)
                continue
            yield snapshot

    def latest_snapshot(self) -> Snapshot | None:
        return next(self.snapshots(), None)

    def write_metrics(self, rows: Sequence[Row]) -> Path:
        """Replace metrics.parquet durably: one (day, metric, value) row per entry."""
        table = pa.table(
            {
                "day": pa.array([r.day for r in rows], pa.int64()),
                "metric": pa.array([r.metric for r in rows], pa.string()),
                "value": pa.array([r.value for r in rows], pa.float64()),
            }
        )
        target = self.path / METRICS
        temporary = target.with_suffix(target.suffix + ".tmp")
        pq.write_table(table, temporary)
        with open(temporary, "rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        _fsync_dir(self.path)
        return target

    def read_metrics(self) -> list[Row]:
        path = self.path / METRICS
        if not path.exists():
            raise RunDirectoryError(f"{path}: no metrics yet; run or resume first")
        table = pq.read_table(path)
        return [Row(int(r["day"]), str(r["metric"]), float(r["value"])) for r in table.to_pylist()]

    def close(self) -> None:
        if self._event_log is not None:
            self._event_log.close()
            self._event_log = None
