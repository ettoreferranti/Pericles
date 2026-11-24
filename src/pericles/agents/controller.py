"""Turns world state into intents for due villagers (ADR-0016 §1-§2)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Protocol

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
ACTION, CONSTRUCTION = "action", "construction"


class MindFailure(Exception):
    """A mind could not decide; the scripted mind takes over (REQ-AGT-008 AC2)."""


class Mind(Protocol):
    def decide(self, view: View, villager: Villager) -> Decision | None: ...


def _failed(event: Event) -> bool:
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
        intents: list[Intent] = []
        for vid in sorted(state.villagers):
            villager = state.villagers[vid]
            memory = self.memory.get(vid)
            if memory is None:
                memory = self.memory[vid] = Memory()
            if not self._due(view, villager, memory):
                continue
            decision = self._decide(view, villager)
            if decision is None:
                memory.idle_until = state.tick + self.config.idle_ticks
                continue
            if _redundant(villager, decision.intent):
                continue
            view.remember(vid, memory, decision.target, decision.job)
            if isinstance(decision.intent, Wait):
                memory.idle_until = state.tick + self.config.idle_ticks
                continue
            intents.append(decision.intent)
        return intents

    def _due(self, view: View, villager: Villager, memory: Memory) -> bool:
        if view.tick < memory.idle_until:
            return False
        if not villager.path and villager.activity is None:
            return True
        return view.urgent(villager)

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
            if not _failed(event):
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
            memory.avoid = {t: until for t, until in memory.avoid.items() if until > state.tick}

    def to_dict(self) -> dict[str, Any]:
        return {
            "fallbacks": self.fallbacks,
            "memory": {vid: self.memory[vid].to_dict() for vid in sorted(self.memory)},
        }

    def load(self, data: Mapping[str, Any]) -> None:
        self.fallbacks = int(data.get("fallbacks", 0))
        self.memory = {str(k): Memory.from_dict(v) for k, v in data.get("memory", {}).items()}
