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
        (5, {"c": 1.0, "b": 1.0, "a": 1.0}, {"a": 2, "b": 2, "c": 1}),
        (3, {"b": 2.0, "a": 1.0}, {"a": 1, "b": 2}),
        (0, {"a": 1.0}, {"a": 0}),
        (0, {"a": 1.0, "b": 2.0, "c": 3.0}, {"a": 0, "b": 0, "c": 0}),
        (1, {"a": 0.1, "b": 0.2}, {"a": 0, "b": 1}),
        (2, {"a": 0.1, "b": 0.2}, {"a": 1, "b": 1}),
        (3, {"a": 0.1, "b": 0.2}, {"a": 1, "b": 2}),
        (4, {"a": 0.1, "b": 0.2}, {"a": 1, "b": 3}),
    ],
)
def test_quotas_use_the_largest_remainder(
    n: int, ratios: dict[str, float], expected: dict[str, int]
) -> None:
    """AC1: groups are split by ratio with exact counts; ties go to the model key."""
    assert quotas(n, ratios) == expected


RATIO_SETS = [
    {"a": 1.0},
    {"a": 1.0, "b": 1.0},
    {"a": 0.1, "b": 0.2},
    {"a": 3.0, "b": 1.0, "c": 1.0},
    {"c": 0.3, "a": 0.3, "b": 0.4},
    {"a": 1.0, "b": 2.0, "c": 3.0, "d": 4.0},
]


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize("ratios", RATIO_SETS)
def test_quotas_sum_to_n_and_are_never_negative(ratios: dict[str, float]) -> None:
    """AC1: counts are exact (sum to n), non-negative, and cover every model."""
    for n in range(21):
        counts = quotas(n, ratios)
        assert sum(counts.values()) == n
        assert min(counts.values()) >= 0
        assert set(counts) == set(ratios)


@pytest.mark.req("REQ-LLM-006")
def test_unpinned_adults_are_split_by_ratio_with_the_seed() -> None:
    """AC1: pins are kept; children get nothing; the split is seeded, exact and order-free."""
    ids = ["v5", "v1", "v7", "v0", "v3", "v6", "v2", "v4"]
    specs = [villager(v) for v in ids] + [villager("kid", age=5), villager("pin", model="b")]
    ratios = {"a": 3.0, "b": 1.0}
    one = assign_models(specs, 120, ratios, seed=1)
    again = assign_models(specs, 120, ratios, seed=1)
    reversed_ = assign_models(specs[::-1], 120, ratios, seed=1)
    models = {s.id: s.model for s in one}
    assert one == again
    assert {s.id: s.model for s in reversed_} == models
    assert models["kid"] is None and models["pin"] == "b"
    adults = [models[v] for v in ids]
    assert adults.count("a") == 6 and adults.count("b") == 2
    assert [s.id for s in one] == [s.id for s in specs]
    draws = {
        tuple(sorted((s.id, s.model) for s in assign_models(specs, 120, ratios, seed=n)))
        for n in range(1, 6)
    }
    assert len(draws) >= 2


@pytest.mark.req("REQ-LLM-006")
def test_no_ratios_assign_nothing() -> None:
    """AC1: without `assign`, unpinned villagers keep no model (scripted)."""
    specs = (villager("a"), villager("b", model="m"))
    assert assign_models(specs, 120, {}, seed=1) == specs
