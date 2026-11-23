import dataclasses
from pathlib import Path

import pytest
import yaml

from pericles.core.config import EngineConfig
from pericles.core.modifiers import Modifier, Op, Target
from pericles.experiment.defaults import DEFAULT_CALENDAR, DEFAULT_SETTINGS, default_config
from pericles.experiment.settings import SettingsError, engine_config_from_mapping, load_settings


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
