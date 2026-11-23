"""What villagers ask the engine to do (spec §3.2: intents, not mutations)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import ClassVar

from pericles.core.canonical import canonical_json
from pericles.core.geometry import Coord


@dataclass(frozen=True)
class Intent:
    actor: str
    kind: ClassVar[str] = "intent"

    def sort_key(self) -> tuple[str, str, str]:
        return (self.actor, self.kind, canonical_json(asdict(self)))


@dataclass(frozen=True)
class MoveTo(Intent):
    target: Coord
    kind: ClassVar[str] = "move_to"


@dataclass(frozen=True)
class Wait(Intent):
    kind: ClassVar[str] = "wait"


@dataclass(frozen=True)
class StartAction(Intent):
    action: str
    target: str | None = None
    kind: ClassVar[str] = "start_action"
