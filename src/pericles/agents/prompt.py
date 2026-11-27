"""Plan prompts from versioned templates, within a token budget (REQ-AGT-002/010; ADR-0018)."""

from __future__ import annotations

import math
import string
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from importlib.resources import files
from pathlib import Path

from pericles.agents.config import MINUTES_PER_HOUR, RELIEFS
from pericles.agents.plan import Catalog, Plan
from pericles.agents.view import View
from pericles.core.buildings import COMMUNAL, remaining_cost
from pericles.core.lifecycle import age_days
from pericles.core.state import Villager
from pericles.llm.types import Message

PROMPTS = Path(str(files("pericles.agents").joinpath("prompts")))
PARTS = ("system", "user", "retry")
ALWAYS = 99  # a rank: sections at this rank are never trimmed
RECIPES, NEARBY, STORES, FAMILY, BELONGINGS = 1, 2, 3, 4, 5  # ranks, first trimmed to last
# What relieves a need, by its relief; eating works only from `act_at["eat"]` (the executor).
RELIEVED_BY = {
    "eat": "eat relieves it, once it is {act_at:.0f} or more",
    "sleep": "only sleep relieves it",
    "shelter": "being at home relieves it",
}


class TemplateError(ValueError):
    """A prompt template version is missing or incomplete."""


@dataclass(frozen=True)
class Template:
    version: str
    system: string.Template
    user: string.Template
    retry: string.Template


def template_paths(version: str) -> list[Path]:
    return [PROMPTS / f"{version}.{part}.txt" for part in PARTS]


def load_template(version: str) -> Template:
    paths = template_paths(version)
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise TemplateError(
            f"prompt template {version!r}: missing {', '.join(missing)} in {PROMPTS}"
        )
    system, user, retry = (string.Template(p.read_text(encoding="utf-8")) for p in paths)
    return Template(version, system, user, retry)


@dataclass(frozen=True)
class Situation:
    triggers: tuple[str, ...]
    plan: Plan | None
    index: int
    failure: str | None


@dataclass(frozen=True)
class Section:
    title: str
    lines: tuple[str, ...]
    rank: int


def estimate_tokens(text: str, chars_per_token: float) -> int:
    return math.ceil(len(text) / chars_per_token)


def render(parts: Sequence[Section]) -> str:
    return "\n\n".join(f"## {s.title}\n" + "\n".join(s.lines) for s in parts)


def _shown(parts: Sequence[Section]) -> list[Section]:
    return [s for s in parts if s.lines or s.rank >= ALWAYS]


def fit(
    parts: Sequence[Section], budget_tokens: int, chars_per_token: float, fixed_chars: int
) -> list[Section]:
    """Drop last lines of the lowest-ranked trimmable section until the prompt fits."""
    current = list(parts)
    while math.ceil((fixed_chars + len(render(_shown(current)))) / chars_per_token) > budget_tokens:
        trimmable = [i for i, s in enumerate(current) if s.rank < ALWAYS and s.lines]
        if not trimmable:
            break
        i = min(trimmable, key=lambda j: (current[j].rank, j))
        current[i] = replace(current[i], lines=current[i].lines[:-1])
    return _shown(current)


def _bundle(bundle: Mapping[str, int]) -> str:
    return ", ".join(f"{qty} {item}" for item, qty in sorted(bundle.items())) or "nothing"


def _you(view: View, villager: Villager) -> Section:
    calendar = view.ctx.config.calendar
    if not villager.adult:
        age = "a child"
    elif age_days(view.ctx, view.state, villager) >= view.ctx.config.old_age_days:
        age = "an elder"
    else:
        age = "an adult"
    sex = villager.sex or "of no stated sex"
    when = calendar.time_of(view.state.tick)
    day = when.day % calendar.days_per_year
    hour = when.minute_of_day // MINUTES_PER_HOUR
    return Section(
        "You",
        (
            f"You are {villager.name} ({villager.id}), {sex}, {age}.",
            f"It is {when.season}, day {day + 1} of the year, hour {hour}.",
        ),
        ALWAYS,
    )


def _traits(view: View, villager: Villager) -> Section:
    traits = view.ctx.registry.traits
    lines = tuple(f"- {t}: {traits[t].description}" for t in villager.traits)
    return Section("Traits", lines or ("- none",), ALWAYS)


def _urgent(view: View, relief: str, level: float) -> bool:
    return level >= view.config.urgent_at[relief]


def _needs(view: View, villager: Villager) -> Section:
    needs = view.ctx.registry.needs
    lines = []
    for need, level in sorted(villager.needs.items()):
        relief = needs[need].relief
        line = f"- {need}: {level:.0f}/100"
        if relief in RELIEFS:
            line += " (urgent)" if _urgent(view, relief, level) else ""
            line += "; " + RELIEVED_BY[relief].format(act_at=view.config.act_at[relief])
        lines.append(line)
    if villager.damage > 0:
        lines.append(f"- injury: {villager.damage:.0f}")
    return Section("Needs", tuple(lines), ALWAYS)


def _plan(situation: Situation) -> Section:
    plan = situation.plan
    if plan is None:
        lines = ["- none yet"]
    else:
        lines = [f"Goal: {plan.goal}"]
        for n, step in enumerate(plan.steps):
            mark = "✓" if n < situation.index else "→" if n == situation.index else " "
            target = f" {step.target}" if step.target else ""
            qty = f" x{step.qty}" if step.qty else ""
            lines.append(f"{mark} {n + 1}. {step.action}{target}{qty}")
    if situation.failure:
        lines.append(f"Last step failed: {situation.failure}")
    lines.append(f"Deciding now because: {', '.join(situation.triggers)}")
    return Section("Your plan", tuple(lines), ALWAYS)


def _belongings(view: View, villager: Villager) -> Section:
    totals = villager.inventory.totals()
    carrying = ", ".join(f"{qty} {item}" for item, qty in sorted(totals.items()) if qty > 0)
    home = view.home(villager)
    lines = [
        f"Carrying: {carrying or 'nothing'}",
        f"Home: {home.kind} {home.id}" if home else "Home: none",
    ]
    lines += [
        f"Owns: {b.kind} {b.id}"
        for _, b in sorted(view.state.buildings.items())
        if villager.id in b.ownership.owners
    ]
    return Section("Belongings", tuple(lines), BELONGINGS)


def _status(view: View, member: Villager) -> str:
    needs = view.ctx.registry.needs
    urgent = sorted(
        {
            relief
            for need, level in member.needs.items()
            if (relief := needs[need].relief) in RELIEFS and _urgent(view, relief, level)
        }
    )
    status = " and ".join(f"needs {r} urgently" for r in urgent) or "fine"
    return status + (", injured" if member.damage > 0 else "")


def _family(view: View, villager: Villager) -> Section:
    state = view.state
    radius = view.config.perception_radius
    relatives: list[tuple[str, Villager]] = []
    if villager.partner in state.villagers:
        relatives.append(("partner", state.villagers[villager.partner]))
    relatives += [
        ("child", c)
        for c in sorted(state.villagers.values(), key=lambda v: v.id)
        if villager.id in c.parents
    ]
    relatives += [("parent", state.villagers[p]) for p in villager.parents if p in state.villagers]
    lines = []
    for relation, member in relatives:
        known = villager.pos.manhattan(member.pos) <= radius or (
            villager.home is not None and member.home == villager.home
        )
        status = _status(view, member) if known else "not in sight"
        lines.append(f"- {relation} {member.name} ({member.id}): {status}")
    for proposer in sorted(state.proposals):
        proposal = state.proposals[proposer]
        if proposal.target == villager.id and state.tick < proposal.expires_tick:
            other = state.villagers.get(proposer)
            if other is not None:
                lines.append(f"- {other.name} ({other.id}) has asked you to be partners")
    return Section("Family", tuple(lines) or ("- none",), FAMILY)


def _nearby(view: View, villager: Villager) -> Section:
    state, registry = view.state, view.ctx.registry
    radius = view.config.perception_radius
    entries: list[tuple[int, str]] = []
    for other in state.villagers.values():
        d = villager.pos.manhattan(other.pos)
        if other.id != villager.id and d <= radius:
            if other.activity is not None:
                doing = other.activity.ident
            else:
                doing = "walking" if other.path else "idle"
            entries.append((d, f"{other.name} ({other.id}), {d} steps away, {doing}"))
    for b in state.buildings.values():
        d = villager.pos.manhattan(b.origin)
        if d > radius:
            continue
        if b.complete:
            built = "complete"
        else:
            missing = remaining_cost(b, registry)
            built = f"site needing {_bundle(missing)}" if missing else "site ready to build"
        owned = (
            "" if b.ownership.kind == COMMUNAL else f", owned by {', '.join(b.ownership.owners)}"
        )
        entries.append((d, f"{b.kind} {b.id}, {d} steps away, {built}{owned}"))
    by_kind: dict[str, list[int]] = {}
    for node in state.nodes.values():
        d = villager.pos.manhattan(node.pos)
        if node.stock > 0 and d <= radius:
            by_kind.setdefault(node.kind, []).append(d)
    for kind, distances in by_kind.items():
        text = (
            f"{kind}: {len(distances)} within {radius} steps, nearest {min(distances)} steps away"
        )
        entries.append((min(distances), text))
    return Section("Nearby", tuple(f"- {text}" for _, text in sorted(entries)), NEARBY)


def _stores(view: View, villager: Villager) -> Section:
    totals: dict[str, int] = {}
    for building in view.stores(villager):
        for item, qty in view.held(building).items():
            totals[item] = totals.get(item, 0) + qty
    lines = tuple(f"- {item}: {qty}" for item, qty in sorted(totals.items()) if qty > 0)
    return Section("Stores you may use", lines or ("- none you may use",), STORES)


def _knowledge(view: View, villager: Villager, catalog: Catalog) -> Section:
    registry, ctx, state = view.ctx.registry, view.ctx, view.state
    lines = [
        f"- {r.id}: {_bundle(r.inputs)} -> {_bundle(r.outputs)} at a {r.building}"
        for r in sorted(registry.recipes.values(), key=lambda r: r.id)
        if ctx.available(state, villager, r.id)
    ]
    lines += [
        f"- {b.id} costs {_bundle(b.cost)}"
        for b in sorted(registry.buildings.values(), key=lambda b: b.id)
        if ctx.available(state, villager, b.id)
    ]
    lines += [
        f"- {t} costs {_bundle(registry.technologies[t].cost)} at a "
        f"{registry.technologies[t].building}"
        for t in catalog.targets.get("research", ())
    ]
    return Section("Recipes and costs", tuple(lines), RECIPES)


def _actions(catalog: Catalog) -> Section:
    return Section("Actions you can use", tuple(catalog.lines()), ALWAYS)


def sections(
    view: View, villager: Villager, situation: Situation, catalog: Catalog
) -> list[Section]:
    return [
        _you(view, villager),
        _traits(view, villager),
        _needs(view, villager),
        _plan(situation),
        _belongings(view, villager),
        _family(view, villager),
        _nearby(view, villager),
        _stores(view, villager),
        _knowledge(view, villager, catalog),
        _actions(catalog),
    ]


def plan_messages(
    view: View, villager: Villager, situation: Situation, catalog: Catalog, template: Template
) -> tuple[Message, Message]:
    config = view.config
    system = template.system.substitute(name=villager.name, max_steps=config.max_plan_steps)
    frame = template.user.substitute(sections="")
    fixed = len(system) + 1 + len(frame)  # the joining newline as estimate_tokens counts it
    kept = fit(
        sections(view, villager, situation, catalog),
        config.prompt_budget_tokens,
        config.chars_per_token,
        fixed,
    )
    user = template.user.substitute(sections=render(kept))
    return Message("system", system), Message("user", user)
