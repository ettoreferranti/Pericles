import os
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
import yaml

from pericles.experiment.config import experiment_from_mapping, load_experiment
from pericles.experiment.launch import advance, start
from pericles.experiment.rundir import RunDirectory
from pericles.llm.fake import FakeBackend

GOLDEN = Path(__file__).parent
UPDATE = os.environ.get("PERICLES_UPDATE_GOLDEN") == "1"


@pytest.fixture(scope="module")
def recorded(tmp_path_factory: pytest.TempPathFactory) -> tuple[str, Path]:
    """The record leg, run once for the module."""
    out = tmp_path_factory.mktemp("golden") / "rec"
    session = start(load_experiment(GOLDEN / "village.yaml"), out)
    advance(session)
    session.close()
    run = RunDirectory.open(out)
    digest = run.event_log.digest()
    run.close()
    return digest, out


@pytest.mark.req("REQ-NFR-001")
def test_golden_run_digest_is_pinned_and_replay_reproduces_it(
    recorded: tuple[str, Path], tmp_path: Path
) -> None:
    """AC1: same config, seed and LLM cache in replay mode give the identical event-log hash."""
    digest, out = recorded
    pinned = GOLDEN / "village.digest"
    if UPDATE and os.environ.get("CI"):
        pytest.fail("PERICLES_UPDATE_GOLDEN must not be set in CI")
    cache = tmp_path / "cache.sqlite"
    shutil.copy(out / "llm_cache" / "responses.sqlite", cache)
    raw = cast(dict[str, Any], yaml.safe_load((GOLDEN / "village.yaml").read_text("utf-8")))
    raw["llm"].update({"cache": "replay", "cache_from": str(cache)})
    session = start(experiment_from_mapping(raw, GOLDEN), tmp_path / "replay")
    advance(session)
    backends = session.gateway.backends
    assert backends
    assert sum(len(cast(FakeBackend, b).calls) for b in backends.values()) == 0
    session.close()
    replayed = RunDirectory.open(tmp_path / "replay")
    assert replayed.event_log.digest() == digest
    replayed.close()
    if UPDATE:
        pinned.write_text(digest + "\n", encoding="utf-8")
        pytest.skip("golden digest updated; re-run without PERICLES_UPDATE_GOLDEN")
    assert digest == pinned.read_text(encoding="utf-8").strip()


def test_golden_run_exercises_plans_retries_and_steps(recorded: tuple[str, Path]) -> None:
    _, out = recorded
    run = RunDirectory.open(out)
    events = list(run.event_log.events())
    run.close()
    kinds = [e.kind for e in events]
    assert kinds.count("plan_made") >= 4
    assert "plan_step" in kinds
    invalid = next(
        i for i, e in enumerate(events) if e.kind == "plan_invalid" and e.data["actor"] == "cora"
    )
    assert any(e.kind == "plan_made" and e.data["actor"] == "cora" for e in events[invalid:])
