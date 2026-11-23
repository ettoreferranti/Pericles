"""What every gameplay rule needs: content, parameters and locked content (ADR-0014)."""

from __future__ import annotations

from dataclasses import dataclass

from pericles.core.config import EngineConfig
from pericles.core.content.registry import Registry
from pericles.core.events import EventSink
from pericles.core.intents import Intent
from pericles.core.state import Villager, WorldState


@dataclass(frozen=True)
class Context:
    registry: Registry
    config: EngineConfig
    locked: frozenset[str]

    @classmethod
    def build(cls, registry: Registry, config: EngineConfig) -> Context:
        locked: set[str] = set()
        for tech in registry.technologies.values():
            locked.update(tech.unlocks_recipes)
            locked.update(tech.unlocks_buildings)
        return cls(registry, config, frozenset(locked))

    def available(self, state: WorldState, villager: Villager, ident: str) -> bool:
        """A recipe or building is available unless a technology unlocks it and it is unknown."""
        return ident not in self.locked or knows(state, villager, ident)


def knows(state: WorldState, villager: Villager, ident: str) -> bool:
    return ident in villager.knowledge or ident in state.village_knowledge


def reject(sink: EventSink, intent: Intent, reason: str) -> None:
    sink.emit("intent_rejected", actor=intent.actor, intent=intent.kind, reason=reason)
