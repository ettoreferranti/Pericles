"""Plan output and the valid-action catalog (REQ-AGT-003; ADR-0018 §3)."""

from __future__ import annotations

import typing
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pericles.agents import rules
from pericles.agents.view import View
from pericles.core.state import Villager

Action = Literal[
    "gather",
    "eat",
    "sleep",
    "rest",
    "go_home",
    "move_in",
    "court",
    "store",
    "take",
    "build",
    "craft",
    "research",
]
ACTIONS: tuple[str, ...] = typing.get_args(Action)
NO_TARGET = frozenset({"sleep", "rest", "go_home", "move_in"})
OPTIONAL_TARGET = frozenset({"eat", "store"})
UNLISTED = frozenset({"store"})  # any carried item; the list would only repeat belongings
USAGE = {
    "gather": "gather <item> [qty]: collect a raw item from the land nearby",
    "eat": "eat [food]: eat food you carry, or fetch it from a store you may use",
    "sleep": "sleep: go home if you have one, and sleep until rested",
    "rest": "rest [hours]: stay where you are",
    "go_home": "go_home: walk home",
    "move_in": "move_in: take a bed in a house with room",
    "court": "court <villager>: ask to become partners, or accept their proposal",
    "store": "store [item] [qty]: put items you carry into a store you may use",
    "take": "take <item> [qty]: take items from a store you may use",
    "build": "build <building>: start or continue a building; carry its materials to it",
    "craft": "craft <recipe> [qty]: make a recipe at its workplace, qty times",
    "research": "research <technology>: study a technology at its workplace",
}


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: Action
    target: str | None = None
    qty: int | None = Field(default=None, ge=1)


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    goal: str = Field(min_length=1)
    steps: tuple[Step, ...] = Field(min_length=1)
    reason: str


@dataclass(frozen=True)
class Catalog:
    """Each action's valid targets for one villager now; `NO_TARGET` actions take none."""

    targets: Mapping[str, tuple[str, ...]]

    def lines(self) -> list[str]:
        out = []
        for action in ACTIONS:
            valid = self.targets.get(action, ())
            needs_target = action not in NO_TARGET and action not in OPTIONAL_TARGET
            if needs_target and not valid:
                continue
            line = f"- {USAGE[action]}"
            if valid and action not in UNLISTED:
                line += f"; targets: {', '.join(valid)}"
            out.append(line)
        return out


def catalog_for(view: View, villager: Villager) -> Catalog:
    state, ctx = view.state, view.ctx
    registry = ctx.registry
    radius = view.config.perception_radius
    gatherable = sorted(
        {item for action in rules.jobs(view, villager, registry.items) for item in action.outputs}
    )
    stocked = sorted(
        {
            item
            for building in view.stores(villager)
            for item, qty in view.held(building).items()
            if qty > 0
        }
    )
    partners: tuple[str, ...] = ()
    if villager.partner is None:
        partners = tuple(
            sorted(
                other.id
                for other in state.villagers.values()
                if other.id != villager.id
                and other.adult
                and other.partner is None
                and villager.pos.manhattan(other.pos) <= radius
                and rules.compatible(view, villager, other)
            )
        )
    researchable = sorted(
        tech.id
        for tech in registry.technologies.values()
        if tech.id
        not in (state.village_knowledge if tech.scope == "village" else villager.knowledge)
    )
    targets: dict[str, tuple[str, ...]] = {action: () for action in NO_TARGET}
    targets |= {
        "gather": tuple(gatherable),
        "eat": tuple(view.foods),
        "store": tuple(sorted(registry.items)),
        "take": tuple(stocked),
        "court": partners,
        "build": tuple(sorted(k for k in registry.buildings if ctx.available(state, villager, k))),
        "craft": tuple(sorted(r for r in registry.recipes if ctx.available(state, villager, r))),
        "research": tuple(researchable),
    }
    return Catalog(targets)


def _listing(valid: tuple[str, ...]) -> str:
    return ", ".join(valid) if valid else "none right now"


def check_plan(plan: Plan, catalog: Catalog, max_steps: int) -> str | None:
    """None if every step's action and target is in `catalog`; else the first problem."""
    if len(plan.steps) > max_steps:
        return f"steps: at most {max_steps} steps, got {len(plan.steps)}"
    for i, step in enumerate(plan.steps):
        where = f"steps[{i}].target"
        valid = catalog.targets.get(step.action, ())
        if step.action in NO_TARGET:
            if step.target is not None:
                return f"{where}: {step.action} takes no target"
            continue
        if step.target is None:
            if step.action in OPTIONAL_TARGET:
                continue
            return f"{where}: {step.action} needs a target; valid: {_listing(valid)}"
        if step.target not in valid:
            return (
                f"{where}: {step.target!r} is not a valid target for {step.action}; "
                f"valid: {_listing(valid)}"
            )
    return None
