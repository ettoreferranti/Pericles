import sqlite3
from pathlib import Path

import pytest

from pericles.core.events import Event
from pericles.experiment.eventlog import EventLog

pytestmark = pytest.mark.req("REQ-EXP-003")


def ev(tick: int, seq: int, kind: str = "moved", **data: object) -> Event:
    return Event(tick, seq, kind, data)


def test_append_and_read_back(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "events.sqlite")
    assert log.last_tick() is None
    log.append_tick(0, [ev(0, 0, actor="a", to=[1, 2]), ev(0, 1, "arrived", actor="a")])
    log.append_tick(1, [])
    log.append_tick(2, [ev(2, 0, actor="b")])
    assert log.last_tick() == 2
    assert [e.to_dict() for e in log.events()] == [
        {"tick": 0, "seq": 0, "kind": "moved", "data": {"actor": "a", "to": [1, 2]}},
        {"tick": 0, "seq": 1, "kind": "arrived", "data": {"actor": "a"}},
        {"tick": 2, "seq": 0, "kind": "moved", "data": {"actor": "b"}},
    ]
    assert [e.tick for e in log.events(start=1, end=2)] == []
    assert [e.tick for e in log.events(start=2)] == [2]
    assert [e.tick for e in log.events(end=1)] == [0, 0]
    log.close()


def test_persists_across_reopen(tmp_path: Path) -> None:
    path = tmp_path / "events.sqlite"
    log = EventLog(path)
    log.append_tick(0, [ev(0, 0)])
    log.close()
    reopened = EventLog(path)
    assert reopened.last_tick() == 0
    assert len(list(reopened.events())) == 1


def test_ticks_must_be_contiguous_from_zero(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.sqlite")
    with pytest.raises(ValueError, match="expected tick 0"):
        log.append_tick(1, [])
    log.append_tick(0, [])
    with pytest.raises(ValueError, match="expected tick 1"):
        log.append_tick(0, [])
    with pytest.raises(ValueError, match="expected tick 1"):
        log.append_tick(3, [])


def test_event_tick_must_match(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.sqlite")
    with pytest.raises(ValueError, match="event tick 5"):
        log.append_tick(0, [ev(5, 0)])


def test_failed_tick_is_rolled_back_entirely(tmp_path: Path) -> None:
    """AC2: event writes are transactional per tick."""
    log = EventLog(tmp_path / "e.sqlite")
    log.append_tick(0, [ev(0, 0)])
    with pytest.raises(sqlite3.IntegrityError):
        log.append_tick(1, [ev(1, 0), ev(1, 0)])
    assert log.last_tick() == 0
    assert [e.tick for e in log.events()] == [0]
    log.append_tick(1, [ev(1, 0)])
    assert log.last_tick() == 1


def test_unserialisable_data_writes_nothing(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.sqlite")
    with pytest.raises(ValueError):
        log.append_tick(0, [ev(0, 0, x=float("nan"))])
    assert log.last_tick() is None


def test_truncate_after(tmp_path: Path) -> None:
    log = EventLog(tmp_path / "e.sqlite")
    for t in range(5):
        log.append_tick(t, [ev(t, 0)])
    log.truncate_after(2)
    assert log.last_tick() == 2
    assert [e.tick for e in log.events()] == [0, 1, 2]
    log.append_tick(3, [])
    log.truncate_after(-1)
    assert log.last_tick() is None


def test_digest_reflects_content_and_order(tmp_path: Path) -> None:
    a, b, c = (EventLog(tmp_path / f"{n}.sqlite") for n in "abc")
    a.append_tick(0, [ev(0, 0, x=1), ev(0, 1, x=2)])
    b.append_tick(0, [ev(0, 0, x=1), ev(0, 1, x=2)])
    c.append_tick(0, [ev(0, 0, x=2), ev(0, 1, x=1)])
    assert a.digest() == b.digest()
    assert a.digest() != c.digest()
    empty = EventLog(tmp_path / "d.sqlite")
    assert empty.digest() != a.digest()


def test_midtick_crash_leaves_no_partial_tick_on_disk(tmp_path: Path) -> None:
    """AC2: a failure part-way through a tick is invisible after reopening."""
    path = tmp_path / "e.sqlite"
    log = EventLog(path)
    log.append_tick(0, [ev(0, 0)])
    with pytest.raises(ValueError):
        log.append_tick(1, [ev(1, 0), ev(1, 1, x=float("nan"))])
    with pytest.raises(sqlite3.IntegrityError):
        log.append_tick(1, [ev(1, 0), ev(1, 0)])
    log.close()
    reopened = EventLog(path)
    assert reopened.last_tick() == 0
    assert [(e.tick, e.seq) for e in reopened.events()] == [(0, 0)]
