import dataclasses
import math

import pytest

from pericles.agents.config import RELIEFS, STEERING, TRIGGERS, AgentConfig, ticks_for_hours


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


def test_plan_mind_defaults() -> None:
    c = AgentConfig()
    assert (c.perception_radius, c.replan_hours, c.fallback_hours) == (12, 6.0, 1.0)
    assert (c.max_retries, c.max_plan_steps, c.prompt_budget_tokens) == (2, 6, 2000)
    assert (c.chars_per_token, c.plan_template, c.drawn_traits) == (4.0, "plan.v1", 0)
    assert c.triggers == TRIGGERS == ("idle", "step_completed", "step_failed", "need", "periodic")
    assert c.steering_phrases == STEERING
    assert "you must obey" in STEERING and "you may break" in STEERING


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("perception_radius", 0, "cells, tick counts and builder limits must be positive"),
        ("max_plan_steps", 0, "cells, tick counts and builder limits must be positive"),
        ("prompt_budget_tokens", 0, "cells, tick counts and builder limits must be positive"),
        ("replan_hours", 0.0, "hours and chars_per_token must be positive"),
        ("fallback_hours", -1.0, "hours and chars_per_token must be positive"),
        ("chars_per_token", 0.0, "hours and chars_per_token must be positive"),
        ("replan_hours", math.nan, "numeric parameters must be finite"),
        ("chars_per_token", math.inf, "numeric parameters must be finite"),
        ("max_retries", -1, "max_retries and drawn_traits must be non-negative"),
        ("drawn_traits", -1, "max_retries and drawn_traits must be non-negative"),
        ("triggers", ("need",), "triggers must be distinct names from"),
        ("triggers", ("idle", "idle"), "triggers must be distinct names from"),
        ("triggers", ("idle", "meeting"), "triggers must be distinct names from"),
        ("plan_template", "", "plan_template and steering phrases must be non-empty"),
        ("steering_phrases", ("ok", ""), "plan_template and steering phrases must be non-empty"),
    ],
)
def test_plan_mind_fields_are_checked(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AgentConfig(**{field: value})  # type: ignore[arg-type]


def test_ticks_for_hours_rounds_and_is_at_least_one() -> None:
    assert ticks_for_hours(10, 6.0) == 36
    assert ticks_for_hours(10, 0.25) == 2  # 1.5 rounds to 2
    assert ticks_for_hours(60, 0.1) == 1
