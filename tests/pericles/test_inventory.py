from collections import Counter

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pericles.core.content.registry import Registry
from pericles.core.inventory import (
    EPSILON,
    UNLIMITED,
    Inventory,
    InventoryError,
    Tool,
    bundle_weight,
    capacity_for,
    fits,
    transfer,
)

pytestmark = pytest.mark.req("REQ-SIM-013")


def test_stackable_items_are_counted(econ: Registry) -> None:
    """AC1: quantities are tracked per item and empty entries disappear."""
    inv = Inventory()
    inv.add(econ, "wood", 3)
    inv.add(econ, "wood", 2)
    inv.add(econ, "berries", 0)
    assert inv.items == {"wood": 5}
    assert (inv.count("wood"), inv.count("plank")) == (5, 0)
    assert inv.remove("wood", 5) == []
    assert inv.items == {}


def test_tools_are_individual_instances(econ: Registry) -> None:
    """AC1: tools are held as instances with their own durability (REQ-SIM-010 AC2)."""
    inv = Inventory()
    inv.add(econ, "axe", 2)
    assert inv.items == {}
    assert inv.tools == [Tool("axe", 3), Tool("axe", 3)]
    assert inv.count("axe") == 2


def test_tools_are_sorted_and_removed_most_worn_first() -> None:
    """AC1: tool order is canonical; the most worn instance leaves first."""
    inv = Inventory()
    inv.add_tools([Tool("hammer", 2), Tool("axe", 3), Tool("axe", 1)])
    assert inv.tools == [Tool("axe", 1), Tool("axe", 3), Tool("hammer", 2)]
    assert inv.remove("axe", 1) == [Tool("axe", 1)]
    assert inv.tools == [Tool("axe", 3), Tool("hammer", 2)]


def test_removing_more_than_held_fails_and_changes_nothing(econ: Registry) -> None:
    """AC1: an inventory never holds a negative quantity."""
    inv = Inventory()
    inv.add(econ, "wood", 2)
    with pytest.raises(InventoryError, match=r"^holds 2 wood, cannot remove 3$"):
        inv.remove("wood", 3)
    assert inv.items == {"wood": 2}
    with pytest.raises(InventoryError, match=r"^holds 0 axe, cannot remove 1$"):
        inv.remove("axe", 1)


@pytest.mark.parametrize("operation", ["add", "remove"])
def test_negative_quantities_are_rejected(econ: Registry, operation: str) -> None:
    """AC1: negative quantities are never accepted."""
    inv = Inventory()
    with pytest.raises(InventoryError, match="negative quantity"):
        if operation == "add":
            inv.add(econ, "wood", -1)
        else:
            inv.remove("wood", -1)
    assert inv == Inventory()


def test_transfer_moves_items_and_keeps_tool_durability(econ: Registry) -> None:
    """AC1: transfers move exact quantities; tools keep their wear."""
    source, target = Inventory(), Inventory()
    source.add(econ, "wood", 4)
    source.add_tools([Tool("axe", 1), Tool("axe", 3)])
    transfer(econ, source, target, "wood", 3)
    transfer(econ, source, target, "axe", 1)
    assert source.items == {"wood": 1}
    assert source.tools == [Tool("axe", 3)]
    assert target.items == {"wood": 3}
    assert target.tools == [Tool("axe", 1)]


def test_totals_and_bundles(econ: Registry) -> None:
    """AC1: totals merge stackables and tools; bundles are checked against them."""
    inv = Inventory()
    inv.add(econ, "wood", 2)
    inv.add(econ, "axe", 2)
    assert inv.totals() == Counter({"wood": 2, "axe": 2})
    assert inv.has({"wood": 2, "axe": 1})
    assert inv.has({})
    assert not inv.has({"wood": 3})


def test_weight_counts_items_and_tools(econ: Registry) -> None:
    """AC2: carried weight is the sum of item weights."""
    inv = Inventory()
    inv.add(econ, "wood", 3)
    inv.add(econ, "axe", 1)
    inv.add(econ, "seed", 2)
    assert inv.weight(econ) == pytest.approx(3 * 2.0 + 2.0 + 2 * 0.1)
    assert bundle_weight(econ, {"wood": 2, "berries": 4}) == pytest.approx(6.0)


def test_capacity_for(econ: Registry) -> None:
    """AC2: how many units of an item still fit under the carry limit."""
    inv = Inventory()
    assert capacity_for(econ, inv, "wood", 30.0) == 15
    assert capacity_for(econ, inv, "seed", 0.3) == 3  # 0.3 / 0.1 must not round down to 2
    inv.add(econ, "wood", 14)
    assert capacity_for(econ, inv, "wood", 30.0) == 1
    assert capacity_for(econ, inv, "wood", 30.0, freed=2.0) == 2
    inv.add(econ, "wood", 1)
    assert capacity_for(econ, inv, "wood", 30.0) == 0
    assert capacity_for(econ, inv, "wood", 29.0) == 0  # over the limit never gives a negative count
    assert capacity_for(econ, inv, "token", 1.0) == UNLIMITED


def test_fits(econ: Registry) -> None:
    """AC2: a bundle fits if the resulting weight stays within the limit."""
    inv = Inventory()
    inv.add(econ, "wood", 14)  # 28
    assert fits(econ, inv, {"wood": 1}, 30.0)
    assert not fits(econ, inv, {"wood": 2}, 30.0)
    assert fits(econ, inv, {"wood": 2}, 30.0, freed=2.0)
    assert fits(econ, inv, {}, 28.0)
    assert not fits(econ, inv, {}, 27.9)


def test_round_trip(econ: Registry) -> None:
    """AC1: inventories serialise exactly."""
    inv = Inventory()
    inv.add(econ, "wood", 2)
    inv.add_tools([Tool("axe", 1)])
    data = inv.to_dict()
    assert data == {"items": {"wood": 2}, "tools": [{"item": "axe", "durability": 1}]}
    assert Inventory.from_dict(data) == inv


ITEMS = ["wood", "berries", "axe", "hammer"]


@settings(max_examples=100, deadline=None)
@given(st.lists(st.tuples(st.sampled_from(ITEMS), st.integers(-2, 5), st.booleans()), max_size=40))
def test_quantities_never_go_negative(econ: Registry, ops: list[tuple[str, int, bool]]) -> None:
    """AC1 (property): any sequence of adds and removes keeps every count exact and ≥ 0."""
    inv = Inventory()
    expected: Counter[str] = Counter()
    for item, qty, adding in ops:
        try:
            if adding:
                inv.add(econ, item, qty)
            else:
                inv.remove(item, qty)
        except InventoryError:
            assert qty < 0 or (not adding and expected[item] < qty)
            continue
        expected[item] += qty if adding else -qty
    assert all(n > 0 for n in inv.items.values())
    assert all(tool.durability > 0 for tool in inv.tools)
    assert +inv.totals() == +expected


def test_fits_tolerates_float_noise_but_not_real_excess(econ: Registry) -> None:
    """AC2: 3 seeds weigh 0.30000000000000004 and still fit a 0.3 limit; a 4th does not."""
    inv = Inventory()
    inv.add(econ, "seed", 3)
    assert fits(econ, inv, {}, 0.3)
    assert fits(econ, Inventory(), {"seed": 3}, 0.3)
    assert not fits(econ, Inventory(), {"seed": 4}, 0.3)
    assert not fits(econ, Inventory(), {"wood": 1}, 1.99)


def test_fits_boundary_is_inclusive(econ: Registry) -> None:
    """AC2: a total exactly at the tolerance edge (limit + EPSILON) still fits."""
    assert fits(econ, Inventory(), {}, -EPSILON)
