"""Append-only, per-tick transactional event log in SQLite (ADR-0004, REQ-EXP-003 AC2)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator, Sequence
from pathlib import Path

from pericles.core.canonical import canonical_json
from pericles.core.events import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    tick INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (tick, seq)
);
CREATE TABLE IF NOT EXISTS ticks (tick INTEGER PRIMARY KEY);
"""


class EventLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def last_tick(self) -> int | None:
        row = self._conn.execute("SELECT MAX(tick) FROM ticks").fetchone()
        return None if row[0] is None else int(row[0])

    def append_tick(self, tick: int, events: Sequence[Event]) -> None:
        last = self.last_tick()
        expected = 0 if last is None else last + 1
        if tick != expected:
            raise ValueError(f"expected tick {expected}, got {tick}")
        rows = []
        for event in events:
            if event.tick != tick:
                raise ValueError(f"event tick {event.tick} does not match tick {tick}")
            rows.append((event.tick, event.seq, event.kind, canonical_json(dict(event.data))))
        with self._conn:
            self._conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", rows)
            self._conn.execute("INSERT INTO ticks VALUES (?)", (tick,))

    def events(self, start: int = 0, end: int | None = None) -> Iterator[Event]:
        query = "SELECT tick, seq, kind, data FROM events WHERE tick >= ?"
        params: list[int] = [start]
        if end is not None:
            query += " AND tick < ?"
            params.append(end)
        for tick, seq, kind, data in self._conn.execute(query + " ORDER BY tick, seq", params):
            yield Event(int(tick), int(seq), str(kind), json.loads(data))

    def truncate_after(self, tick: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM events WHERE tick > ?", (tick,))
            self._conn.execute("DELETE FROM ticks WHERE tick > ?", (tick,))

    def digest(self) -> str:
        hasher = hashlib.sha256()
        hasher.update(f"ticks:{self.last_tick()}\n".encode())
        for event in self.events():
            hasher.update(canonical_json(event.to_dict()).encode("utf-8"))
            hasher.update(b"\n")
        return hasher.hexdigest()

    def close(self) -> None:
        self._conn.close()
