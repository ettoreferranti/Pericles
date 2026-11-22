"""The deterministic tick loop (REQ-SIM-002, ADR-0001, ADR-0013)."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from pericles.core.content.registry import Registry
from pericles.core.events import Event, EventSink
from pericles.core.intents import Intent, MoveTo, Wait
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import expire
from pericles.core.pathfinding import TerrainCostField, find_path
from pericles.core.state import WorldState

Handler = Callable[[WorldState, Intent, EventSink], None]


class Engine:
    def __init__(self, registry: Registry) -> None:
        self.registry = registry
        self._handlers: dict[type[Intent], Handler] = {
            MoveTo: self._move_to,
            Wait: self._wait,
        }
        self._field_map: TileMap | None = (
            None  # pragma: no mutate - cache sentinel; any non-matching value just forces a rebuild
        )
        self._field: TerrainCostField | None = (
            None  # pragma: no mutate - cache sentinel; any non-None value just forces a rebuild
        )

    def register(self, intent_type: type[Intent], handler: Handler) -> None:
        self._handlers[intent_type] = handler

    def step(self, state: WorldState, intents: Sequence[Intent]) -> tuple[WorldState, list[Event]]:
        sink = EventSink(state.tick)
        ordered = sorted(intents, key=lambda i: i.sort_key())
        state.rng.shuffle(ordered)
        acted: set[str] = set()
        for intent in ordered:
            reason = None
            if intent.actor not in state.villagers:
                reason = "unknown_actor"
            elif intent.actor in acted:
                reason = "duplicate_intent"
            elif type(intent) not in self._handlers:
                reason = "unknown_intent"
            if reason is not None:
                sink.emit("intent_rejected", actor=intent.actor, intent=intent.kind, reason=reason)
                continue
            acted.add(intent.actor)
            self._handlers[type(intent)](state, intent, sink)
        self._advance_movement(state, sink)
        state.modifiers = expire(state.modifiers, state.tick + 1)
        state.tick += 1
        return state, sink.events

    def _cost_field(self, state: WorldState) -> TerrainCostField:
        if self._field is None or self._field_map is not state.tilemap:
            self._field = TerrainCostField(state.tilemap, self.registry)
            self._field_map = state.tilemap
        return self._field

    def _move_to(self, state: WorldState, intent: Intent, sink: EventSink) -> None:
        assert isinstance(intent, MoveTo)
        villager = state.villagers[intent.actor]
        path = find_path(self._cost_field(state), villager.pos, intent.target)
        villager.move_progress = 0.0
        if path is None:
            villager.path = []
            sink.emit(
                "move_failed", actor=villager.id, target=list(intent.target), reason="no_path"
            )
        elif len(path) == 1:
            villager.path = []
            sink.emit("arrived", actor=villager.id, at=list(villager.pos))
        else:
            villager.path = path[1:]
            sink.emit(
                "move_started", actor=villager.id, target=list(intent.target), steps=len(path) - 1
            )

    def _wait(self, state: WorldState, intent: Intent, sink: EventSink) -> None:
        villager = state.villagers[intent.actor]
        if villager.path:
            villager.path = []
            villager.move_progress = 0.0
            sink.emit("stopped", actor=villager.id, at=list(villager.pos))

    def _advance_movement(self, state: WorldState, sink: EventSink) -> None:
        field = self._cost_field(state)
        for vid in sorted(state.villagers):
            villager = state.villagers[vid]
            if not villager.path:
                continue
            villager.move_progress += 1.0
            while villager.path:
                cost = field.cost(villager.path[0])
                if cost is None:
                    target = villager.path[-1]
                    villager.path = []
                    villager.move_progress = 0.0
                    sink.emit("move_failed", actor=vid, target=list(target), reason="blocked")
                    break
                if villager.move_progress < cost:
                    break
                villager.move_progress -= cost
                villager.pos = villager.path.pop(0)
                sink.emit("moved", actor=vid, to=list(villager.pos))
                if not villager.path:
                    villager.move_progress = 0.0
                    sink.emit("arrived", actor=vid, at=list(villager.pos))
