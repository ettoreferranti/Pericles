"""Turns world state into intents for due villagers (ADR-0016 §1-§2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from pericles.agents.config import AgentConfig
from pericles.agents.view import Decision, Memory, NodeIndex, OriginCache, View
from pericles.core.context import Context
from pericles.core.events import Event
from pericles.core.intents import Construct, Intent, MoveTo, Sleep, StartAction, Wait
from pericles.core.life import SLEEP
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

FAILURES = ("intent_rejected", "move_failed")
INTERRUPTED, ENGINE_CAUSE = "work_interrupted", "engine"
WATCHED = frozenset((*FAILURES, INTERRUPTED))  # the only kinds `failed_event` can accept
ACTION, CONSTRUCTION = "action", "construction"


class MindFailure(Exception):
    """A mind could not decide; the scripted mind takes over (REQ-AGT-008 AC2)."""


class Mind(Protocol):
    def decide(self, view: View, villager: Villager) -> Decision | None: ...


@runtime_checkable
class Planner(Protocol):
    """A mind that prepares decisions for many villagers at once (ADR-0018 §1)."""

    def prepare(self, view: View, villagers: Sequence[Villager]) -> None: ...

    def decide(self, view: View, villager: Villager) -> Decision | None: ...

    def observe(self, state: WorldState, events: Sequence[Event]) -> None: ...

    def take_events(self) -> list[tuple[str, dict[str, Any]]]: ...

    def to_dict(self) -> dict[str, Any]: ...

    def parse(self, data: Mapping[str, Any]) -> object: ...

    def restore(self, parsed: object) -> None: ...


def failed_event(event: Event) -> bool:
    """True if `event` says the villager's current plan did not work out.

    Work the engine itself stops (depleted node, full carry, known technology) is a failure;
    work the villager or an intervention stops is not.
    """
    if event.kind == INTERRUPTED:
        return event.data.get("cause") == ENGINE_CAUSE
    return event.kind in FAILURES


def _redundant(villager: Villager, intent: Intent) -> bool:
    """True if the villager is already doing what `intent` asks; sending it would restart it."""
    activity = villager.activity
    if isinstance(intent, MoveTo):
        return bool(villager.path) and villager.path[-1] == intent.target
    if activity is None:
        return False
    if isinstance(intent, StartAction):
        return activity.kind == ACTION and (activity.ident, activity.target) == (
            intent.action,
            intent.target,
        )
    if isinstance(intent, Sleep):
        return activity.kind == SLEEP
    if isinstance(intent, Construct):
        return activity.kind == CONSTRUCTION and activity.target == intent.building
    return False


class Controller:
    def __init__(
        self,
        ctx: Context,
        config: AgentConfig,
        adult: Mind,
        child: Mind,
        minds: Mapping[str, Mind] | None = None,
    ) -> None:
        self.ctx = ctx
        self.config = config
        self.adult = adult
        self.child = child
        self.minds = dict(minds or {})
        self.memory: dict[str, Memory] = {}
        self.fallbacks = 0
        self._index: tuple[dict[str, Node], NodeIndex] | None = None
        self._origins = OriginCache()

    def view(self, state: WorldState) -> View:
        if self._index is None or self._index[0] is not state.nodes:
            self._index = (state.nodes, NodeIndex(state.nodes.values(), self.config.index_cell))
        return View(self.ctx, state, self.config, self._index[1], self.memory, self._origins)

    def intents(self, state: WorldState) -> list[Intent]:
        self.memory = {vid: m for vid, m in self.memory.items() if vid in state.villagers}
        view = self.view(state)
        due: list[Villager] = []
        for vid in sorted(state.villagers):
            villager = state.villagers[vid]
            memory = self.memory.get(vid)
            if memory is None:
                memory = self.memory[vid] = Memory()
            # Due: idle time over, and either free (no path, no activity) or urgent.
            if state.tick < memory.idle_until:
                continue
            if (villager.path or villager.activity is not None) and not view.urgent(villager):
                continue
            due.append(villager)
        for key, planner in self._planners():
            group = [v for v in due if v.adult and v.model == key]
            if group:
                planner.prepare(view, group)
        intents: list[Intent] = []
        for villager in due:
            memory = self.memory[villager.id]
            decision = self._decide(view, villager)
            if decision is None:
                memory.idle_until = state.tick + self.config.idle_ticks
                continue
            if _redundant(villager, decision.intent):
                continue
            view.remember(villager.id, memory, decision.target, decision.job)
            if isinstance(decision.intent, Wait):
                memory.idle_until = state.tick + self.config.idle_ticks
                continue
            intents.append(decision.intent)
        return intents

    def _planners(self) -> list[tuple[str, Planner]]:
        return [(k, m) for k, m in sorted(self.minds.items()) if isinstance(m, Planner)]

    def events(self) -> list[tuple[str, dict[str, Any]]]:
        """Agent events since the last call, planner by planner in model-key order."""
        out: list[tuple[str, dict[str, Any]]] = []
        for _, planner in self._planners():
            out.extend(planner.take_events())
        return out

    def _decide(self, view: View, villager: Villager) -> Decision | None:
        if not villager.adult:
            return self.child.decide(view, villager)
        mind = self.minds.get(villager.model) if villager.model is not None else None
        if mind is None:
            return self.adult.decide(view, villager)
        try:
            return mind.decide(view, villager)
        except MindFailure:
            self.fallbacks += 1
            return self.adult.decide(view, villager)

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        """Learn from the tick's failures: avoid failed targets, idle on untargeted failures."""
        for event in events:
            if event.kind not in WATCHED or not failed_event(event):
                continue
            memory = self.memory.get(str(event.data.get("actor")))
            if memory is None:
                continue
            if memory.target is not None:
                memory.avoid[memory.target] = state.tick + self.config.avoid_ticks
                memory.target = memory.job = None
            else:
                memory.idle_until = state.tick + self.config.idle_ticks
        for memory in self.memory.values():
            if memory.avoid and min(memory.avoid.values()) <= state.tick:
                memory.avoid = {t: until for t, until in memory.avoid.items() if until > state.tick}
        for _, planner in self._planners():
            planner.observe(state, events)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "fallbacks": self.fallbacks,
            "memory": {vid: self.memory[vid].to_dict() for vid in sorted(self.memory)},
        }
        planners = self._planners()
        if planners:
            out["minds"] = {key: planner.to_dict() for key, planner in planners}
        return out

    def load(self, data: Mapping[str, Any]) -> None:
        """Restore from `to_dict` output. On error the controller is left unchanged."""
        fallbacks = int(data.get("fallbacks", 0))
        memory = {str(k): Memory.from_dict(v) for k, v in data.get("memory", {}).items()}
        minds = data.get("minds", {})
        parsed = [(p, p.parse(minds[key])) for key, p in self._planners() if key in minds]
        self.fallbacks, self.memory = fallbacks, memory
        for planner, value in parsed:
            planner.restore(value)
