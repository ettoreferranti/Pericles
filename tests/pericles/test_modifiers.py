import pytest

from pericles.core.content.schema import ModifierDef, TargetDef
from pericles.core.modifiers import Effective, Modifier, Op, Scope, Target, expire, resolve

pytestmark = pytest.mark.req("REQ-SIM-006")


def effective(
    mods: list[Modifier],
    tick: int = 0,
    base: float = 10.0,
    villager: str | None = None,
    building: str | None = None,
) -> Effective:
    return resolve(
        mods,
        kind="action",
        ident="fell_tree",
        tags=("labour",),
        attribute="work_speed",
        base=base,
        tick=tick,
        villager=villager,
        building=building,
    )


def value(
    mods: list[Modifier],
    tick: int = 0,
    villager: str | None = None,
    building: str | None = None,
) -> float:
    return effective(mods, tick=tick, villager=villager, building=building).value


def mod(
    op: Op,
    value: float,
    source: str = "s",
    attribute: str = "work_speed",
    target: Target | None = None,
    scope: Scope | None = None,
) -> Modifier:
    return Modifier(
        target=target or Target(kind="action", id="fell_tree"),
        attribute=attribute,
        op=op,
        value=value,
        source=source,
        scope=scope or Scope(),
    )


def test_no_modifiers_returns_base() -> None:
    result = effective([])
    assert (result.base, result.value, result.contributions) == (10.0, 10.0, ())


def test_stacking_order_is_set_then_add_then_mul() -> None:
    """AC2: deterministic stacking order regardless of list order."""
    mods = [mod(Op.MUL, 1.5, "tool"), mod(Op.ADD, 2, "skill"), mod(Op.SET, 4, "law")]
    assert value(mods) == pytest.approx((4 + 2) * 1.5)
    assert value(list(reversed(mods))) == pytest.approx((4 + 2) * 1.5)


def test_last_set_wins() -> None:
    assert value([mod(Op.SET, 4), mod(Op.SET, 7)]) == 7


def test_adds_and_muls_accumulate() -> None:
    assert value([mod(Op.ADD, 1), mod(Op.ADD, 2), mod(Op.MUL, 2), mod(Op.MUL, 3)]) == 78


@pytest.mark.parametrize(
    ("target", "matches"),
    [
        (Target(kind="action"), True),
        (Target(kind="action", id="fell_tree"), True),
        (Target(kind="action", id="quarry_stone"), False),
        (Target(kind="action", tag="labour"), True),
        (Target(kind="action", tag="leisure"), False),
        (Target(kind="action", id="fell_tree", tag="leisure"), False),
        (Target(kind="recipe", id="fell_tree"), False),
    ],
)
def test_selector_matching(target: Target, matches: bool) -> None:
    """AC1: modifiers apply to matching targets only."""
    assert (value([mod(Op.ADD, 5, target=target)]) == 15) is matches


def test_other_attribute_is_ignored() -> None:
    assert value([mod(Op.ADD, 5, attribute="yield")]) == 10


def test_villager_and_building_scopes() -> None:
    """AC4: scoped modifiers apply only within their scope."""
    mine = mod(Op.ADD, 5, scope=Scope(villager="ana"))
    assert value([mine], villager="ana") == 15
    assert value([mine], villager="bo") == 10
    assert value([mine]) == 10
    hut = mod(Op.ADD, 5, scope=Scope(building="b1"))
    assert value([hut], building="b1") == 15
    assert value([hut], building="b2") == 10


def test_time_limited_scope_applies_until_exclusive_tick() -> None:
    """AC4: time-limited modifiers expire."""
    drought = mod(Op.MUL, 0.5, scope=Scope(until_tick=100))
    assert value([drought], tick=99) == 5
    assert value([drought], tick=100) == 10
    assert expire([drought, mod(Op.ADD, 1)], tick=99) == (drought, mod(Op.ADD, 1))
    assert expire([drought, mod(Op.ADD, 1)], tick=100) == (mod(Op.ADD, 1),)


def test_explain_lists_base_and_sources_in_application_order() -> None:
    """AC3: every effective value is explainable."""
    mods = [mod(Op.MUL, 1.5, "axe"), mod(Op.ADD, 2, "skill:woodcutting")]
    result = effective(mods)
    assert [m.source for m in result.contributions] == ["skill:woodcutting", "axe"]
    assert result.explain() == "work_speed base 10 → +2 (skill:woodcutting) → ×1.5 (axe) = 18"  # noqa: RUF001


def test_explain_without_modifiers() -> None:
    assert effective([], base=3.0).explain() == "work_speed base 3 = 3"


def test_explain_set() -> None:
    assert effective([mod(Op.SET, 4, "law")], base=3.0).explain() == (
        "work_speed base 3 → =4 (law) = 4"
    )


def test_from_def_and_round_trip() -> None:
    definition = ModifierDef(
        target=TargetDef(kind="action", tag="labour"), attribute="work_speed", op="mul", value=1.1
    )
    modifier = Modifier.from_def(definition, source="trait:industrious", scope=Scope(villager="a"))
    assert modifier.op is Op.MUL
    assert modifier.target == Target(kind="action", tag="labour")
    assert Modifier.from_dict(modifier.to_dict()) == modifier
    assert modifier.to_dict() == {
        "target": {"kind": "action", "id": None, "tag": "labour"},
        "attribute": "work_speed",
        "op": "mul",
        "value": 1.1,
        "source": "trait:industrious",
        "scope": {"villager": "a", "building": None, "until_tick": None},
    }


def test_from_def_keeps_id_and_defaults_scope() -> None:
    definition = ModifierDef(
        target=TargetDef(kind="action", id="fell_tree"), attribute="work_speed", op="add", value=2
    )
    modifier = Modifier.from_def(definition, source="s")
    assert modifier.target == Target(kind="action", id="fell_tree")
    assert modifier.scope == Scope()


def test_round_trip_preserves_all_fields() -> None:
    modifier = Modifier(
        target=Target(kind="action", id="fell_tree", tag="labour"),
        attribute="work_speed",
        op=Op.SET,
        value=3.0,
        source="law",
        scope=Scope(villager="a", building="b", until_tick=7),
    )
    assert Modifier.from_dict(modifier.to_dict()) == modifier
