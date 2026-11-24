"""What a scripted mind may see: read-only queries over the world (ADR-0016 §2-§4)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from pericles.agents.config import AgentConfig
from pericles.core.buildings import Building, building_tiles, footprint, near, remaining_cost
from pericles.core.construction import blocked_tiles
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo
from pericles.core.life import at_home
from pericles.core.lifecycle import food_stock, occupants
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

PLACE = "place:"
CONSTRUCT = "construct"


def beds_needed(villager: Villager) -> int:
    """Beds a villager takes when moving in: one, and one more for a child on the way."""
    return 1 + (1 if villager.pregnancy is not None else 0)


@dataclass
class Memory:
    """What the controller remembers about one villager between ticks (ADR-0016 §2)."""

    target: str | None = None
    job: str | None = None
    idle_until: int = 0
    avoid: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "job": self.job,
            "idle_until": self.idle_until,
            "avoid": dict(sorted(self.avoid.items())),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Memory:
        target, job = data["target"], data["job"]
        return cls(
            target=None if target is None else str(target),
            job=None if job is None else str(job),
            idle_until=int(data["idle_until"]),
            avoid={str(k): int(v) for k, v in data["avoid"].items()},
        )


@dataclass(frozen=True)
class Decision:
    intent: Intent
    target: str | None = None
    job: str | None = None


def _ring(cx: int, cy: int, r: int) -> Iterator[tuple[int, int]]:
    if r == 0:
        yield (cx, cy)
        return
    for dx in range(-r, r + 1):
        yield (cx + dx, cy - r)
        yield (cx + dx, cy + r)
    for dy in range(-r + 1, r):
        yield (cx - r, cy + dy)
        yield (cx + r, cy + dy)


class NodeIndex:
    """Nodes bucketed by kind and grid cell; nodes never move (ADR-0016 §3)."""

    def __init__(self, nodes: Iterable[Node], cell: int) -> None:
        self.cell = cell
        self._cells: dict[str, dict[tuple[int, int], list[Node]]] = {}
        for node in sorted(nodes, key=lambda n: n.id):
            bucket = self._cells.setdefault(node.kind, {})
            bucket.setdefault((node.pos.x // cell, node.pos.y // cell), []).append(node)

    def nearest(
        self, kind: str, origin: Coord, radius: int, accept: Callable[[Node], bool]
    ) -> Node | None:
        cells = self._cells.get(kind)
        if not cells:
            return None
        cx, cy = origin.x // self.cell, origin.y // self.cell
        best: Node | None = None
        best_key: tuple[int, str] | None = None
        for ring in range(radius // self.cell + 1 + 1):
            if best_key is not None and (ring - 1) * self.cell >= best_key[0]:
                break
            for key in _ring(cx, cy, ring):
                for node in cells.get(key, ()):
                    distance = origin.manhattan(node.pos)
                    if distance > radius or not accept(node):
                        continue
                    candidate = (distance, node.id)
                    if best_key is None or candidate < best_key:
                        best, best_key = node, candidate
        return best


class View:
    """Per-tick, read-only queries for minds; results are cached for the tick."""

    def __init__(
        self,
        ctx: Context,
        state: WorldState,
        config: AgentConfig,
        index: NodeIndex,
        memory: Mapping[str, Memory],
    ) -> None:
        self.ctx = ctx
        self.state = state
        self.config = config
        self.index = index
        self.memory = memory
        items = ctx.registry.items
        self.foods = tuple(
            sorted(
                (i for i in items if items[i].nutrition > 0), key=lambda i: (-items[i].nutrition, i)
            )
        )
        needs = ctx.registry.needs
        self._relief: dict[str, tuple[str, ...]] = {}
        for need in sorted(needs):
            relief = needs[need].relief
            if relief is not None:
                self._relief[relief] = (*self._relief.get(relief, ()), need)
        self._blocked: frozenset[Coord] | None = None
        self._needed: Counter[str] | None = None
        self._stock: float | None = None
        self._origins: dict[str, Coord | None] = {}

    @property
    def tick(self) -> int:
        return self.state.tick

    def level(self, villager: Villager, relief: str) -> float:
        return max((villager.needs.get(n, 0.0) for n in self._relief.get(relief, ())), default=0.0)

    def avoided(self, villager: Villager, target: str) -> bool:
        memory = self.memory.get(villager.id)
        return memory is not None and memory.avoid.get(target, self.tick) > self.tick

    def nearest_node(
        self, villager: Villager, kind: str, origin: Coord | None = None, radius: int | None = None
    ) -> Node | None:
        return self.index.nearest(
            kind,
            villager.pos if origin is None else origin,
            self.config.node_search_radius if radius is None else radius,
            lambda node: node.stock > 0 and not self.avoided(villager, node.id),
        )

    def _blocked_tiles(self) -> frozenset[Coord]:
        if self._blocked is None:
            self._blocked = blocked_tiles(self.ctx, self.state)
        return self._blocked

    def walkable(self, c: Coord) -> bool:
        tilemap = self.state.tilemap
        return (
            tilemap.in_bounds(c)
            and self.ctx.registry.terrains[tilemap.terrain_at(c)].walkable
            and c not in self._blocked_tiles()
        )

    def go(self, villager: Villager, tiles: Sequence[Coord]) -> MoveTo | None:
        """None if `tiles` are within reach; else a move to the nearest walkable tile by them."""
        if not tiles or near(villager.pos, tiles):
            return None
        candidates = {c for t in tiles for c in (t, *t.neighbours4()) if self.walkable(c)}
        if not candidates:
            return MoveTo(villager.id, tiles[0])
        return MoveTo(
            villager.id, min(candidates, key=lambda c: (villager.pos.manhattan(c), c.y, c.x))
        )

    def tiles(self, building: Building) -> list[Coord]:
        return building_tiles(building, self.ctx.registry)

    def home(self, villager: Villager) -> Building | None:
        home = self.state.buildings.get(villager.home) if villager.home is not None else None
        return home if home is not None and home.complete else None

    def at_home(self, villager: Villager) -> bool:
        return at_home(self.ctx, self.state, villager)

    def stores(self, villager: Villager) -> list[Building]:
        registry = self.ctx.registry
        found = [
            b
            for b in self.state.buildings.values()
            if b.complete
            and registry.buildings[b.kind].storage > 0
            and b.ownership.owned_by(villager.id)
            and not self.avoided(villager, b.id)
        ]
        return sorted(found, key=lambda b: (villager.pos.manhattan(b.origin), b.id))

    def room(self, building: Building) -> int:
        capacity = self.ctx.registry.buildings[building.kind].storage
        return capacity - sum(building.storage.totals().values())

    def sites(self) -> list[Building]:
        return [
            self.state.buildings[b]
            for b in sorted(self.state.buildings)
            if not self.state.buildings[b].complete
        ]

    def needed(self) -> Counter[str]:
        if self._needed is None:
            self._needed = Counter()
            for site in self.sites():
                self._needed.update(remaining_cost(site, self.ctx.registry))
        return self._needed

    def population(self) -> int:
        return len(self.state.villagers)

    def food_stock(self) -> float:
        if self._stock is None:
            self._stock = food_stock(self.ctx, self.state)
        return self._stock

    def food_target(self) -> float:
        return self.config.food_reserve_per_capita * self.population()

    def workers(self, item: str, exclude: str) -> int:
        actions = self.ctx.registry.actions
        return len(
            [
                vid
                for vid, memory in self.memory.items()
                if vid != exclude
                and memory.job is not None
                and memory.job in actions
                and item in actions[memory.job].outputs
                and vid in self.state.villagers
            ]
        )

    def builders(self, site_id: str, exclude: str) -> int:
        return sum(
            1
            for vid, memory in self.memory.items()
            if vid != exclude
            and memory.job == CONSTRUCT
            and memory.target == site_id
            and vid in self.state.villagers
        )

    def placing(self, kind: str, exclude: str) -> bool:
        claim = PLACE + kind
        return any(
            vid != exclude and memory.target == claim and vid in self.state.villagers
            for vid, memory in self.memory.items()
        )

    def house_for(self, villager: Villager) -> Building | None:
        """A complete house this villager may live in with room for it, the partner's first."""
        registry = self.ctx.registry
        buildings = self.state.buildings
        partner = self.state.villagers.get(villager.partner) if villager.partner else None
        incoming = beds_needed(villager)

        def fits(b: Building) -> bool:
            housing = registry.buildings[b.kind].housing
            allowed = b.ownership.owned_by(villager.id) or (
                partner is not None and b.ownership.owned_by(partner.id)
            )
            room = villager.home == b.id or occupants(self.state, b.id) + incoming <= housing
            return b.complete and housing > 0 and allowed and room

        if partner is not None and partner.home in buildings and fits(buildings[partner.home]):
            return buildings[partner.home]
        options = sorted(
            (b for b in buildings.values() if fits(b)),
            key=lambda b: (villager.pos.manhattan(b.origin), b.id),
        )
        return options[0] if options else None

    def _communal(self, attribute: str, *, complete: bool) -> int:
        registry = self.ctx.registry
        return sum(
            getattr(registry.buildings[b.kind], attribute)
            for b in self.state.buildings.values()
            if b.complete == complete and b.ownership.kind == "communal"
        )

    def housing_shortfall(self) -> int:
        """Homeless villagers less free communal beds and beds under construction.

        Negative when the village has more beds, built or planned, than homeless villagers.
        """
        homeless = sum(
            beds_needed(v) for v in self.state.villagers.values() if self.home(v) is None
        )
        registry = self.ctx.registry
        free = sum(
            registry.buildings[b.kind].housing - occupants(self.state, b.id)
            for b in self.state.buildings.values()
            if b.complete and b.ownership.kind == "communal" and registry.buildings[b.kind].housing
        )
        building = self._communal("housing", complete=False)
        return homeless - free - building

    def storage_shortfall(self) -> float:
        storage = self._communal("storage", complete=True) + self._communal(
            "storage", complete=False
        )
        return max(0.0, self.config.storage_per_capita * self.population() - storage)

    def center(self) -> Coord:
        registry = self.ctx.registry
        stores = sorted(
            (
                b
                for b in self.state.buildings.values()
                if b.complete
                and b.ownership.kind == "communal"
                and registry.buildings[b.kind].storage
            ),
            key=lambda b: b.id,
        )
        return stores[0].origin if stores else self.state.tilemap.start()

    def free_origin(self, kind: str) -> Coord | None:
        """The clear footprint origin nearest the village centre, with `site_gap` around it."""
        if kind in self._origins:
            return self._origins[kind]
        width, height = self.ctx.registry.buildings[kind].footprint
        gap = self.config.site_gap
        taken = {t for b in self.state.buildings.values() for t in self.tiles(b)}
        nodes = {n.pos for n in self.state.nodes.values()}
        centre = self.center()
        radius = self.config.site_search_radius
        candidates = sorted(
            (
                Coord(centre.x + dx, centre.y + dy)
                for dy in range(-radius, radius + 1)
                for dx in range(-radius, radius + 1)
            ),
            key=lambda c: (centre.manhattan(c), c.y, c.x),
        )
        found: Coord | None = None
        for origin in candidates:
            tiles = footprint(origin, (width, height))
            if not all(self.walkable(t) and t not in nodes for t in tiles):
                continue
            margin = footprint(
                Coord(origin.x - gap, origin.y - gap), (width + gap + gap, height + gap + gap)
            )
            if any(t in taken for t in margin):
                continue
            found = origin
            break
        self._origins[kind] = found
        return found

    def guardian(self, child: Villager) -> Villager | None:
        for parent in sorted(child.parents):
            if parent in self.state.villagers:
                return self.state.villagers[parent]
        return None
