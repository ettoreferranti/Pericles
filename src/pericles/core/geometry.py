"""Grid coordinates."""

from __future__ import annotations

from typing import NamedTuple


class Coord(NamedTuple):
    x: int
    y: int

    def neighbours4(self) -> tuple[Coord, Coord, Coord, Coord]:
        """Up, right, down, left (fixed order keeps searches deterministic)."""
        x, y = self
        return (Coord(x, y - 1), Coord(x + 1, y), Coord(x, y + 1), Coord(x - 1, y))

    def manhattan(self, other: Coord) -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)
