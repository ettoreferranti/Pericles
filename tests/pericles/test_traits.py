import pytest

from pericles.experiment.config import VillagerSpec
from pericles.experiment.traits import draw_traits

IDS = ("altruistic", "dutiful", "fearful", "greedy", "industrious", "rebellious")


def spec(vid: str, traits: tuple[str, ...] | None = None) -> VillagerSpec:
    data: dict[str, object] = {"id": vid, "name": vid.title(), "age_days": 200}
    if traits is not None:
        data["traits"] = traits
    return VillagerSpec.model_validate(data)


@pytest.mark.req("REQ-AGT-009")
def test_omitted_traits_are_drawn_with_the_seed_and_given_traits_kept() -> None:
    """AC1: traits come from config, or are drawn with the seeded RNG."""
    population = [spec("ada"), spec("bram", ("greedy",)), spec("cora", ())]
    drawn = draw_traits(population, IDS, 2, seed=5)
    assert drawn[1].traits == ("greedy",) and drawn[2].traits == ()
    assert drawn[0].traits is not None and len(drawn[0].traits) == 2
    assert len(set(drawn[0].traits)) == 2 and set(drawn[0].traits) <= set(IDS)
    assert drawn[0].traits == tuple(sorted(drawn[0].traits))
    assert draw_traits(population, IDS, 2, seed=5) == drawn
    others = {draw_traits(population, IDS, 2, seed=s)[0].traits for s in range(20)}
    assert len(others) > 1


def test_zero_count_draws_nothing_and_too_many_is_an_error() -> None:
    assert draw_traits([spec("ada")], IDS, 0, seed=1)[0].traits is None
    with pytest.raises(ValueError, match="drawn_traits: 7 is more than the 6 traits"):
        draw_traits([spec("ada")], IDS, 7, seed=1)
