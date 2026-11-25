"""What a scripted mind may see: read-only queries over the world (ADR-0016 §2-§4)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar, cast

from pericles.agents.config import RELIEFS, AgentConfig
from pericles.core.buildings import (
    COMMUNAL,
    Building,
    building_tiles,
    footprint,
    near,
    remaining_cost,
)
from pericles.core.construction import blocked_tiles
from pericles.core.context import Context
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo
from pericles.core.life import at_home
from pericles.core.lifecycle import food_stock
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState

PLACE = "place:"
T = TypeVar("T")
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


Rings = tuple[tuple[tuple[int, int], ...], ...]


class NodeIndex:
    """Nodes bucketed by kind and grid cell; nodes never move (ADR-0016 §3)."""

    def __init__(self, nodes: Iterable[Node], cell: int) -> None:
        self.cell = cell
        self._rings: dict[tuple[str, int, int, int], Rings] = {}
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
        ox, oy = origin
        cx, cy = ox // self.cell, oy // self.cell
        best: Node | None = None
        # The best (distance, id) so far; `reach` is its distance (`radius` before any).
        # `accept` is pure, so it is asked only of nodes that could still win.
        best_key: tuple[int, str] | None = None
        reach = radius
        rings = self._occupied_rings(kind, cx, cy, radius // self.cell + 1 + 1)
        for ring, keys in enumerate(rings):
            if best_key is not None and (ring - 1) * self.cell >= reach:
                break
            for key in keys:
                for node in cells[key]:
                    pos = node.pos
                    distance = abs(ox - pos.x) + abs(oy - pos.y)  # origin.manhattan(pos)
                    if distance > reach:
                        continue
                    candidate = (distance, node.id)
                    if best_key is not None and candidate >= best_key:
                        continue
                    if accept(node):
                        best, best_key, reach = node, candidate, distance
        return best

    def _occupied_rings(self, kind: str, cx: int, cy: int, count: int) -> Rings:
        """For rings 0..count-1 around cell (cx, cy): the cells of `kind` holding nodes, in
        `_ring` order. Nodes never move, so this is kept per kind, cell and ring count."""
        key = (kind, cx, cy, count)
        rings = self._rings.get(key)
        if rings is None:
            cells = self._cells[kind]
            rings = tuple(
                tuple(c for c in _ring(cx, cy, ring) if c in cells) for ring in range(count)
            )
            self._rings[key] = rings
        return rings


class OriginCache:
    """Free site origins kept across ticks while the inputs `free_origin` reads are unchanged:
    the tilemap, the nodes, the buildings (id, kind, origin) and the village centre."""

    def __init__(self) -> None:
        self.key: tuple[object, ...] | None = None
        self.origins: dict[str, Coord | None] = {}

    def lookup(self, key: tuple[object, ...]) -> dict[str, Coord | None]:
        if key != self.key:
            self.key, self.origins = key, {}
        return self.origins


class View:
    """Per-tick, read-only queries for minds; results are cached for the tick.

    The world does not change while minds decide, so world-only queries are cached on first
    use. Queries that read `memory` targets and jobs are not: minds update those as they go.
    """

    def __init__(
        self,
        ctx: Context,
        state: WorldState,
        config: AgentConfig,
        index: NodeIndex,
        memory: Mapping[str, Memory],
        origins: OriginCache | None = None,
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
        self._stored: dict[tuple[str, ...], float] = {}
        self._origin_cache = origins if origins is not None else OriginCache()
        self._origins: dict[str, Coord | None] | None = None
        self._occupancy: dict[str, int] | None = None
        self._sites: tuple[Building, ...] | None = None
        self._storage: tuple[Building, ...] | None = None
        self._usable: dict[str, tuple[Building, ...]] = {}
        self._owners: tuple[tuple[Building, ...], dict[str | None, frozenset[str]]] | None = None
        self._housing_shortfall: int | None = None
        self._storage_shortfall: float | None = None
        self._center: Coord | None = None
        self._food: dict[str, float] = {}
        self._food_demand: dict[str, float] = {}
        self._memo: dict[Hashable, object] = {}
        self._held: dict[str, Mapping[str, int]] = {}
        self._jobs: Counter[str] | None = None
        self._targets: Counter[tuple[str | None, str]] | None = None
        self._producing: dict[str, frozenset[str]] = {}
        self._houses: tuple[tuple[Building, int], ...] | None = None
        self._family: dict[tuple[str, ...], Building | None] = {}
        self._urgent = [
            (need, config.urgent_at[relief])
            for relief in RELIEFS
            for need in self._relief.get(relief, ())
        ]

    @property
    def tick(self) -> int:
        return self.state.tick

    def level(self, villager: Villager, relief: str) -> float:
        return max((villager.needs.get(n, 0.0) for n in self._relief.get(relief, ())), default=0.0)

    def urgent(self, villager: Villager) -> bool:
        """True if any relief's `level` is at or past its `urgent_at`. A relief no need
        uses has level 0, below every `urgent_at` (levels are positive, `AgentConfig`)."""
        needs = villager.needs
        for need, at in self._urgent:  # noqa: SIM110 - a loop beats a generator here
            if needs.get(need, 0.0) >= at:
                return True
        return False

    def avoided(self, villager: Villager, target: str) -> bool:
        memory = self.memory.get(villager.id)
        if memory is None or not memory.avoid:
            return False
        tick = self.state.tick
        return memory.avoid.get(target, tick) > tick

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

    def occupants(self, building_id: str) -> int:
        """Residents plus their unborn children (`lifecycle.occupants`), counted once a tick."""
        if self._occupancy is None:
            table: dict[str, int] = {}
            for v in self.state.villagers.values():
                if v.home is not None:
                    table[v.home] = table.get(v.home, 0) + beds_needed(v)
            self._occupancy = table
        return self._occupancy.get(building_id, 0)

    def at_home(self, villager: Villager) -> bool:
        return at_home(self.ctx, self.state, villager)

    def _storehouses(self) -> tuple[Building, ...]:
        """Complete buildings with storage, by id."""
        if self._storage is None:
            registry = self.ctx.registry
            self._storage = tuple(
                sorted(
                    (
                        b
                        for b in self.state.buildings.values()
                        if b.complete and registry.buildings[b.kind].storage > 0
                    ),
                    key=lambda b: b.id,
                )
            )
        return self._storage

    def _usable_stores(self, villager: Villager) -> tuple[Building, ...]:
        """The stores `villager` may use and does not avoid, by id (avoidance is fixed while
        minds decide: only `Controller.observe` changes it)."""
        usable = self._usable.get(villager.id)
        if usable is None:
            memory = self.memory.get(villager.id)
            avoid = memory.avoid if memory is not None else {}
            tick = self.state.tick
            communal, owned = self._store_owners()
            if villager.id in owned or any(
                until > tick and target in owned[None] for target, until in avoid.items()
            ):
                usable = tuple(
                    b
                    for b in self._storehouses()
                    if b.ownership.owned_by(villager.id) and avoid.get(b.id, tick) <= tick
                )
            else:  # no store of its own and none avoided: just the communal ones
                usable = communal
            self._usable[villager.id] = usable
        return usable

    def _store_owners(self) -> tuple[tuple[Building, ...], dict[str | None, frozenset[str]]]:
        """The communal `_storehouses`, and the ids of each owner's other storehouses, with
        every storehouse id under None. Built once a tick."""
        if self._owners is None:
            owned: dict[str | None, set[str]] = {None: set()}
            communal = []
            for b in self._storehouses():
                owned[None].add(b.id)
                if b.ownership.kind == COMMUNAL:
                    communal.append(b)
                for owner in b.ownership.owners:
                    owned.setdefault(owner, set()).add(b.id)
            self._owners = (tuple(communal), {k: frozenset(v) for k, v in owned.items()})
        return self._owners

    def stores(self, villager: Villager) -> list[Building]:
        return sorted(
            self._usable_stores(villager),
            key=lambda b: (villager.pos.manhattan(b.origin), b.id),
        )

    def room(self, building: Building) -> int:
        capacity = self.ctx.registry.buildings[building.kind].storage
        return capacity - sum(building.storage.totals().values())

    def sites(self) -> tuple[Building, ...]:
        if self._sites is None:
            self._sites = tuple(
                self.state.buildings[b]
                for b in sorted(self.state.buildings)
                if not self.state.buildings[b].complete
            )
        return self._sites

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

    def stored_food(self, villager: Villager) -> float:
        """Nutrition in the stores `villager` can fetch from (`stores`): complete buildings
        with storage it may use and does not avoid. Summed in id and item order."""
        known = self._food.get(villager.id)
        if known is not None:
            return known
        usable = self._usable_stores(villager)
        key = tuple(b.id for b in usable)
        if key not in self._stored:
            items = self.ctx.registry.items
            self._stored[key] = sum(
                items[item].nutrition * qty
                for building in usable
                for item, qty in sorted(self.held(building).items())
            )
        self._food[villager.id] = self._stored[key]
        return self._stored[key]

    def memo(self, key: Hashable, compute: Callable[[], T]) -> T:
        """`compute()` once a tick per `key`; the key must name everything it depends on."""
        if key not in self._memo:
            self._memo[key] = compute()
        return cast(T, self._memo[key])

    def food_demand(self, villager: Villager) -> float:
        """How much `villager` sees food wanted, 0..1: the shortfall of `stored_food` against
        `food_target`, as a share of the target (ADR-0016 §4, amended)."""
        known = self._food_demand.get(villager.id)
        if known is None:
            target = self.food_target()
            known = 0.0 if target <= 0 else max(0.0, target - self.stored_food(villager)) / target
            self._food_demand[villager.id] = known
        return known

    def held(self, building: Building) -> Mapping[str, int]:
        """`building.storage.totals()`, counted once a tick; a store without tools holds
        just its items, so they are read as they are. Read only, with `get(item, 0)`."""
        found = self._held.get(building.id)
        if found is None:
            storage = building.storage
            found = storage.items if not storage.tools else storage.totals()
            self._held[building.id] = found
        return found

    def food_target(self) -> float:
        return self.config.food_reserve_per_capita * self.population()

    def _job_counts(self) -> Counter[str]:
        """Living villagers per remembered job; kept current by `remember`."""
        if self._jobs is None:
            self._count_memory()
        assert self._jobs is not None
        return self._jobs

    def _target_counts(self) -> Counter[tuple[str | None, str]]:
        """Living villagers per remembered (job, target); kept current by `remember`."""
        if self._targets is None:
            self._count_memory()
        assert self._targets is not None
        return self._targets

    def _count_memory(self) -> None:
        villagers = self.state.villagers
        living = [m for vid, m in self.memory.items() if vid in villagers]
        self._jobs = Counter(m.job for m in living if m.job is not None)
        self._targets = Counter((m.job, m.target) for m in living if m.target is not None)

    def _producers(self, item: str) -> frozenset[str]:
        """The actions with `item` among their outputs."""
        found = self._producing.get(item)
        if found is None:
            actions = self.ctx.registry.actions
            found = frozenset(a for a in actions if item in actions[a].outputs)
            self._producing[item] = found
        return found

    def remember(self, vid: str, memory: Memory, target: str | None, job: str | None) -> None:
        """Record a decision's target and job in `memory` (minds' one write while deciding)."""
        if vid in self.state.villagers:
            if self._jobs is not None:
                if memory.job is not None:
                    self._jobs[memory.job] -= 1
                if job is not None:
                    self._jobs[job] += 1
            if self._targets is not None:
                if memory.target is not None:
                    self._targets[(memory.job, memory.target)] -= 1
                if target is not None:
                    self._targets[(job, target)] += 1
        memory.target, memory.job = target, job

    def _others(self, job: str | None, target: str, exclude: str) -> int:
        """Living villagers other than `exclude` remembering (job, target)."""
        total = self._target_counts()[(job, target)]
        mine = self.memory.get(exclude)
        if (
            mine is not None
            and (mine.job, mine.target) == (job, target)
            and exclude in self.state.villagers
        ):
            total -= 1
        return total

    def workers(self, item: str, exclude: str) -> int:
        """Living villagers other than `exclude` whose remembered job produces `item`."""
        producers = self._producers(item)
        counts = self._job_counts()
        total = sum(counts[job] for job in producers)
        mine = self.memory.get(exclude)
        if mine is not None and mine.job in producers and exclude in self.state.villagers:
            total -= 1
        return total

    def builders(self, site_id: str, exclude: str) -> int:
        return self._others(CONSTRUCT, site_id, exclude)

    def placing(self, kind: str, exclude: str) -> bool:
        """True if another living villager has claimed a site for `kind` (no job, as `build`
        decides a placement)."""
        claim = PLACE + kind
        return any(
            self._others(job, claim, exclude) > 0
            for job, target in self._target_counts()
            if target == claim
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
            room = villager.home == b.id or self.occupants(b.id) + incoming <= housing
            return b.complete and housing > 0 and allowed and room

        if partner is not None and partner.home in buildings and fits(buildings[partner.home]):
            return buildings[partner.home]
        options = sorted(
            (b for b in buildings.values() if fits(b)),
            key=lambda b: (villager.pos.manhattan(b.origin), b.id),
        )
        return options[0] if options else None

    def full(self, building: Building) -> bool:
        """True if every bed of `building` is taken."""
        housing = self.ctx.registry.buildings[building.kind].housing
        return self.occupants(building.id) >= housing

    def _pair_rank(self, a: Villager, b: Villager) -> Callable[[Building], tuple[int, str]]:
        """The same order for both partners: summed distance, then id."""
        return lambda h: (a.pos.manhattan(h.origin) + b.pos.manhattan(h.origin), h.id)

    def _fits_pair(self, building: Building, a: Villager, b: Villager) -> bool:
        """A complete house either partner may live in, with beds for both and one to spare,
        not counting the partners' own beds in it."""
        housing = self.ctx.registry.buildings[building.kind].housing
        allowed = building.ownership.owned_by(a.id) or building.ownership.owned_by(b.id)
        others = self.occupants(building.id) - sum(1 for v in (a, b) if v.home == building.id)
        room = others + beds_needed(a) + beds_needed(b) + 1 <= housing
        return building.complete and allowed and room

    def family_house(self, villager: Villager) -> Building | None:
        """For a couple without a roomy shared home: the other complete house nearest to both
        partners (summed distance, ties to the lower id) with beds for both and one to spare."""
        partner = self.state.villagers.get(villager.partner) if villager.partner else None
        if partner is None:
            return None
        pair = tuple(sorted((villager.id, partner.id)))
        if pair not in self._family:
            # Neither partner lives in the candidate, so `_fits_pair` reduces to free beds.
            homes = {villager.home, partner.home}
            beds = beds_needed(villager) + beds_needed(partner) + 1
            options = sorted(
                (
                    b
                    for b, free in self._free_beds()
                    if free >= beds
                    and b.id not in homes
                    and (b.ownership.owned_by(villager.id) or b.ownership.owned_by(partner.id))
                ),
                key=self._pair_rank(villager, partner),
            )
            self._family[pair] = options[0] if options else None
        return self._family[pair]

    def _free_beds(self) -> tuple[tuple[Building, int], ...]:
        """Complete buildings with beds, in building order, with their beds not taken."""
        if self._houses is None:
            registry = self.ctx.registry
            self._houses = tuple(
                (b, registry.buildings[b.kind].housing - self.occupants(b.id))
                for b in self.state.buildings.values()
                if b.complete and registry.buildings[b.kind].housing > 0
            )
        return self._houses

    def couple_house(self, villager: Villager) -> Building | None:
        """Where a housed couple should live; both partners compute the same house.

        Together in a home with a free bed: that home. Together in a full home: the family
        house, if any. Apart: whichever partner's home fits the pair (summed distance, then
        id), else the family house. None while the partner has no home or nothing fits.
        """
        partner = self.state.villagers.get(villager.partner) if villager.partner else None
        if partner is None or partner.home is None:
            return None
        home = self.home(villager)
        if villager.home == partner.home:
            if home is None or not self.full(home):
                return home
            return self.family_house(villager) or home
        buildings = self.state.buildings
        pair_homes = sorted(
            (
                buildings[h]
                for h in {villager.home, partner.home}
                if h in buildings and self._fits_pair(buildings[h], villager, partner)
            ),
            key=self._pair_rank(villager, partner),
        )
        return pair_homes[0] if pair_homes else self.family_house(villager)

    def _communal(self, attribute: str, *, complete: bool) -> int:
        registry = self.ctx.registry
        return sum(
            getattr(registry.buildings[b.kind], attribute)
            for b in self.state.buildings.values()
            if b.complete == complete and b.ownership.kind == "communal"
        )

    def crowded_couples(self) -> int:
        """Couples who do not share a complete home with a free bed: no room for a child.

        Each couple counts once, by its bearing partner (ADR-0016 §4, amended).
        """
        villagers = self.state.villagers
        crowded = 0
        for villager in villagers.values():
            partner = villagers.get(villager.partner) if villager.partner is not None else None
            if partner is None or villager.sex != self.ctx.config.bearing_sex:
                continue
            home = self.home(villager)
            roomy = home is not None and partner.home == home.id and not self.full(home)
            crowded += 0 if roomy else 1
        return crowded

    def housing_shortfall(self) -> int:
        """Homeless villagers' beds, plus a bed per crowded couple, less free communal beds
        and beds under construction.

        Negative when the village has more beds, built or planned, than it needs.
        """
        if self._housing_shortfall is None:
            self._housing_shortfall = self._count_housing_shortfall()
        return self._housing_shortfall

    def _count_housing_shortfall(self) -> int:
        homeless = sum(
            beds_needed(v) for v in self.state.villagers.values() if self.home(v) is None
        )
        homeless += self.crowded_couples()
        registry = self.ctx.registry
        free = sum(
            registry.buildings[b.kind].housing - self.occupants(b.id)
            for b in self.state.buildings.values()
            if b.complete and b.ownership.kind == "communal" and registry.buildings[b.kind].housing
        )
        building = self._communal("housing", complete=False)
        return homeless - free - building

    def storage_shortfall(self) -> float:
        if self._storage_shortfall is None:
            self._storage_shortfall = self._count_storage_shortfall()
        return self._storage_shortfall

    def _count_storage_shortfall(self) -> float:
        storage = self._communal("storage", complete=True) + self._communal(
            "storage", complete=False
        )
        return max(0.0, self.config.storage_per_capita * self.population() - storage)

    def center(self) -> Coord:
        if self._center is None:
            self._center = self._find_center()
        return self._center

    def _find_center(self) -> Coord:
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
        if self._origins is None:
            state = self.state
            buildings = tuple((b.id, b.kind, b.origin) for b in state.buildings.values())
            key = (state.tilemap, state.nodes, buildings, self.center())
            self._origins = self._origin_cache.lookup(key)
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
