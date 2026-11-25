import pytest

from pericles_tools.bench import measure

REQUIRED_TICKS_PER_SECOND = 1000  # REQ-NFR-003 AC1


@pytest.mark.perf
@pytest.mark.req("REQ-NFR-003")
def test_the_engine_sustains_1000_ticks_per_second() -> None:
    """AC1: 150 scripted villagers on a 128x128 map, no LLM calls, on the target machine."""
    assert measure(villagers=150, size=128) >= REQUIRED_TICKS_PER_SECOND
