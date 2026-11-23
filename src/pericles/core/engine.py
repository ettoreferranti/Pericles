"""The deterministic tick loop (REQ-SIM-002, ADR-0001, ADR-0013, ADR-0014)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from functools import partial

from pericles.core import construction, work
from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.context import Context
from pericles.core.events import Event, EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import (
    Construct,
    Craft,
    Deliver,
    Deposit,
    Intent,
    MoveTo,
    PlaceBuilding,
    Research,
    StartAction,
    Take,
    Wait,
)
from pericles.core.invariants import InvariantError, check_tick, item_totals
from pericles.core.mapgen import TileMap
from pericles.core.modifiers import expire
from pericles.core.nodes import regrow
from pericles.core.pathfinding import TerrainCostField, find_path
from pericles.core.state import WorldState

Handler = Callable[[WorldState, Intent, EventSink], None]


class Engine:
    def __init__(self, registry: Registry, config: EngineConfig | None = None) -> None:
        self.registry = registry
        self.config = config if config is not None else EngineConfig()
        self.context = Context.build(registry, self.config)
        self._handlers: dict[type[Intent], Handler] = {
            MoveTo: self._move_to,
            Wait: self._wait,
            StartAction: partial(work.start_action, self.context),
            PlaceBuilding: partial(construction.place_building, self.context),
            Deliver: partial(construction.deliver, self.context),
            Construct: partial(construction.construct, self.context),
            Deposit: partial(construction.deposit, self.context),
            Take: partial(construction.take, self.context),
            Craft: partial(work.start_recipe, self.context),
            Research: partial(work.start_research, self.context),
        }
        self._cache: tuple[TileMap, frozenset[Coord], TerrainCostField] | None = (
            None  # pragma: no mutate - cache sentinel; any non-matching value just forces a rebuild
        )

    def register(self, intent_type: type[Intent], handler: Handler) -> None:
        self._handlers[intent_type] = handler

    def interrupt(
        self, state: WorldState, villager_id: str, sink: EventSink, cause: str = "intervened"
    ) -> None:
        """Interrupt a villager's work on behalf of someone else (REQ-SIM-008 AC3)."""
        work.interrupt(self.context, state.villagers[villager_id], sink, cause=cause)

    def step(self, state: WorldState, intents: Sequence[Intent]) -> tuple[WorldState, list[Event]]:
        sink = EventSink(state.tick)
        before = item_totals(state) if self.config.debug_invariants else None
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
            work.interrupt(self.context, state.villagers[intent.actor], sink, cause="actor")
            self._handlers[type(intent)](state, intent, sink)
        self._advance_work(state, sink)
        self._advance_movement(state, sink)
        if (state.tick + 1) % self.config.calendar.ticks_per_day == 0:
            regrow(state.nodes.values(), self.registry)
        state.modifiers = expire(state.modifiers, state.tick + 1)
        state.tick += 1
        if before is not None:
            problems = check_tick(self.context, before, state, sink.events)
            if problems:
                raise InvariantError(f"tick {state.tick - 1}: " + "; ".join(problems))
        return state, sink.events

    def _advance_work(self, state: WorldState, sink: EventSink) -> None:
        for vid in sorted(state.villagers):
            villager = state.villagers[vid]
            activity = villager.activity
            if activity is None:
                continue
            if activity.kind == "construction":
                construction.progress(self.context, state, villager, sink)
                continue
            activity.done += activity.speed
            if activity.done >= activity.work - work.EPSILON:
                work.complete(self.context, state, villager, sink)

    def _cost_field(self, state: WorldState) -> TerrainCostField:
        """Cached per tilemap object and blocked-tile set (ADR-0014 §7)."""
        blocked = construction.blocked_tiles(self.context, state)
        cache = self._cache
        if cache is not None and cache[0] is state.tilemap and cache[1] == blocked:
            return cache[2]
        field = TerrainCostField(state.tilemap, self.registry, blocked.__contains__)
        self._cache = (state.tilemap, blocked, field)
        return field

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
