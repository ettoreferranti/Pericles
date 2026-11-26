import pytest

from pericles.experiment.config import VillagerSpec
from pericles.experiment.models import assign_models, quotas


def villager(vid: str, age: int = 200, model: str | None = None) -> VillagerSpec:
    return VillagerSpec(id=vid, name=vid.upper(), age_days=age, model=model)


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize(
    ("n", "ratios", "expected"),
    [
        (10, {"a": 1.0, "b": 1.0}, {"a": 5, "b": 5}),
        (7, {"a": 1.0, "b": 1.0}, {"a": 4, "b": 3}),
        (10, {"a": 0.7, "b": 0.3}, {"a": 7, "b": 3}),
        (5, {"a": 1.0, "b": 1.0, "c": 1.0}, {"a": 2, "b": 2, "c": 1}),
        (3, {"b": 2.0, "a": 1.0}, {"a": 1, "b": 2}),
        (0, {"a": 1.0}, {"a": 0}),
    ],
)
def test_quotas_use_the_largest_remainder(
    n: int, ratios: dict[str, float], expected: dict[str, int]
) -> None:
    """AC1: groups are split by ratio with exact counts; ties go to the model key."""
    assert quotas(n, ratios) == expected


@pytest.mark.req("REQ-LLM-006")
def test_unpinned_adults_are_split_by_ratio_with_the_seed() -> None:
    """AC1: pins are kept; children get nothing; the split is seeded and exact."""
    specs = [villager(f"v{i}") for i in range(8)] + [
        villager("kid", age=5),
        villager("pin", model="b"),
    ]
    one = assign_models(specs, 120, {"a": 3.0, "b": 1.0}, seed=1)
    again = assign_models(specs, 120, {"a": 3.0, "b": 1.0}, seed=1)
    other = assign_models(specs, 120, {"a": 3.0, "b": 1.0}, seed=2)
    models = {s.id: s.model for s in one}
    assert one == again
    assert models["kid"] is None and models["pin"] == "b"
    adults = [models[f"v{i}"] for i in range(8)]
    assert adults.count("a") == 6 and adults.count("b") == 2
    assert [s.id for s in one] == [s.id for s in specs]
    assert {s.id: s.model for s in other} != models


@pytest.mark.req("REQ-LLM-006")
def test_no_ratios_assign_nothing() -> None:
    """AC1: without `assign`, unpinned villagers keep no model (scripted)."""
    specs = (villager("a"), villager("b", model="m"))
    assert assign_models(specs, 120, {}, seed=1) == specs
