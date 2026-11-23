"""Construction sites, building work and stores (REQ-SIM-009, REQ-SIM-004, REQ-ECO-001)."""

from __future__ import annotations

from pericles.core.buildings import (
    Building,
    Ownership,
    building_tiles,
    footprint,
    near,
    remaining_cost,
    storage_capacity,
)
from pericles.core.context import Context, reject
from pericles.core.events import EventSink
from pericles.core.geometry import Coord
from pericles.core.intents import Construct, Deliver, Deposit, Intent, PlaceBuilding, Take
from pericles.core.inventory import fits, transfer
from pericles.core.state import Villager, WorldState
from pericles.core.work import EPSILON, finish, start_work, used_tools, work_speed


def blocked_tiles(ctx: Context, state: WorldState) -> frozenset[Coord]:
    """Footprint tiles of buildings and sites without an entrance (REQ-SIM-004 AC3)."""
    registry = ctx.registry
    return frozenset(
        tile
        for building in state.buildings.values()
        if not registry.buildings[building.kind].entrance
        for tile in building_tiles(building, registry)
    )


def _occupied(ctx: Context, state: WorldState) -> set[Coord]:
    tiles = {tile for b in state.buildings.values() for tile in building_tiles(b, ctx.registry)}
    tiles.update(node.pos for node in state.nodes.values())
    return tiles


def _ownership(state: WorldState, intent: PlaceBuilding) -> Ownership | None:
    if any(owner not in state.villagers for owner in intent.co_owners):
        return None
    if intent.ownership == "communal":
        owners = intent.co_owners
    else:
        owners = tuple(sorted({intent.actor, *intent.co_owners}))
    try:
        return Ownership(intent.ownership, owners)
    except ValueError:
        return None


def place_building(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, PlaceBuilding)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    definition = registry.buildings.get(intent.building)
    if definition is None:
        return reject(sink, intent, "unknown_building")
    if not ctx.available(state, villager, definition.id):
        return reject(sink, intent, "locked")
    ownership = _ownership(state, intent)
    if ownership is None:
        return reject(sink, intent, "bad_ownership")
    origin = Coord(*intent.origin)
    tiles = footprint(origin, definition.footprint)
    if not all(state.tilemap.in_bounds(tile) for tile in tiles):
        return reject(sink, intent, "out_of_bounds")
    if not all(registry.terrains[state.tilemap.terrain_at(tile)].walkable for tile in tiles):
        return reject(sink, intent, "bad_terrain")
    if not _occupied(ctx, state).isdisjoint(tiles):
        return reject(sink, intent, "occupied")
    if not definition.entrance and any(v.pos in tiles for v in state.villagers.values()):
        return reject(sink, intent, "occupied")
    if not near(villager.pos, tiles):
        return reject(sink, intent, "not_at_location")
    building_id = f"b{state.next_building}"
    state.next_building += 1
    state.buildings[building_id] = Building(building_id, definition.id, origin, ownership)
    sink.emit(
        "site_placed",
        actor=villager.id,
        building=building_id,
        kind=definition.id,
        origin=list(origin),
        ownership=ownership.to_dict(),
    )


def _site(
    ctx: Context,
    state: WorldState,
    villager: Villager,
    intent: Intent,
    building_id: str,
    sink: EventSink,
) -> Building | None:
    """An unfinished building within reach, or None after rejecting the intent."""
    building = state.buildings.get(building_id)
    if building is None:
        problem = "unknown_building"
    elif building.complete:
        problem = "already_complete"
    elif not near(villager.pos, building_tiles(building, ctx.registry)):
        problem = "not_at_location"
    else:
        return building
    reject(sink, intent, problem)
    return None


def deliver(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Deliver)
    villager = state.villagers[intent.actor]
    building = _site(ctx, state, villager, intent, intent.building, sink)
    if building is None:
        return None
    if intent.qty <= 0:
        return reject(sink, intent, "bad_quantity")
    if intent.qty > remaining_cost(building, ctx.registry).get(intent.item, 0):
        return reject(sink, intent, "not_needed")
    if villager.inventory.count(intent.item) < intent.qty:
        return reject(sink, intent, "missing_items")
    villager.inventory.remove(intent.item, intent.qty)
    building.delivered[intent.item] = building.delivered.get(intent.item, 0) + intent.qty
    sink.emit(
        "delivered", actor=villager.id, building=building.id, item=intent.item, qty=intent.qty
    )
    return None


def construct(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Construct)
    villager = state.villagers[intent.actor]
    building = _site(ctx, state, villager, intent, intent.building, sink)
    if building is None:
        return None
    if remaining_cost(building, ctx.registry):
        return reject(sink, intent, "missing_materials")
    definition = ctx.registry.buildings[building.kind]
    tools = used_tools(ctx, villager, "building", building.kind, definition.tags, ()) or []
    speed = work_speed(
        ctx,
        state,
        villager,
        kind="building",
        ident=building.kind,
        tags=definition.tags,
        skill=None,
        tools=tools,
        building=building.id,
    )
    return start_work(
        ctx,  # pragma: no mutate - ctx only reserves inputs; none here
        villager,
        intent,
        sink,
        kind="construction",
        ident=building.kind,
        target=building.id,
        work=definition.build_work,
        speed=speed,
        inputs={},
        done=building.work_done,
    )


def progress(ctx: Context, state: WorldState, villager: Villager, sink: EventSink) -> None:
    """Add one tick of this villager's build work; complete the building when it is done."""
    activity = villager.activity
    assert activity is not None
    assert activity.target is not None
    building = state.buildings[activity.target]
    work = float(ctx.registry.buildings[building.kind].build_work)
    building.work_done = min(work, building.work_done + activity.speed)
    activity.done = building.work_done
    if building.work_done >= work - EPSILON:
        _complete(ctx, state, building, sink)


def _complete(ctx: Context, state: WorldState, building: Building, sink: EventSink) -> None:
    building.complete = True
    destroyed = dict(sorted(building.delivered.items()))
    building.delivered = {}
    sink.emit("building_completed", building=building.id, kind=building.kind, destroyed=destroyed)
    tags = ctx.registry.buildings[building.kind].tags
    for vid in sorted(state.villagers):
        villager = state.villagers[vid]
        activity = villager.activity
        if (
            activity is not None
            and activity.kind == "construction"
            and activity.target == building.id
        ):
            tools = used_tools(ctx, villager, "building", building.kind, tags, ()) or []
            finish(ctx, villager, activity, sink, created={}, skill=None, tools=tools)


def _store(
    ctx: Context, state: WorldState, villager: Villager, intent: Deposit | Take, sink: EventSink
) -> Building | None:
    """A completed store within reach and a positive quantity, or None after rejecting."""
    building = state.buildings.get(intent.building)
    if building is None:
        problem = "unknown_building"
    elif storage_capacity(ctx.registry, building) == 0:
        problem = "no_storage"
    elif not near(villager.pos, building_tiles(building, ctx.registry)):
        problem = "not_at_location"
    elif intent.qty <= 0:
        problem = "bad_quantity"
    else:
        return building
    reject(sink, intent, problem)
    return None


def deposit(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Deposit)
    villager = state.villagers[intent.actor]
    building = _store(ctx, state, villager, intent, sink)
    if building is None:
        return None
    if villager.inventory.count(intent.item) < intent.qty:
        return reject(sink, intent, "missing_items")
    stored = sum(building.storage.totals().values())
    if stored + intent.qty > storage_capacity(ctx.registry, building):
        return reject(sink, intent, "store_full")
    transfer(ctx.registry, villager.inventory, building.storage, intent.item, intent.qty)
    sink.emit(
        "item_deposited", actor=villager.id, building=building.id, item=intent.item, qty=intent.qty
    )
    return None


def take(ctx: Context, state: WorldState, intent: Intent, sink: EventSink) -> None:
    assert isinstance(intent, Take)
    registry = ctx.registry
    villager = state.villagers[intent.actor]
    building = _store(ctx, state, villager, intent, sink)
    if building is None:
        return None
    if building.storage.count(intent.item) < intent.qty:
        return reject(sink, intent, "missing_items")
    if not fits(registry, villager.inventory, {intent.item: intent.qty}, ctx.config.carry_limit):
        return reject(sink, intent, "carry_limit")
    transfer(registry, building.storage, villager.inventory, intent.item, intent.qty)
    ownership = building.ownership
    sink.emit(
        "item_taken",
        actor=villager.id,
        building=building.id,
        item=intent.item,
        qty=intent.qty,
        ownership=ownership.kind,
    )
    if not ownership.owned_by(villager.id):
        sink.emit(
            "take_unowned",
            actor=villager.id,
            store=building.id,
            item=intent.item,
            qty=intent.qty,
            owners=list(ownership.owners),
        )
    return None
