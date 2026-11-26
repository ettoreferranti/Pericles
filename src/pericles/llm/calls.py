"""One row per LLM call, outside the event log (REQ-LLM-008; ADR-0017 §6)."""

from __future__ import annotations

import sqlite3
import zlib
from collections.abc import Iterator
from dataclasses import astuple, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class CallRecord:
    tick: int
    villager: str
    kind: str
    model: str
    backend: str
    backend_model: str
    prompt_hash: str
    tokens_in: int
    tokens_out: int
    latency_s: float
    valid: bool
    error: str | None
    attempt: int
    cached: bool
    template: str | None
    raw: str


COLUMNS = tuple(f.name for f in fields(CallRecord))
SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER NOT NULL,
    villager TEXT NOT NULL,
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    backend TEXT NOT NULL,
    backend_model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    latency_s REAL NOT NULL,
    valid INTEGER NOT NULL,
    error TEXT,
    attempt INTEGER NOT NULL,
    cached INTEGER NOT NULL,
    template TEXT,
    raw BLOB NOT NULL
);
"""


class CallLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def append(self, record: CallRecord) -> None:
        values = list(astuple(record))
        values[COLUMNS.index("raw")] = zlib.compress(record.raw.encode("utf-8"))
        placeholders = ", ".join("?" for _ in COLUMNS)
        with self._conn:
            self._conn.execute(
                f"INSERT INTO calls ({', '.join(COLUMNS)}) VALUES ({placeholders})", values
            )

    def records(self, start: int = 0, end: int | None = None) -> Iterator[CallRecord]:
        query = f"SELECT {', '.join(COLUMNS)} FROM calls WHERE tick >= ?"
        params: list[int] = [start]
        if end is not None:
            query += " AND tick < ?"
            params.append(end)
        for row in self._conn.execute(query + " ORDER BY id", params):
            item = dict(zip(COLUMNS, row, strict=True))
            item["raw"] = zlib.decompress(item["raw"]).decode("utf-8")
            item["valid"] = bool(item["valid"])
            item["cached"] = bool(item["cached"])
            yield CallRecord(**item)

    def truncate_after(self, tick: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM calls WHERE tick > ?", (tick,))

    def close(self) -> None:
        self._conn.close()
