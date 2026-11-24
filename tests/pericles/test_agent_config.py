import dataclasses

import pytest

from pericles.agents.config import RELIEFS, AgentConfig


@pytest.mark.req("REQ-AGT-008")
def test_defaults_are_valid_and_cover_every_relief() -> None:
    """AC1: the scripted thresholds name a level for eating, sleeping and shelter."""
    config = AgentConfig()
    assert set(config.act_at) == set(RELIEFS) == set(config.urgent_at)
    assert all(config.act_at[r] <= config.urgent_at[r] for r in RELIEFS)


@pytest.mark.req("REQ-AGT-008")
@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"act_at": {"eat": 50.0, "sleep": 70.0}}, "act_at and urgent_at"),
        ({"urgent_at": {"eat": 40.0, "sleep": 90.0, "shelter": 80.0}}, "act_at <= urgent_at"),
        ({"act_at": {"eat": 0.0, "sleep": 70.0, "shelter": 60.0}}, "levels must be in (0, 100]"),
        ({"act_at": {"eat": 50.0, "sleep": 70.0, "shelter": float("nan")}}, "finite"),
        ({"warm_until": 70.0}, "warm_until"),
        ({"deposit_load": 0.0}, "deposit_load"),
        ({"deposit_load": 1.5}, "deposit_load"),
        ({"food_carry": -1.0}, "must be non-negative"),
        ({"food_reserve_per_capita": -1.0}, "must be non-negative"),
        ({"storage_per_capita": -1.0}, "must be non-negative"),
        ({"skill_weight": -1.0}, "must be non-negative"),
        ({"site_search_radius": -1}, "must be non-negative"),
        ({"site_gap": -1}, "must be non-negative"),
        ({"node_search_radius": -1}, "must be non-negative"),
        ({"child_follow_radius": -1}, "must be non-negative"),
        ({"index_cell": 0}, "must be positive"),
        ({"avoid_ticks": 0}, "must be positive"),
        ({"idle_ticks": 0}, "must be positive"),
        ({"max_builders": 0}, "must be positive"),
        ({"house_building": ""}, "building ids must be non-empty"),
        ({"store_building": ""}, "building ids must be non-empty"),
    ],
)
def test_bad_values_are_rejected(overrides: dict[str, object], message: str) -> None:
    """AC1: nonsensical scripted-behaviour parameters fail at construction."""
    with pytest.raises(ValueError, match=message.replace("(", r"\(").replace(")", r"\)")):
        dataclasses.replace(AgentConfig(), **overrides)  # type: ignore[arg-type]
