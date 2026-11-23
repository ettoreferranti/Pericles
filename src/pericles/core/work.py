"""Work: actions, tools, skills and interruption (REQ-SIM-008, -010, -014; ADR-0014)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping

from pericles.core.buildings import Building, building_tiles, near
from pericles.core.context import Context, knows, reject
from pericles.core.events import EventSink
from pericles.core.intents import Craft, Intent, Research, StartAction
from pericles.core.inventory import (
    EPSILON as EPSILON,
)
from pericles.core.inventory import (
    Inventory,
    Tool,
    bundle_weight,
    capacity_for,
    fits,
    transfer,
)
from pericles.core.modifiers import Modifier, Op, Scope, Target, resolve
from pericles.core.state import Activity, Villager, WorldState

WORKPLACE_KINDS = ("recipe", "research")

Finisher = Callable[[Context, WorldState, Villager, Activity, EventSink], None]


def used_tools(
    ctx: Context,
    villager: Villager,
    kind: str,
    ident: str,
    tags: Iterable[str],
    required: Iterable[str],
) -> list[Tool] | None:
    """The tool instances a piece of work uses, or None if a required tool is missing.

    One instance per required tag (the first, most worn, holder of that tag), plus the first
    instance of every other held tool item that has a modifier targeting the work.
    """
    registry = ctx.registry
    tag_tuple = tuple(tags)
    used: list[Tool] = []
    for tag in sorted(required):
        tool = next(
            (t for t in villager.inventory.tools if tag in registry.items[t.item].tags), None
        )
        if tool is None:
            return None
        if all(tool is not other for other in used):
            used.append(tool)
    seen = {tool.item for tool in used}
    for tool in villager.inventory.tools:
        if tool.item in seen:
            continue
        seen.add(tool.item)
        targets = (m.target for m in registry.items[tool.item].modifiers)
        if any(Target(t.kind, t.id, t.tag).matches(kind, ident, tag_tuple) for t in targets):
            used.append(tool)
    return used


def work_speed(
    ctx: Context,
    state: WorldState,
    villager: Villager,
    *,
    kind: str,
    ident: str,
    tags: Iterable[str],
    skill: str | None,
    tools: Iterable[Tool],
    attribute: str = "work_speed",
    building: str | None = None,
) -> float:
    """World, tool, trait and skill modifiers folded over a base speed of 1 (ADR-0014 §2)."""
    registry = ctx.registry
    modifiers = list(state.modifiers)
    for tool in tools:
        modifiers.extend(
            Modifier.from_def(m, f"item:{tool.item}") for m in registry.items[tool.item].modifiers
        )
    for trait in villager.traits:
        modifiers.extend(
            Modifier.from_def(m, f"trait:{trait}") for m in registry.traits[trait].modifiers
        )
    if skill is not None:
        bonus = villager.skills.get(skill, 0.0) * ctx.config.skill_speed_per_level
        modifiers.append(Modifier(Target(kind, ident), attribute, Op.ADD, bonus, f"skill:{skill}"))
    return resolve(
        modifiers,
        kind=kind,
        ident=ident,
        attribute=attribute,
        base=1.0,
        tick=state.tick,
        tags=tags,
        villager=villager.id,
        building=building,
    ).value


def start_work(
    ctx: Context,
    villager: Villager,
    intent: Intent,
    sink: EventSink,
    *,
    kind: str,
    ident: str,
    target: str | None,
    work: float,
    speed: float,
    inputs: Mapping[str, int],
    done: float = 0.0,
) -> None:
    """Reserve the inputs, stop any movement and start the activity."""
    if speed <= 0:
        return reject(sink, intent, "cannot_work")
    reserved = Inventory()
    for item, qty in sorted(inputs.items()):
        transfer(ctx.registry, villager.inventory, reserved, item, qty)
    if villager.path:
        villager.path = []
        villager.move_progress = 0.0
        sink.emit("stopped", actor=villager.id, at=list(villager.pos))
    villager.activity = Activity(kind, ident, target, float(work), done, speed, reserved)
    ticks = math.ceil((work - done - EPSILON) / speed)
    sink.emit("work_started", actor=villager.id, work=kind, ident=ident, target=target, ticks=ticks)


def interrupt(
    ctx: Context, villager: Villager, sink: EventSink, cause: str, reason: str | None = None
) -> None:
    """Stop the current work; reserved inputs return to the inventory (REQ-SIM-008 AC3)."""
    activity = villager.activity
    if activity is None:
        return
    for item, qty in sorted(activity.reserved.totals().items()):
        transfer(ctx.registry, activity.reserved, villager.inventory, item, qty)
    villager.activity = None
    sink.emit(
        "work_interrupted",
        actor=villager.id,
        work=activity.kind,
        ident=activity.ident,
        target=activity.target,
        cause=cause,
        reason=reason,
    )


def start_action(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, StartAction)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    action = registry.actions.get(intent.action)
    if action is None:
        return reject(sink, intent, "unknown_action")
    blocked = ctx.config.calendar.season_at(state.tick).blocked_tags
    if any(tag in blocked for tag in action.tags):
        return reject(sink, intent, "season")
    requires = action.requires
    if requires.knowledge and not knows(state, villager, action.id):
        return reject(sink, intent, "missing_knowledge")
    if requires.skill is not None and villager.skills.get(requires.skill, 0.0) < requires.min_skill:
        return reject(sink, intent, "skill_too_low")
    tools = used_tools(ctx, villager, "action", action.id, action.tags, requires.tools)
    if tools is None:
        return reject(sink, intent, "missing_tool")
    if not villager.inventory.has(action.inputs):
        return reject(sink, intent, "missing_inputs")
    location = action.location
    target: str | None = None
    building_id: str | None = None
    if location.node is not None:
        node = state.nodes.get(intent.target) if intent.target is not None else None
        if node is None or node.kind != location.node:
            return reject(sink, intent, "bad_target")
        if not near(villager.pos, [node.pos]):
            return reject(sink, intent, "not_at_location")
        if node.stock == 0:
            return reject(sink, intent, "depleted")
        target = node.id
    if location.building is not None:
        building = state.buildings.get(intent.target) if intent.target is not None else None
        if building is None or building.kind != location.building:
            return reject(sink, intent, "bad_target")
        if not building.complete:
            return reject(sink, intent, "incomplete")
        if not near(villager.pos, building_tiles(building, registry)):
            return reject(sink, intent, "not_at_location")
        target = building_id = building.id
    if location.terrains and state.tilemap.terrain_at(villager.pos) not in location.terrains:
        return reject(sink, intent, "not_at_location")
    freed = bundle_weight(registry, action.inputs)
    limit = ctx.config.carry_limit
    room = [
        capacity_for(registry, villager.inventory, item, limit, freed) for item in action.outputs
    ]
    if room and not any(room):
        return reject(sink, intent, "carry_limit")
    speed = work_speed(
        ctx,
        state,
        villager,
        kind="action",
        ident=action.id,
        tags=action.tags,
        skill=action.skill,
        tools=tools,
        building=building_id,
    )
    return start_work(
        ctx,
        villager,
        intent,
        sink,
        kind="action",
        ident=action.id,
        target=target,
        work=action.duration_ticks,
        speed=speed,
        inputs=action.inputs,
    )


def workplace(
    ctx: Context,
    state: WorldState,
    villager: Villager,
    intent: Intent,
    building_id: str,
    kind: str,
    sink: EventSink,
) -> Building | None:
    """A complete building of `kind`, within reach and with a free workplace, or None."""
    building = state.buildings.get(building_id)
    if building is None or building.kind != kind:
        problem = "bad_target"
    elif not building.complete:
        problem = "incomplete"
    elif not near(villager.pos, building_tiles(building, ctx.registry)):
        problem = "not_at_location"
    elif _workers(state, building.id) >= ctx.registry.buildings[kind].workers:
        problem = "building_full"
    else:
        return building
    reject(sink, intent, problem)
    return None


def _workers(state: WorldState, building_id: str) -> int:
    return sum(
        1
        for villager in state.villagers.values()
        if villager.activity is not None
        and villager.activity.kind in WORKPLACE_KINDS
        and villager.activity.target == building_id
    )


def start_recipe(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Craft)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    recipe = registry.recipes.get(intent.recipe)
    if recipe is None:
        return reject(sink, intent, "unknown_recipe")
    if not ctx.available(state, villager, recipe.id):
        return reject(sink, intent, "locked")
    building = workplace(ctx, state, villager, intent, intent.building, recipe.building, sink)
    if building is None:
        return None
    if not villager.inventory.has(recipe.inputs):
        return reject(sink, intent, "missing_inputs")
    freed = bundle_weight(registry, recipe.inputs)
    if not fits(registry, villager.inventory, recipe.outputs, ctx.config.carry_limit, freed):
        return reject(sink, intent, "carry_limit")
    tools = used_tools(ctx, villager, "recipe", recipe.id, (), ()) or []
    speed = work_speed(
        ctx,
        state,
        villager,
        kind="recipe",
        ident=recipe.id,
        tags=(),
        skill=recipe.skill,
        tools=tools,
        building=building.id,
    )
    return start_work(
        ctx,
        villager,
        intent,
        sink,
        kind="recipe",
        ident=recipe.id,
        target=building.id,
        work=recipe.work_ticks,
        speed=speed,
        inputs=recipe.inputs,
    )


def start_research(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Research)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    tech = registry.technologies.get(intent.technology)
    if tech is None:
        return reject(sink, intent, "unknown_technology")
    known = state.village_knowledge if tech.scope == "village" else villager.knowledge
    if tech.id in known:
        return reject(sink, intent, "already_known")
    building = workplace(ctx, state, villager, intent, intent.building, tech.building, sink)
    if building is None:
        return None
    if not villager.inventory.has(tech.cost):
        return reject(sink, intent, "missing_inputs")
    tags = registry.buildings[building.kind].tags
    tools = used_tools(ctx, villager, "building", building.kind, tags, ()) or []
    speed = work_speed(
        ctx,
        state,
        villager,
        kind="building",
        ident=building.kind,
        tags=tags,
        skill=None,
        tools=tools,
        attribute="research_speed",
        building=building.id,
    )
    return start_work(
        ctx,
        villager,
        intent,
        sink,
        kind="research",
        ident=tech.id,
        target=building.id,
        work=tech.research_ticks,
        speed=speed,
        inputs=tech.cost,
    )


def finish(
    ctx: Context,
    villager: Villager,
    activity: Activity,
    sink: EventSink,
    *,
    created: Mapping[str, int],
    skill: str | None,
    tools: list[Tool],
) -> None:
    """Consume the reserved inputs, train the skill, wear the given tools and report.

    `tools` are the instances used, chosen before the outputs were added, so a tool the work
    itself produced is never worn by it.
    """
    config = ctx.config
    destroyed = dict(sorted(activity.reserved.totals().items()))
    if skill is not None:
        villager.skills[skill] = min(
            config.max_skill, villager.skills.get(skill, 0.0) + config.skill_practice
        )
    villager.activity = None
    sink.emit(
        "work_done",
        actor=villager.id,
        work=activity.kind,
        ident=activity.ident,
        target=activity.target,
        created=dict(sorted(created.items())),
        destroyed=destroyed,
    )
    for tool in tools:
        tool.durability -= 1
        if tool.durability <= 0:
            villager.inventory.tools.remove(tool)
            sink.emit("tool_broken", actor=villager.id, item=tool.item, destroyed={tool.item: 1})


def _finish_action(
    ctx: Context, state: WorldState, villager: Villager, activity: Activity, sink: EventSink
) -> None:
    registry = ctx.registry
    action = registry.actions[activity.ident]
    node = None
    if action.location.node is not None:
        assert activity.target is not None
        node = state.nodes[activity.target]
        if node.stock == 0:
            interrupt(ctx, villager, sink, cause="engine", reason="depleted")
            return
    tools = used_tools(ctx, villager, "action", action.id, action.tags, action.requires.tools)
    assert tools is not None  # a working villager's inventory cannot have lost a required tool
    yields = None if node is None else registry.nodes[node.kind].yields
    created: dict[str, int] = {}
    for item in sorted(action.outputs, key=lambda name: (name != yields, name)):
        qty = action.outputs[item]
        if node is not None and item == yields:
            qty = min(qty, node.stock)
        qty = min(qty, capacity_for(registry, villager.inventory, item, ctx.config.carry_limit))
        if qty > 0:
            villager.inventory.add(registry, item, qty)
            created[item] = qty
            if node is not None and item == yields:
                node.stock -= qty
    finish(
        ctx,
        villager,
        activity,
        sink,
        created=created,
        skill=action.skill,
        tools=tools,
    )


def _finish_recipe(
    ctx: Context, state: WorldState, villager: Villager, activity: Activity, sink: EventSink
) -> None:
    registry = ctx.registry
    recipe = registry.recipes[activity.ident]
    tools = used_tools(ctx, villager, "recipe", recipe.id, (), ()) or []
    for item, qty in sorted(recipe.outputs.items()):
        villager.inventory.add(registry, item, qty)
    finish(
        ctx,
        villager,
        activity,
        sink,
        created=recipe.outputs,
        skill=recipe.skill,
        tools=tools,
    )


def _finish_research(
    ctx: Context, state: WorldState, villager: Villager, activity: Activity, sink: EventSink
) -> None:
    registry = ctx.registry
    tech = registry.technologies[activity.ident]
    village = tech.scope == "village"
    known = state.village_knowledge if village else villager.knowledge
    if tech.id in known:
        interrupt(ctx, villager, sink, cause="engine", reason="already_known")
        return
    known.update((tech.id, *tech.unlocks_recipes, *tech.unlocks_buildings))
    scope = Scope() if village else Scope(villager=villager.id)
    source = f"technology:{tech.id}"
    state.modifiers = state.modifiers + tuple(
        Modifier.from_def(m, source, scope) for m in tech.modifiers
    )
    assert activity.target is not None
    kind = state.buildings[activity.target].kind
    tools = used_tools(ctx, villager, "building", kind, registry.buildings[kind].tags, ()) or []
    finish(
        ctx,
        villager,
        activity,
        sink,
        created={},
        skill=None,
        tools=tools,
    )
    sink.emit("technology_learned", actor=villager.id, technology=tech.id, scope=tech.scope)


_FINISHERS: dict[str, Finisher] = {
    "action": _finish_action,
    "recipe": _finish_recipe,
    "research": _finish_research,
}


def complete(ctx: Context, state: WorldState, villager: Villager, sink: EventSink) -> None:
    activity = villager.activity
    assert activity is not None
    _FINISHERS[activity.kind](ctx, state, villager, activity, sink)
