"""Daily survival metrics from the resolved config and the event log (REQ-EXP-003; ADR-0016 §6)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pericles.core.events import Event

DEATHS = "deaths"


@dataclass(frozen=True)
class Row:
    day: int
    metric: str
    value: float


def ticks_per_day(config: Mapping[str, Any]) -> int:
    calendar = config["engine"]["calendar"]
    return int(calendar["day_minutes"]) // int(calendar["tick_minutes"])


def daily_survival(
    config: Mapping[str, Any], events: Iterable[Event], last_tick: int | None
) -> list[Row]:
    """Rows per day up to `last_tick`'s day: population, adults, children, births, deaths
    (and `deaths.<cause>`), food eaten. Events must come in tick order.

    Pass the current tick as `last_tick`: the last row is then the village at the start of
    the current day, with that day's counts so far (zero at its first tick)."""
    per_day = ticks_per_day(config)
    adult_age = int(config["engine"]["adult_age_days"])
    population = [(str(v["id"]), int(v["age_days"])) for v in config["population"]]
    adults = {vid for vid, age in population if age >= adult_age}
    children = {vid for vid, _ in population} - adults
    counts: Counter[str] = Counter()
    food = 0.0
    rows: list[Row] = []
    day = 0

    def close() -> None:
        nonlocal food
        rows.extend(
            [
                Row(day, "population", float(len(adults) + len(children))),
                Row(day, "adults", float(len(adults))),
                Row(day, "children", float(len(children))),
                Row(day, "births", float(counts["births"])),
                Row(day, DEATHS, float(counts[DEATHS])),
                Row(day, "food_eaten", food),
            ]
        )
        rows.extend(
            Row(day, key, float(n))
            for key, n in sorted(counts.items())
            if key.startswith(DEATHS + ".")
        )
        counts.clear()
        food = 0.0

    for event in events:
        while event.tick // per_day > day:
            close()
            day += 1
        data = event.data
        if event.kind == "born":
            children.add(str(data["child"]))
            counts["births"] += 1
        elif event.kind == "died":
            vid = str(data["villager"])
            adults.discard(vid)
            children.discard(vid)
            counts[DEATHS] += 1
            counts[f"{DEATHS}.{data['cause']}"] += 1
        elif event.kind == "came_of_age":
            vid = str(data["villager"])
            children.discard(vid)
            adults.add(vid)
        elif event.kind == "ate":
            food += float(data["nutrition"])
    if last_tick is None:
        return []
    while day <= last_tick // per_day:
        close()
        day += 1
    return rows
