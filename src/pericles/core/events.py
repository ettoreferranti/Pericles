"""Typed simulation events (ADR-0004)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Event:
    tick: int
    seq: int
    kind: str
    data: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"tick": self.tick, "seq": self.seq, "kind": self.kind, "data": dict(self.data)}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Event:
        return cls(int(data["tick"]), int(data["seq"]), str(data["kind"]), dict(data["data"]))


class EventSink:
    """Collects one tick's events and numbers them."""

    def __init__(self, tick: int) -> None:
        self.tick = tick
        self.events: list[Event] = []

    def emit(self, kind: str, /, **data: Any) -> Event:
        event = Event(self.tick, len(self.events), kind, data)
        self.events.append(event)
        return event
