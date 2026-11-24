"""The scripted minds: utility AIs built from rules (REQ-AGT-008, REQ-SIM-016 AC1; ADR-0016)."""

from __future__ import annotations

from collections.abc import Mapping

from pericles.agents import rules
from pericles.agents.config import AgentConfig
from pericles.agents.controller import Controller, Mind
from pericles.agents.rules import Rule
from pericles.agents.view import Decision, View
from pericles.core.context import Context
from pericles.core.state import Villager


class ScriptedMind:
    """Keeps an adult alive and productive; the baseline and the LLM fallback."""

    rules: tuple[Rule, ...] = (
        rules.eat,
        rules.sleep,
        rules.shelter,
        rules.couple,
        rules.home,
        rules.deliver,
        rules.deposit,
        rules.build,
        rules.work,
    )

    def decide(self, view: View, villager: Villager) -> Decision:
        for rule in self.rules:
            decision = rule(view, villager)
            if decision is not None:
                return decision
        return rules.wait(view, villager)


class ChildMind(ScriptedMind):
    """Children: stay near a parent, eat, light gathering (REQ-SIM-016 AC1)."""

    rules: tuple[Rule, ...] = (
        rules.child_eat,
        rules.sleep,
        rules.shelter,
        rules.follow,
        rules.deposit,
        rules.forage,
    )


def scripted_controller(
    ctx: Context, config: AgentConfig, minds: Mapping[str, Mind] | None = None
) -> Controller:
    """The controller every run uses: scripted adults and children, plus any model minds."""
    return Controller(ctx, config, ScriptedMind(), ChildMind(), minds)
