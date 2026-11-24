import dataclasses
from pathlib import Path

import pytest
import yaml

from pericles.agents.config import AgentConfig
from pericles.core.config import EngineConfig
from pericles.core.content.loader import read_yaml
from pericles.core.modifiers import Modifier, Op, Target
from pericles.experiment.defaults import (
    DEFAULT_CALENDAR,
    DEFAULT_SETTINGS,
    default_agent_config,
    default_config,
    default_settings_mapping,
)
from pericles.experiment.settings import (
    SettingsError,
    agent_config_from_mapping,
    engine_config_from_mapping,
    load_agent_settings,
    load_settings,
)


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.req("REQ-EXP-001")
def test_settings_set_engine_parameters(tmp_path: Path) -> None:
    """AC2: a settings file sets engine parameters; omitted ones keep the core default."""
    path = write(
        tmp_path,
        "engine:\n"
        "  carry_limit: 12\n"
        "  sexes: [a, b]\n"
        "  bearing_sex: b\n"
        "  adult_model: llama\n"
        "  debug_invariants: true\n",
    )
    config = load_settings(path)
    assert config.carry_limit == 12.0
    assert isinstance(config.carry_limit, float)
    assert config.sexes == ("a", "b")
    assert config.bearing_sex == "b"
    assert config.adult_model == "llama"
    assert config.debug_invariants is True
    assert config.max_health == EngineConfig().max_health


@pytest.mark.req("REQ-EXP-001")
def test_settings_build_a_calendar_with_season_modifiers(tmp_path: Path) -> None:
    """AC2: seasons, blocked tags and season modifiers come from the file."""
    path = write(
        tmp_path,
        "engine:\n"
        "  calendar:\n"
        "    day_minutes: 60\n"
        "    sunrise_minute: 10\n"
        "    sunset_minute: 50\n"
        "    seasons:\n"
        "      - {name: warm, days: 2}\n"
        "      - name: cold\n"
        "        days: 3\n"
        "        blocked_tags: [sowing]\n"
        "        modifiers:\n"
        "          - {target: {kind: need, id: cold}, attribute: rate, op: mul, value: 4}\n",
    )
    calendar = load_settings(path).calendar
    assert calendar.day_minutes == 60
    assert [s.name for s in calendar.seasons] == ["warm", "cold"]
    cold = calendar.seasons[1]
    assert cold.blocked_tags == ("sowing",)
    assert cold.modifiers == (Modifier(Target("need", "cold"), "rate", Op.MUL, 4.0, "season:cold"),)


@pytest.mark.req("REQ-EXP-001")
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("engine:\n  carry_limt: 3\n", r"^engine\.carry_limt: unknown setting$"),
        ("engine:\n  carry_limit: heavy\n", r"^engine\.carry_limit: "),
        ("engine:\n  carry_limit: true\n", r"^engine\.carry_limit: "),
        ("engine:\n  gestation_days: 2.5\n", r"^engine\.gestation_days: "),
        ("engine:\n  sexes: a\n", r"^engine\.sexes: "),
        ("engine:\n  carry_limit: 0\n", r"^engine: carry_limit must be positive$"),
        (
            "engine:\n  calendar: {seasons: [{days: 3}]}\n",
            r"^engine\.calendar\.seasons\[0\]\.name: missing$",
        ),
        ("engine:\n  calendar: {}\n", r"^engine\.calendar\.seasons: missing$"),
        (
            "engine:\n  calendar: {seasons: [{name: a, days: 0}]}\n",
            r"^engine\.calendar: every season must last at least one day$",
        ),
        (
            "engine:\n  calendar: {seasons: [x]}\n",
            r"^engine\.calendar\.seasons\[0\]: expected a mapping$",
        ),
        (
            "engine:\n"
            "  calendar: {seasons: [{name: a, days: 3, modifiers: [{attribute: rate}]}]}\n",
            r"^engine\.calendar\.seasons\[0\]\.modifiers\.0\.target: ",
        ),
        (
            "engine:\n  calendar: {seasons: [{name: a, days: 3, colour: red}]}\n",
            r"^engine\.calendar\.seasons\[0\]\.colour: unknown setting$",
        ),
        (
            "engine:\n  calendar: {seasons: [{name: a, days: 3, modifiers: }]}\n",
            r"^engine\.calendar\.seasons\[0\]\.modifiers: expected a list$",
        ),
        (
            "engine:\n  calendar: {seasons: [{name: a, days: 3, modifiers: 3}]}\n",
            r"^engine\.calendar\.seasons\[0\]\.modifiers: expected a list$",
        ),
        ("engine:\n  calendar: {seasons: 3}\n", r"^engine\.calendar\.seasons: expected a list$"),
        ("engine: 3\n", r"^engine: expected a mapping$"),
        ("map: {}\n", r"^map: unknown section$"),
        ("engine: {carry_limit: 1}\nengine: {carry_limit: 2}\n", r"duplicate key 'engine'"),
    ],
)
def test_settings_errors_name_the_field(tmp_path: Path, text: str, message: str) -> None:
    """AC2: errors name the field and the problem; no raw TypeError or KeyError escapes."""
    with pytest.raises(SettingsError, match=message):
        load_settings(write(tmp_path, text))


def test_an_empty_settings_file_gives_core_defaults(tmp_path: Path) -> None:
    """No engine section means every parameter keeps its core default."""
    assert load_settings(write(tmp_path, "")) == EngineConfig()


def test_engine_config_from_mapping_takes_a_where_prefix() -> None:
    """Callers embedding the engine section elsewhere get their own path in errors."""
    with pytest.raises(SettingsError, match=r"^experiment\.engine\.x: unknown setting$"):
        engine_config_from_mapping({"x": 1}, where="experiment.engine")


def test_default_settings_list_every_engine_parameter() -> None:
    """No magic values: every EngineConfig field is spelled out in the default settings file."""
    raw = yaml.safe_load(DEFAULT_SETTINGS.read_text(encoding="utf-8"))
    assert sorted(raw["engine"]) == sorted(f.name for f in dataclasses.fields(EngineConfig))
    calendar_fields = {"seasons", "tick_minutes", "day_minutes", "sunrise_minute", "sunset_minute"}
    assert set(raw["engine"]["calendar"]) == calendar_fields


def test_default_config_is_the_four_season_year() -> None:
    """The playable default is four 10-day seasons; winter blocks sowing."""
    assert [(s.name, s.days) for s in DEFAULT_CALENDAR.seasons] == [
        ("spring", 10),
        ("summer", 10),
        ("autumn", 10),
        ("winter", 10),
    ]
    assert DEFAULT_CALENDAR.seasons[3].blocked_tags == ("sowing",)
    assert default_config(carry_limit=5.0).carry_limit == 5.0
    assert default_config().calendar == DEFAULT_CALENDAR


@pytest.mark.req("REQ-SIM-003")
def test_the_default_winter_raises_food_and_warmth_needs() -> None:
    """AC2: the playable winter multiplies hunger and cold rates (values tweakable in the file)."""
    winter = DEFAULT_CALENDAR.seasons[3]
    assert winter.modifiers == (
        Modifier(Target("need", "hunger"), "rate", Op.MUL, 1.5, "season:winter"),
        Modifier(Target("need", "cold"), "rate", Op.MUL, 6.0, "season:winter"),
    )
    assert all(s.modifiers == () for s in DEFAULT_CALENDAR.seasons[:3])


@pytest.mark.req("REQ-EXP-001")
def test_agents_section_loads_with_named_errors(tmp_path: Path) -> None:
    """AC2: the agents section is validated; errors name the field."""
    good = agent_config_from_mapping(
        {"idle_ticks": 5, "act_at": {"eat": 40.0, "sleep": 70.0, "shelter": 60.0}}
    )
    assert good.idle_ticks == 5 and good.act_at["eat"] == 40.0
    for data, prefix in [
        ({"idle": 5}, "agents.idle: unknown setting"),
        ({"idle_ticks": "5"}, "agents.idle_ticks:"),
        ({"idle_ticks": True}, "agents.idle_ticks:"),
        ({"act_at": [1.0]}, "agents.act_at:"),
        ({"deposit_load": 2.0}, "agents: deposit_load"),
        ([1, 2], "agents: expected a mapping"),
    ]:
        with pytest.raises(SettingsError) as caught:
            agent_config_from_mapping(data)
        assert str(caught.value).startswith(prefix), str(caught.value)


@pytest.mark.req("REQ-EXP-001")
def test_load_agent_settings_reads_the_agents_section(tmp_path: Path) -> None:
    """AC1: a settings file sets agent parameters; unknown sections are refused."""
    path = tmp_path / "s.yaml"
    path.write_text("agents:\n  idle_ticks: 7\n", encoding="utf-8")
    assert load_agent_settings(path).idle_ticks == 7
    path.write_text("agentz: {}\n", encoding="utf-8")
    with pytest.raises(SettingsError, match="agentz: unknown section"):
        load_agent_settings(path)


@pytest.mark.req("REQ-EXP-001")
def test_default_settings_list_every_agent_parameter() -> None:
    """AC1: the packaged settings file spells out every agent parameter."""
    raw = read_yaml(DEFAULT_SETTINGS)
    assert set(raw["agents"]) == {f.name for f in dataclasses.fields(AgentConfig)}
    assert default_settings_mapping() == raw
    assert default_agent_config() == AgentConfig()
    assert default_agent_config(idle_ticks=3).idle_ticks == 3
