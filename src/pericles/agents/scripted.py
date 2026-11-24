"""The scripted minds: utility AIs built from rules (REQ-AGT-008, REQ-SIM-016 AC1; ADR-0016)."""

from __future__ import annotations

from pericles.agents import rules
from pericles.agents.rules import Rule
from pericles.agents.view import Decision, View
from pericles.core.state import Villager


class ScriptedMind:
    """Keeps an adult alive and productive; the baseline and the LLM fallback."""

    rules: tuple[Rule, ...] = (rules.eat, rules.sleep, rules.shelter)

    def decide(self, view: View, villager: Villager) -> Decision:
        for rule in self.rules:
            decision = rule(view, villager)
            if decision is not None:
                return decision
        return rules.wait(view, villager)
