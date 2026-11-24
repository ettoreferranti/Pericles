from collections.abc import Callable

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from pericles.agents.config import AgentConfig
from pericles.agents.scripted import scripted_controller
from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.geometry import Coord
from pericles.core.nodes import Node
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config

MakeWorld = Callable[..., WorldState]
ROWS = [
    "....TTTT....",
    "....TTTT.~~.",
    "...........~",
    "RR..........",
    "RR....~~....",
    "......~~....",
] * 2
TICKS, SPLIT = 600, 300

person = st.tuples(
    st.sampled_from(["female", "male"]),
    st.sampled_from([30, 200, 400]),
    st.integers(0, 6),
    st.integers(0, 11),
    st.integers(0, 11),
)
spot = st.tuples(
    st.sampled_from(["berry_bush", "tree", "boulder"]), st.integers(0, 11), st.integers(0, 11)
)


@pytest.mark.req("REQ-AGT-008", "REQ-EXP-003")
@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(st.lists(person, min_size=1, max_size=6), st.lists(spot, max_size=12))
def test_scripted_villages_keep_invariants_and_resume_exactly(
    registry: Registry,
    make_world: MakeWorld,
    people: list[tuple[str, int, int, int, int]],
    spots: list[tuple[str, int, int]],
) -> None:
    """AGT-008 AC1 / EXP-003 AC3: any small scripted village keeps the engine invariants, and
    restoring world + agent memory mid-run reproduces the rest of the run exactly."""
    config = default_config(debug_invariants=True, adult_age_days=100)
    villagers = []
    for i, (sex, age, berries, x, y) in enumerate(people):
        v = Villager(f"v{i}", f"V{i}", Coord(x, y), sex=sex, born_tick=0, adult=age >= 100)
        v.inventory.add(registry, "berries", berries)
        villagers.append(v)
    parents = [v.id for v in villagers if v.adult][:2]
    for v in villagers:
        if not v.adult and parents:
            v.parents = tuple(sorted(parents))
    nodes = [Node(f"n{i}", kind, Coord(x, y), 10) for i, (kind, x, y) in enumerate(spots)]
    state = make_world(ROWS, villagers, nodes)
    engine = Engine(registry, config)
    controller = scripted_controller(engine.context, AgentConfig())
    saved = None
    tail: list[object] = []
    for tick in range(TICKS):
        if tick == SPLIT:
            saved = (state.to_dict(), controller.to_dict())
        state, events = engine.step(state, controller.intents(state))
        controller.observe(state, events)
        if tick >= SPLIT:
            tail.extend(e.to_dict() for e in events)
    assert saved is not None
    again = WorldState.from_dict(saved[0])
    other = scripted_controller(Engine(registry, config).context, AgentConfig())
    other.load(saved[1])
    engine2 = Engine(registry, config)
    replay: list[object] = []
    for _ in range(SPLIT, TICKS):
        again, events = engine2.step(again, other.intents(again))
        other.observe(again, events)
        replay.extend(e.to_dict() for e in events)
    assert replay == tail
