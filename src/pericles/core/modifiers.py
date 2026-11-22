"""Modifiers: the single mechanism through which effects alter the world (REQ-SIM-006)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pericles.core.content.schema import ModifierDef


class Op(StrEnum):
    ADD = "add"
    MUL = "mul"
    SET = "set"


ORDER = (Op.SET, Op.ADD, Op.MUL)
SYMBOL = {Op.SET: "=", Op.ADD: "+", Op.MUL: "×"}  # noqa: RUF001


@dataclass(frozen=True)
class Target:
    kind: str
    id: str | None = None
    tag: str | None = None

    def matches(self, kind: str, ident: str, tags: Iterable[str] = ()) -> bool:
        return (
            self.kind == kind
            and (self.id is None or self.id == ident)
            and (self.tag is None or self.tag in tuple(tags))
        )


@dataclass(frozen=True)
class Scope:
    villager: str | None = None
    building: str | None = None
    until_tick: int | None = None

    def active_at(self, tick: int) -> bool:
        return self.until_tick is None or tick < self.until_tick

    def applies(self, tick: int, villager: str | None, building: str | None) -> bool:
        return (
            self.active_at(tick)
            and (self.villager is None or self.villager == villager)
            and (self.building is None or self.building == building)
        )


@dataclass(frozen=True)
class Modifier:
    target: Target
    attribute: str
    op: Op
    value: float
    source: str
    scope: Scope = field(default_factory=Scope)

    @classmethod
    def from_def(cls, definition: ModifierDef, source: str, scope: Scope | None = None) -> Modifier:
        return cls(
            target=Target(definition.target.kind, definition.target.id, definition.target.tag),
            attribute=definition.attribute,
            op=Op(definition.op),
            value=definition.value,
            source=source,
            scope=scope if scope is not None else Scope(),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": {"kind": self.target.kind, "id": self.target.id, "tag": self.target.tag},
            "attribute": self.attribute,
            "op": self.op.value,
            "value": self.value,
            "source": self.source,
            "scope": {
                "villager": self.scope.villager,
                "building": self.scope.building,
                "until_tick": self.scope.until_tick,
            },
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Modifier:
        target, scope = data["target"], data["scope"]
        return cls(
            target=Target(target["kind"], target["id"], target["tag"]),
            attribute=data["attribute"],
            op=Op(data["op"]),
            value=float(data["value"]),
            source=data["source"],
            scope=Scope(scope["villager"], scope["building"], scope["until_tick"]),
        )


def _fmt(number: float) -> str:
    return f"{number:g}"


@dataclass(frozen=True)
class Effective:
    attribute: str
    base: float
    value: float
    contributions: tuple[Modifier, ...]

    def explain(self) -> str:
        steps = "".join(
            f" → {SYMBOL[m.op]}{_fmt(m.value)} ({m.source})" for m in self.contributions
        )
        return f"{self.attribute} base {_fmt(self.base)}{steps} = {_fmt(self.value)}"


def resolve(
    modifiers: Iterable[Modifier],
    *,
    kind: str,
    ident: str,
    attribute: str,
    base: float,
    tick: int,
    tags: Iterable[str] = (),
    villager: str | None = None,
    building: str | None = None,
) -> Effective:
    """Fold the matching modifiers over `base` (REQ-SIM-006 AC2).

    Stacking order: matching modifiers apply in the order set, then add, then mul.
    Within each op the given list order is kept. Among `set` modifiers the last one
    wins; `add` values sum; `mul` values multiply.
    """
    tag_tuple = tuple(tags)
    active = [
        m
        for m in modifiers
        if m.attribute == attribute
        and m.target.matches(kind, ident, tag_tuple)
        and m.scope.applies(tick, villager, building)
    ]
    ordered = tuple(m for op in ORDER for m in active if m.op is op)
    value = base
    for m in ordered:
        if m.op is Op.SET:
            value = m.value
        elif m.op is Op.ADD:
            value += m.value
        else:
            value *= m.value
    return Effective(attribute=attribute, base=base, value=value, contributions=ordered)


def expire(modifiers: Iterable[Modifier], tick: int) -> tuple[Modifier, ...]:
    return tuple(m for m in modifiers if m.scope.active_at(tick))
