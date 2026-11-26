import sqlite3
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from pericles.llm.calls import CallLog, CallRecord

RECORD = CallRecord(
    tick=5,
    villager="ada",
    kind="plan",
    model="qwen",
    backend="ollama",
    backend_model="qwen3:latest",
    prompt_hash="ab" * 32,
    tokens_in=120,
    tokens_out=40,
    latency_s=1.25,
    valid=False,
    error="goal: Field required",
    attempt=1,
    cached=False,
    template="plan-v1",
    raw='{"steps": []}',
)


@pytest.mark.req("REQ-LLM-008")
def test_every_field_round_trips(tmp_path: Path) -> None:
    """AC1: model, prompt hash, tokens, latency, validity, retry count and raw output."""
    log = CallLog(tmp_path / "llm_calls.sqlite")
    log.append(RECORD)
    log.append(replace(RECORD, tick=6, valid=True, error=None, cached=True, template=None))
    assert list(log.records()) == [
        RECORD,
        replace(RECORD, tick=6, valid=True, error=None, cached=True, template=None),
    ]
    log.close()


@pytest.mark.req("REQ-LLM-008")
def test_raw_output_is_stored_compressed(tmp_path: Path) -> None:
    """AC1: the raw output is zlib-compressed on disk."""
    path = tmp_path / "llm_calls.sqlite"
    log = CallLog(path)
    log.append(replace(RECORD, raw="x" * 1000))
    log.close()
    blob = sqlite3.connect(path).execute("SELECT raw FROM calls").fetchone()[0]
    assert len(blob) < 100
    assert zlib.decompress(blob).decode("utf-8") == "x" * 1000


@pytest.mark.req("REQ-LLM-008")
def test_records_filter_by_tick_and_truncate(tmp_path: Path) -> None:
    """AC1: the log follows the event log on resume."""
    log = CallLog(tmp_path / "llm_calls.sqlite")
    for tick in (1, 2, 2, 3):
        log.append(replace(RECORD, tick=tick))
    assert [r.tick for r in log.records(2)] == [2, 2, 3]
    assert [r.tick for r in log.records(1, 3)] == [1, 2, 2]
    log.truncate_after(1)
    assert [r.tick for r in log.records()] == [1]
    log.close()
