from pathlib import Path

import pytest

from pericles.core.content.loader import ContentError, _location, load_pack
from pericles.core.content.schema import ActionDef, TerrainDef

pytestmark = pytest.mark.req("REQ-SIM-005")

VALID = """
terrains:
  - {id: grass, walkable: true, move_cost: 1.0, color: "#8fb35a"}
  - {id: water, walkable: false, color: "#3b6ea5"}
items:
  - {id: wood, weight: 2.0}
actions:
  - id: fell
    duration_ticks: 60
    outputs: {wood: 2}
    skill: woodcutting
"""


def pack(tmp_path: Path, files: dict[str, str]) -> Path:
    root = tmp_path / "mypack"
    root.mkdir()
    for name, text in files.items():
        (root / name).write_text(text, encoding="utf-8")
    return root


def test_loads_sections_from_all_yaml_files(tmp_path: Path) -> None:
    """AC1: a valid pack loads; definitions are typed and keyed by id."""
    loaded = load_pack(pack(tmp_path, {"a.yaml": VALID, "b.yaml": "items:\n  - {id: stone}\n"}))
    assert loaded.name == "mypack"
    assert loaded.path.name == "mypack"
    assert sorted(loaded.defs["items"]) == ["stone", "wood"]
    grass = loaded.defs["terrains"]["grass"]
    assert isinstance(grass, TerrainDef) and grass.walkable is True
    fell = loaded.defs["actions"]["fell"]
    assert isinstance(fell, ActionDef)
    assert fell.outputs == {"wood": 2}
    assert fell.inputs == {}
    assert loaded.defs["recipes"] == {}


def test_defaults_are_applied(tmp_path: Path) -> None:
    loaded = load_pack(pack(tmp_path, {"a.yaml": VALID}))
    water = loaded.defs["terrains"]["water"]
    assert isinstance(water, TerrainDef) and water.move_cost == 1.0


@pytest.mark.parametrize(
    ("text", "fragment"),
    [
        (
            VALID.replace("duration_ticks: 60", "duraton_ticks: 60"),
            "actions[fell].duraton_ticks: Extra inputs are not permitted",
        ),
        (VALID.replace("duration_ticks: 60", "duration_ticks: -5"), "actions[fell].duration_ticks"),
        (
            VALID.replace("duration_ticks: 60", "duration_ticks: soon"),
            "actions[fell].duration_ticks",
        ),
        (VALID.replace("weight: 2.0", "weight: -1"), "items[wood].weight"),
        (VALID.replace("id: fell", "id: Fell"), "actions[Fell].id"),
        (VALID.replace('"#8fb35a"', "green"), "terrains[grass].color"),
        (VALID.replace("outputs: {wood: 2}", "outputs: {wood: 0}"), "actions[fell].outputs.wood"),
        ("monsters:\n  - {id: x}\n", "monsters: Extra inputs are not permitted"),
    ],
    ids=[
        "typo-key",
        "negative",
        "wrong-type",
        "negative-weight",
        "bad-id",
        "bad-color",
        "zero-count",
        "unknown-section",
    ],
)
def test_invalid_definitions_name_file_definition_and_field(
    tmp_path: Path, text: str, fragment: str
) -> None:
    """AC1: invalid packs are rejected with file, path and problem."""
    root = pack(tmp_path, {"a.yaml": text})
    with pytest.raises(ContentError) as excinfo:
        load_pack(root)
    message = str(excinfo.value)
    assert str(root / "a.yaml") in message
    assert fragment in message


def test_invalid_yaml(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match=r"a\.yaml: invalid YAML"):
        load_pack(pack(tmp_path, {"a.yaml": "items: [\n"}))


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="top level must be a mapping of sections, got list"):
        load_pack(pack(tmp_path, {"a.yaml": "- id: wood\n"}))


def test_empty_file_is_allowed(tmp_path: Path) -> None:
    loaded = load_pack(pack(tmp_path, {"a.yaml": VALID, "empty.yaml": ""}))
    assert "wood" in loaded.defs["items"]


def test_duplicate_id_within_pack(tmp_path: Path) -> None:
    root = pack(tmp_path, {"a.yaml": VALID, "b.yaml": "items:\n  - {id: wood}\n"})
    with pytest.raises(ContentError, match=r"b\.yaml: items\[wood\]: duplicate id"):
        load_pack(root)


def test_pack_without_yaml_files(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match=r"no \.yaml files"):
        load_pack(pack(tmp_path, {"notes.txt": "x"}))


def test_pack_must_be_a_directory(tmp_path: Path) -> None:
    with pytest.raises(ContentError, match="must be a directory"):
        load_pack(tmp_path / "missing")


def test_every_problem_is_reported_on_its_own_line(tmp_path: Path) -> None:
    text = VALID.replace("weight: 2.0", "weight: -1").replace(
        "duration_ticks: 60", "duration_ticks: -5"
    )
    with pytest.raises(ContentError) as excinfo:
        load_pack(pack(tmp_path, {"a.yaml": text}))
    lines = str(excinfo.value).splitlines()
    assert len(lines) == 2
    assert all(line.startswith(str(tmp_path / "mypack" / "a.yaml") + ": ") for line in lines)
    assert sorted(line.split(": ")[1] for line in lines) == [
        "actions[fell].duration_ticks",
        "items[wood].weight",
    ]


def test_location_helper_edge_cases() -> None:
    assert _location({"a": [1]}, ("a", "x")) == "a.x"
    assert _location({"items": [{"id": "w"}]}, ("items", 1)) == "items.1"
    assert _location({"items": [5]}, ("items", 0)) == "items[0]"
    assert _location({"items": [{"id": 5}]}, ("items", 0)) == "items[0]"
    assert _location({"items": [{"id": "w"}]}, ("items", 0, "weight")) == "items[w].weight"
    top: list[object] = [{"id": "x", "a": [{"id": "y"}]}]
    assert _location(top, (0, "a", 0)) == "[x].a[y]"  # type: ignore[arg-type]
