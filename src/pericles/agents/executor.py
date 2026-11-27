"""Turns plan steps into engine intents, without LLM calls (REQ-AGT-004; ADR-0018 §3)."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from pericles.agents import rules
from pericles.agents.config import ticks_for_hours
from pericles.agents.plan import Step
from pericles.agents.view import CONSTRUCT, PLACE, Decision, View
from pericles.core.buildings import COMMUNAL, Building, footprint, remaining_cost
from pericles.core.intents import (
    AcceptCouple,
    Construct,
    Craft,
    Deliver,
    Deposit,
    Eat,
    PlaceBuilding,
    ProposeCouple,
    Research,
    SetHome,
    Sleep,
    Take,
    Wait,
)
from pericles.core.inventory import capacity_for
from pericles.core.life import SLEEP
from pericles.core.state import Villager

EAT = "eat"
COUNTED = ("gather", "take", "store")  # steps measured against the held count at their start


@dataclass
class Progress:
    """How far the current step got; saved in snapshots (ADR-0018 §7)."""

    start: int = 0
    base: int = 0
    issued: bool = False
    count: int = 0
    site: str | None = None
    origin: tuple[int, int] | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["origin"] = None if self.origin is None else list(self.origin)
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Progress:
        origin = data["origin"]
        site = data["site"]
        return cls(
            start=int(data["start"]),
            base=int(data["base"]),
            issued=bool(data["issued"]),
            count=int(data["count"]),
            site=None if site is None else str(site),
            origin=None if origin is None else (int(origin[0]), int(origin[1])),
        )


@dataclass(frozen=True)
class Outcome:
    """A decision to send now, the step done, the step failed, or (all empty) carry on."""

    decision: Decision | None = None
    done: bool = False
    failed: str | None = None


DONE = Outcome(done=True)
CARRY_ON = Outcome()
Handler = Callable[[View, Villager, Step, Progress], Outcome]


def act(decision: Decision) -> Outcome:
    return Outcome(decision=decision)


def fail(reason: str) -> Outcome:
    return Outcome(failed=reason)


def begin(tick: int, villager: Villager, step: Step) -> Progress:
    counted = step.action in COUNTED and step.target is not None
    base = villager.inventory.count(step.target) if counted and step.target else 0
    return Progress(start=tick, base=base)


def advance(view: View, villager: Villager, step: Step, progress: Progress) -> Outcome:
    return HANDLERS[step.action](view, villager, step, progress)


def _gather(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    item = str(step.target)
    if step.qty is not None and villager.inventory.count(item) - p.base >= step.qty:
        return DONE
    ranked = sorted(
        rules.jobs(view, villager, [item]),
        key=lambda a: (-rules.skill_score(view, villager, a), a.id),
    )
    if not ranked:
        return fail(f"no way to gather {item} now")
    if not any(rules.fits_output(view, villager, a) for a in ranked):
        return DONE if step.qty is None else fail(f"no room to carry more {item}")
    decision = rules.first_reachable(view, villager, ranked)
    return act(decision) if decision is not None else fail(f"no {item} source within reach")


def _fetch(view: View, villager: Villager, foods: Sequence[str]) -> Decision | None:
    for building in view.stores(villager):
        stock = view.held(building)
        for food in foods:
            qty = min(stock.get(food, 0), rules.portion(view, villager, food))
            if qty <= 0:
                continue
            move = view.go(villager, view.tiles(building))
            if move is not None:
                return Decision(move, target=building.id)
            return Decision(Take(villager.id, building.id, food, qty), target=building.id)
    return None


def _eat(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    if p.issued:
        return DONE
    foods = (step.target,) if step.target is not None else view.foods
    items = view.ctx.registry.items
    level = view.level(villager, EAT)
    for food in foods:
        have = villager.inventory.count(food)
        if have:
            p.issued = True
            qty = min(have, max(1, math.ceil(level / items[food].nutrition)))
            return act(Decision(Eat(villager.id, food, qty)))
    fetch = _fetch(view, villager, foods)
    if fetch is not None:
        return act(fetch)
    return fail("no food to eat" if step.target is None else f"no {step.target} to eat")


def _sleep(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    if p.issued:
        asleep = villager.activity is not None and villager.activity.kind == SLEEP
        return CARRY_ON if asleep else DONE
    home = view.home(villager)
    if home is not None and not view.avoided(villager, home.id) and not view.at_home(villager):
        move = view.go(villager, view.tiles(home))
        if move is not None:
            return act(Decision(move, target=home.id))
    p.issued = True
    return act(Decision(Sleep(villager.id)))


def _rest(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    hours = step.qty if step.qty is not None else 1
    if view.tick >= p.start + ticks_for_hours(view.ctx.config.calendar.tick_minutes, hours):
        return DONE
    return act(Decision(Wait(villager.id)))


def _go_home(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    home = view.home(villager)
    if home is None:
        return fail("no home")
    if view.at_home(villager):
        return DONE
    move = view.go(villager, view.tiles(home))
    return DONE if move is None else act(Decision(move, target=home.id))


def _move_in(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    if p.issued:
        return DONE if villager.home is not None else fail("could not move in")
    house = view.couple_house(villager) if villager.partner is not None else None
    house = house if house is not None else view.house_for(villager)
    if house is None:
        return fail("no house with a free bed")
    if house.id == villager.home:
        return DONE
    p.issued = True
    return act(Decision(SetHome(villager.id, house.id), target=house.id))


def _court(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    target = str(step.target)
    if villager.partner == target:
        return DONE
    other = view.state.villagers.get(target)
    if (
        villager.partner is not None
        or other is None
        or not other.adult
        or other.partner is not None
        or not rules.compatible(view, villager, other)
    ):
        return fail(f"{target} is not a possible partner")
    proposal = view.state.proposals.get(target)
    if (
        proposal is not None
        and proposal.target == villager.id
        and proposal.expires_tick > view.tick
    ):
        return act(Decision(AcceptCouple(villager.id, target), target=target))
    if p.issued:
        return DONE
    p.issued = True
    return act(Decision(ProposeCouple(villager.id, target), target=target))


def _store(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    if step.target is None:
        extra = rules.surplus(view, villager)
        if not extra:
            return DONE
        item, qty = extra[0]
    else:
        item = step.target
        held = villager.inventory.count(item)
        stored = p.base - held
        if held == 0 or (step.qty is not None and stored >= step.qty):
            return DONE
        qty = held if step.qty is None else min(held, step.qty - stored)
    for building in view.stores(villager):
        room = view.room(building)
        if room <= 0:
            continue
        move = view.go(villager, view.tiles(building))
        if move is not None:
            return act(Decision(move, target=building.id))
        deposit = Deposit(villager.id, building.id, item, min(qty, room))
        return act(Decision(deposit, target=building.id))
    return fail("no store with room")


def _take(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    item = str(step.target)
    taken = villager.inventory.count(item) - p.base
    if step.qty is not None and taken >= step.qty:
        return DONE
    registry = view.ctx.registry
    room = capacity_for(registry, villager.inventory, item, view.ctx.config.carry_limit)
    if room <= 0:
        return DONE if step.qty is None and taken > 0 else fail(f"no room to carry {item}")
    left = room if step.qty is None else min(room, step.qty - taken)
    for building in view.stores(villager):
        stock = view.held(building).get(item, 0)
        if stock <= 0:
            continue
        move = view.go(villager, view.tiles(building))
        if move is not None:
            return act(Decision(move, target=building.id))
        return act(
            Decision(Take(villager.id, building.id, item, min(left, stock)), target=building.id)
        )
    if step.qty is None and taken > 0:
        return DONE
    return fail(f"no {item} in a store you may use")


def workplace(view: View, villager: Villager, kind: str) -> Building | None:
    """The nearest complete building of `kind`, by Manhattan distance then id."""
    complete = [b for b in view.state.buildings.values() if b.kind == kind and b.complete]
    return min(complete, key=lambda b: (villager.pos.manhattan(b.origin), b.id), default=None)


def _missing(villager: Villager, bundle: Mapping[str, int]) -> str:
    have = villager.inventory
    return ", ".join(
        f"{qty - have.count(item)} {item}"
        for item, qty in sorted(bundle.items())
        if have.count(item) < qty
    )


def _site(view: View, villager: Villager, kind: str, p: Progress) -> Building | Outcome:
    """The site this step works on, or the outcome of finding or placing one."""
    if p.site is not None:
        site = view.state.buildings.get(p.site)
        return site if site is not None else fail(f"the {kind} site is gone")
    if p.origin is not None:
        placed = next(
            (b for b in view.sites() if b.kind == kind and (b.origin.x, b.origin.y) == p.origin),
            None,
        )
        if placed is None:
            return fail(f"could not place a {kind}")
        p.site = placed.id
        return placed
    joined = next(
        (b for b in view.sites() if b.kind == kind and not view.avoided(villager, b.id)), None
    )
    if joined is not None:
        p.site = joined.id
        return joined
    origin = view.free_origin(kind, villager.pos)
    if origin is None:
        return fail(f"no free place for a {kind}")
    size = view.ctx.registry.buildings[kind].footprint
    move = view.go(villager, footprint(origin, size))
    if move is not None:
        return act(Decision(move, target=PLACE + kind))
    p.origin = (origin.x, origin.y)
    place = PlaceBuilding(villager.id, kind, origin, ownership=COMMUNAL)
    return act(Decision(place, target=PLACE + kind))


def _build(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    kind = str(step.target)
    site = _site(view, villager, kind, p)
    if isinstance(site, Outcome):
        return site
    if site.complete:
        return DONE
    remaining = remaining_cost(site, view.ctx.registry)
    for item, qty in remaining.items():
        have = villager.inventory.count(item)
        if have:
            move = view.go(villager, view.tiles(site))
            if move is not None:
                return act(Decision(move, target=site.id))
            deliver = Deliver(villager.id, site.id, item, min(have, qty))
            return act(Decision(deliver, target=site.id))
    if remaining:
        needs = ", ".join(f"{qty} {item}" for item, qty in remaining.items())
        return fail(f"the {kind} still needs {needs}")
    move = view.go(villager, view.tiles(site))
    if move is not None:
        return act(Decision(move, target=site.id, job=CONSTRUCT))
    return act(Decision(Construct(villager.id, site.id), target=site.id, job=CONSTRUCT))


def _work_at(
    view: View,
    villager: Villager,
    kind: str,
    make: Callable[[str], Decision],
    p: Progress,
) -> Outcome:
    building = workplace(view, villager, kind)
    if building is None:
        return fail(f"no {kind} to work at")
    move = view.go(villager, view.tiles(building))
    if move is not None:
        return act(Decision(move, target=building.id))
    p.issued = True
    return act(make(building.id))


def _craft(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    recipe = view.ctx.registry.recipes[str(step.target)]
    if p.issued and villager.activity is not None:
        return CARRY_ON
    output = min(recipe.outputs)  # a rejected or interrupted craft leaves this count unchanged
    if p.issued:
        if villager.inventory.count(output) > p.base:
            p.count += 1
        p.issued = False
    if p.count >= (step.qty if step.qty is not None else 1):
        return DONE
    if not villager.inventory.has(recipe.inputs):
        return fail(f"{recipe.id} needs {_missing(villager, recipe.inputs)}")

    def make(building: str) -> Decision:
        p.base = villager.inventory.count(output)
        return Decision(Craft(villager.id, recipe.id, building), target=building, job=recipe.id)

    return _work_at(view, villager, recipe.building, make, p)


def _research(view: View, villager: Villager, step: Step, p: Progress) -> Outcome:
    tech = view.ctx.registry.technologies[str(step.target)]
    known = view.state.village_knowledge if tech.scope == "village" else villager.knowledge
    if tech.id in known:
        return DONE
    if p.issued and villager.activity is not None:
        return CARRY_ON
    if not villager.inventory.has(tech.cost):
        return fail(f"{tech.id} needs {_missing(villager, tech.cost)}")

    def make(building: str) -> Decision:
        return Decision(Research(villager.id, tech.id, building), target=building)

    return _work_at(view, villager, tech.building, make, p)


HANDLERS: dict[str, Handler] = {
    "gather": _gather,
    "eat": _eat,
    "sleep": _sleep,
    "rest": _rest,
    "go_home": _go_home,
    "move_in": _move_in,
    "court": _court,
    "store": _store,
    "take": _take,
    "build": _build,
    "craft": _craft,
    "research": _research,
}
