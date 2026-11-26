"""Response cache: off, record or replay (REQ-LLM-005; ADR-0017 §5)."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from pericles.core.canonical import canonical_json
from pericles.llm.types import BackendCall, Completion

CACHE_MODES = ("off", "record", "replay")
SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL
);
"""


class CacheMiss(Exception):
    """Replay mode found no cached response for a request."""


def cache_key(model: str, call: BackendCall) -> str:
    """SHA-256 of the model ("<backend kind>:<name>"), sampling, messages, schema and seed."""
    payload = {
        "model": model,
        "sampling": call.sampling.to_dict(),
        "messages": [m.to_dict() for m in call.messages],
        "schema": None if call.schema is None else dict(call.schema),
        "seed": call.seed,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, path: Path | None, mode: str) -> None:
        if mode not in CACHE_MODES:
            raise ValueError(f"cache mode must be one of {CACHE_MODES}, got {mode!r}")
        if mode != "off" and path is None:
            raise ValueError(f"cache mode {mode!r} needs a path")
        self.mode = mode
        self._conn: sqlite3.Connection | None = None
        if path is not None and mode != "off":
            self._conn = sqlite3.connect(path)
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def get(self, key: str) -> Completion | None:
        """The cached response in replay mode (a miss raises CacheMiss); None otherwise."""
        if self.mode != "replay" or self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT text, tokens_in, tokens_out FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise CacheMiss(key)
        return Completion(str(row[0]), int(row[1]), int(row[2]))

    def put(self, key: str, completion: Completion) -> None:
        if self.mode != "record" or self._conn is None:
            return
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?)",
                (key, completion.text, completion.tokens_in, completion.tokens_out),
            )

    def __len__(self) -> int:
        if self._conn is None:
            return 0
        return int(self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0])

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
