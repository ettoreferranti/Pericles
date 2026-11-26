# M2a LLM Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Pericles one well-tested way to call a language model. A new `pericles.llm` gateway talks to Ollama, MLX or a scripted fake backend. It validates output against schemas, caches responses so runs replay bit-exactly, logs every call with its metrics, batches requests by model, and survives backend outages. `experiment.yaml` gains an `llm:` section that defines backends and models and assigns them to villagers. The plan also fixes the experiment-facing minors held over from M1d.

**Architecture:**
- **`pericles.llm`** is a new package that knows nothing about villages.
  - A `Backend` turns a `BackendCall` into a `Completion`. Three backends exist: `OllamaBackend` (HTTP via the standard library), `MLXBackend` (in-process, Apple Silicon, optional extra) and `FakeBackend` (scripted).
  - The `Gateway` is the only thing the agent layer will call. It takes `Request`s naming a *logical* model (a key of `llm.models`), resolves it to a backend and sampling parameters, consults the `ResponseCache`, calls backends in per-model batches with a per-backend concurrency limit, validates JSON against a pydantic output model, writes one `CallRecord` per call to the `CallLog`, and applies the failure policy.
- **Calls stay out of the event log.** Latency and token counts differ between a recorded run and its replay, so they live in `llm_calls.sqlite` next to `events.sqlite`. The event-log digest therefore stays identical under replay (REQ-LLM-005 AC3).
- **`pericles.experiment`** builds backends from the `llm:` section, checks that every configured model exists before it creates a run directory (fail fast), stores the cache in `llm_cache/responses.sqlite`, copies a replay source cache into a new run, and stops a run cleanly when a backend stays down.
- No mind calls the gateway yet. M2b plugs an LLM mind into the controller's existing `minds` map. Until then, villagers with a `model` keep using the scripted mind, and tests drive the gateway with a small test-only agent.

**Tech Stack:** Python 3.12+, uv, pydantic v2 (output schemas and validation), PyYAML, sqlite3, urllib (Ollama HTTP), `mlx-lm` (new, optional extra `mlx`, Apple Silicon only), pytest, mypy strict, ruff, mutmut.

**Spec:** `docs/superpowers/specs/2026-11-22-pericles-design.md` (§3.2, §5.6, §6, §7, §10). Requirements: `docs/requirements/llm.md` (REQ-LLM-001…009), `exp.md`, `nfr.md`. Decisions: ADR-0006 (gateway and cache), ADR-0003, ADR-0004, ADR-0016, and the new ADR-0017 written in Task 2.

**User decisions (2026-11-26):**
- M2 is split into three plans. M2a is the gateway, plus the experiment-facing M1d minors. M2b covers plan minds: triggers, prompt builder, plan schema, executor, retries with fallback, personality, neutral framing and the golden replay run. M2c covers memory, reflection, opinions and the LLM budget metric.
- The MLX backend (REQ-LLM-003) is in M2a, as an optional extra that is skipped where it is not installed.

**Requirements in scope:**

| Requirement | In this plan |
|---|---|
| REQ-LLM-001 | All. The `Backend` protocol, three implementations, and a boundary test: only the backend modules import an HTTP or MLX client, and only `pericles.llm` and `pericles.experiment` import the backend modules |
| REQ-LLM-002 | All. Model listing with a fail-fast check, `format` schema-constrained output, and slow contract tests against the local Ollama |
| REQ-LLM-003 | All. `MLXBackend` loads by name or path. JSON is validated by the gateway. The schema goes into the prompt because MLX has no constrained decoding. Slow contract test |
| REQ-LLM-004 | All. Rules keyed by call kind, villager or prompt pattern, reply sequences, recorded scripts from YAML, simulated latency, invalid output and errors |
| REQ-LLM-005 | All. `hash(model, sampling, messages, schema, seed)`, modes `off`, `record` and `replay`, and a replayed run with an identical event-log digest |
| REQ-LLM-006 | All. Villagers pinned by `model:`, a seeded ratio split for the rest, per-model sampling, and the concrete model recorded in every call record |
| REQ-LLM-007 | All. Requests are grouped by model, one model at a time per backend, each group runs on a pool of `concurrency` threads, and results come back in request order |
| REQ-LLM-008 | All. Every call (including cache hits and backend errors) logs model, prompt hash, tokens, latency, validity, attempt, cached flag and zlib-compressed raw output |
| REQ-LLM-009 | AC1 only. Wait mode backs off exponentially, and after `max_backend_failures` the run stops cleanly and can be resumed. AC2 (live-mode fallback, flagged) needs the M2b mind. The gateway already returns a `backend_error` result in live mode for it, and the requirement stays Accepted |

**M1d carry-over in this plan** (from the M1d reviews):
- Map size has no upper bound.
- A corrupt `events.sqlite`, or a malformed agents blob, raises a raw error.
- `RunDirectory.create` on a regular file raises `NotADirectoryError`.
- Resume is not portable: the resolved map omits MapParams defaults, and `packs` stores the installed pack path.
- `_merged` is shallow.
- `RunDirectory.skipped` collects duplicates.
- `skills` accepts bool and str.
- Duplicate band or vein terrain is accepted.

---

## Global Constraints

- **Branch.** Work on `m2a-llm-gateway`, which the plan commit creates from `main`. Land it through a PR to `main`.
- **Layering.**
  - `pericles.core` imports nothing from `pericles.agents`, `pericles.llm`, `pericles.experiment`, `pericles.server` or `pericles.analysis`. Existing tests enforce this.
  - `pericles.llm` imports only the standard library, `pydantic`, `yaml`, `pericles.core.canonical` and itself. It knows no villages, ticks beyond the integer on a request, or content.
  - Only `pericles/llm/ollama.py` imports `urllib`. Only `pericles/llm/mlx_runtime.py` imports `mlx` or `mlx_lm`. No module imports `requests`, `httpx`, `ollama` or `openai`. Task 2 adds the test.
  - Only `pericles.llm` and `pericles.experiment` import `pericles.llm.ollama`, `pericles.llm.mlx`, `pericles.llm.mlx_runtime` or `pericles.llm.fake`. M2b's agents will import only `pericles.llm.gateway` and `pericles.llm.types`.
- **Determinism.**
  - The gateway returns results in request order, whatever order the backend finished them in.
  - Cache lookups, cache writes and call-log writes happen on the calling thread in request order. Only the backend calls run on worker threads.
  - Model assignment uses `random.Random(f"pericles-models:{seed}")` in `pericles.experiment`, never in agents or core.
- **No magic values** (the user's rule, 2026-11-23). Every gateway parameter (modes, backoff, failure limit, default sampling, default concurrency, timeout, Ollama URL) is an `LLMConfig` field. It is listed in the new `llm:` section of `src/pericles/experiment/default_settings.yaml`, and a test checks that the file lists every field. Engine parameters stay `EngineConfig` fields, listed under `engine:`.
- **Item conservation** and the engine tick order are unchanged. Nothing in this plan touches `pericles.core` except the new `EngineConfig.max_map_tiles` field.
- **Tests.**
  - Every test for a requirement carries `@pytest.mark.req("REQ-…")` (literal ids) and names the AC in its docstring.
  - Product tests live in `tests/pericles/`. Tests that need a live Ollama or MLX model are marked `slow` (excluded by default and in CI).
  - Unit tests never open a network connection except to a stub HTTP server on `127.0.0.1` that the test starts itself.
  - Time is injected. `Gateway` and `FakeBackend` take `clock` and `sleep` callables, and tests pass fakes so no test sleeps.
- **Mutation scores.** `pericles.core` must stay ≥ 80%, and `pericles.agents` and `pericles.llm` ≥ 70%. Each task mutates its own modules and adds tests for survivors.
  - `src/pericles/llm/mlx_runtime.py` is listed under `do_not_mutate` (Task 7), because it only runs where MLX is installed, and its slow contract test covers it.
  - `# pragma: no mutate` is allowed only on a line where every possible mutant is equivalent, with the per-mutant reason given in the report.
- **Gates before every commit**, in order. Never hide a gate's exit code behind a pipe.
  1. `uv run ruff format .`
  2. `uv run pytest -q`
  3. `uv run mypy`
  4. `uv run ruff check .`
  5. `uv run ruff format --check .`
  6. `PYTHONPATH=tools uv run python -m pericles_tools.traceability check`
- **Commit messages** end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Ollama is down or a model is missing.**
   - Cases: at start, the server is not running, or a configured model is not pulled. Mid-run, the connection is refused, times out or returns HTTP 500.
   - Expected:
     - At start, `pericles run` exits 2 with a message that names the URL or the missing model and the `ollama pull` command, and leaves no run directory behind.
     - Mid-run in wait mode, the gateway backs off with `delay(n) = min(base × factor^(n-1), max)` and gives up after `max_backend_failures` failures in a row. The CLI then exits 3 and says how to resume. The event log ends at the last completed tick, and `pericles resume` continues.
   - Tests: Tasks 5, 6 and 10.
2. **Replay must not drift.**
   - Cases: a record run is replayed, either from its run directory, its `llm_cache` directory or the `responses.sqlite` file.
   - Expected:
     - The replayed event-log digest equals the recorded one, with no backend call.
     - A replay request that is not in the cache raises `CacheMiss` naming the kind, villager, tick and model. It is never silently sent to a backend.
     - Latency and token counts never enter the event log.
   - Tests: Tasks 3, 5 and 10.
3. **Malformed model output.**
   - Cases: the output is empty, not JSON, JSON wrapped in a ```` ```json ```` fence, valid JSON with a missing or extra field, or a wrong type.
   - Expected: a `Result` with `value=None` and an `error` string that names the field (`goal: Field required`). The fenced form validates. A raw output is logged even when it is invalid, and nothing raises.
   - Tests: Tasks 3 and 5.
4. **`llm:` configuration errors.**
   - Cases: an unknown key, a backend kind other than `ollama`, `mlx` or `fake`, a model naming an unknown backend, `assign` naming an unknown model or a ratio ≤ 0, `replay` without `cache_from`, a villager or `engine.adult_model` naming an undefined model, and a `cache_from` with no `responses.sqlite`.
   - Expected: an `ExperimentError` whose message starts with the dotted path (`llm.models.qwen.backend: …`, `population[3].model: …`), never a raw exception.
   - Tests: Tasks 8 and 9.
5. **Concurrency.**
   - Cases: several villagers on two models and two backends, with concurrency 1 and 3, and requests given in any order.
   - Expected: each result belongs to its own request. Groups run one model at a time per backend, and no more than `concurrency` calls are in flight per backend. Shuffling the request order changes no villager's result.
   - Tests: Task 5.

---

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `src/pericles/core/config.py`, `default_settings.yaml` | `EngineConfig.max_map_tiles` | 1 |
| `src/pericles/experiment/config.py` | Deep merge, map-size bound, strict skills, duplicate terrains, portable resolved map and packs | 1, 9 |
| `src/pericles/experiment/rundir.py` | Regular-file guard, readable-event-log guard, de-duplicated `skipped`, meta extras | 1, 10 |
| `src/pericles/experiment/runner.py` | `resume(run_dir, load=…)` skips snapshots whose agents blob will not load | 1 |
| `src/pericles/agents/controller.py` | `Controller.load` is atomic | 1 |
| `docs/adr/0017-llm-gateway.md` | Backends, gateway, cache, call log, failure policy, scheduling, `llm:` section, model assignment | 2 |
| `src/pericles/llm/types.py` | `Message`, `Sampling`, `ModelSpec`, `BackendCall`, `Completion`, `Request`, `Result` | 2 |
| `src/pericles/llm/backend.py` | `Backend` protocol, `BackendError`, `LLMSetupError` | 2 |
| `src/pericles/llm/fake.py` | `FakeBackend`, `FakeRule`, `FakeError`, YAML scripts | 2 |
| `src/pericles/llm/validate.py` | `schema_of`, `unfenced`, `validate` | 3 |
| `src/pericles/llm/cache.py` | `cache_key`, `ResponseCache`, `CacheMiss` | 3 |
| `src/pericles/llm/calls.py` | `CallRecord`, `CallLog` (`llm_calls.sqlite`) | 4 |
| `src/pericles/llm/gateway.py` | `Gateway`, `FailurePolicy`, `BackendUnavailable`, `check_models`, `prompt_hash` | 5 |
| `src/pericles/llm/ollama.py` | `OllamaBackend`, `http_json` | 6 |
| `src/pericles/llm/mlx.py`, `mlx_runtime.py` | `MLXBackend`, `MLXRuntime` protocol, the real `mlx-lm` runtime | 7 |
| `src/pericles/llm/config.py` | `LLMConfig`, `BackendSpec` | 8 |
| `src/pericles/experiment/settings.py`, `defaults.py` | `llm:` section parsing and serialising | 8 |
| `src/pericles/experiment/models.py` | `quotas`, `assign_models` | 9 |
| `src/pericles/experiment/llm.py` | `build_backends`, `replay_source`, `open_gateway` | 10 |
| `src/pericles/experiment/launch.py`, `cli.py` | Fail-fast check, gateway in the session, clean stop, exit 3 | 10 |
| `docs/requirements/*.md`, `README.md` | Statuses, traceability matrix, MLX and Ollama instructions | 11 |

---

### Task 1: M1d carry-over — experiment and run-directory robustness

**Files:**
- Modify: `src/pericles/core/config.py`, `src/pericles/experiment/default_settings.yaml`
- Modify: `src/pericles/experiment/config.py`, `src/pericles/experiment/rundir.py`, `src/pericles/experiment/runner.py`, `src/pericles/experiment/launch.py`, `src/pericles/agents/controller.py`
- Test: `tests/pericles/test_experiment_config.py`, `tests/pericles/test_rundir.py`, `tests/pericles/test_runner.py`, `tests/pericles/test_controller.py`

**Interfaces:**
- Produces:
  - `EngineConfig.max_map_tiles: int = 1_048_576`.
  - `pericles.experiment.config.merged(section: str, data: object) -> dict[str, Any]`, a public deep merge that replaces `calendar` whole.
  - `RunDirectory.skip(path: Path) -> None`, which de-duplicates.
  - `resume(run_dir, load: Callable[[dict[str, Any]], None] | None = None) -> tuple[WorldState, dict[str, Any]]`.
  - The resolved `packs` stores `"base"` for the base pack, and the resolved `map` holds every `MapParams` field.

- [ ] **Step 1: Write the failing tests**

Append to `tests/pericles/test_experiment_config.py` (it already defines `MINIMAL`, `changed` and imports `experiment_from_mapping`, `ExperimentError`, `pytest`, `Path`):

```python
@pytest.mark.req("REQ-EXP-001")
def test_a_map_larger_than_max_map_tiles_is_a_field_error(tmp_path: Path) -> None:
    """AC2: a typo like width 1000000000 is refused before the map is generated."""
    data = changed("map.width", 1_000_000_000)
    with pytest.raises(ExperimentError, match=r"^map: .* more than engine.max_map_tiles"):
        experiment_from_mapping(data, tmp_path)


@pytest.mark.req("REQ-EXP-001")
def test_max_map_tiles_is_a_setting(tmp_path: Path) -> None:
    """AC2: the bound itself comes from the engine section."""
    data = {**MINIMAL, "engine": {"max_map_tiles": 100}}
    with pytest.raises(ExperimentError, match="24 × 24 = 576 tiles"):
        experiment_from_mapping(data, tmp_path)


@pytest.mark.req("REQ-EXP-001")
@pytest.mark.parametrize("value", [True, "5"])
def test_skills_must_be_numbers(tmp_path: Path, value: object) -> None:
    """AC2: a bool or a string is not a skill level."""
    data = changed("population.0.skills.foraging", value)
    with pytest.raises(ExperimentError, match=r"^population\[0\]\.skills\.foraging"):
        experiment_from_mapping(data, tmp_path)


@pytest.mark.req("REQ-EXP-001")
@pytest.mark.parametrize("key", ["bands", "veins"])
def test_duplicate_terrains_are_field_errors(tmp_path: Path, key: str) -> None:
    """AC2: a terrain listed twice in bands or veins names the second entry."""
    entries = {
        "bands": [{"terrain": "grass", "share": 0.5}, {"terrain": "grass", "share": 0.2}],
        "veins": [
            {"terrain": "iron_vein", "share": 0.01, "host": "grass"},
            {"terrain": "iron_vein", "share": 0.01, "host": "grass"},
        ],
    }
    data = changed(f"map.{key}", entries[key])
    with pytest.raises(ExperimentError, match=rf"^map\.{key}\[1\]\.terrain: duplicate"):
        experiment_from_mapping(data, tmp_path)


@pytest.mark.req("REQ-EXP-001")
def test_nested_settings_merge_key_by_key(tmp_path: Path) -> None:
    """AC1: overriding one relief's act_at keeps the defaults for the others."""
    data = {**MINIMAL, "agents": {"act_at": {"eat": 40.0}}}
    experiment = experiment_from_mapping(data, tmp_path)
    assert experiment.agents.act_at["eat"] == 40.0
    assert experiment.agents.act_at["sleep"] == 75.0


@pytest.mark.req("REQ-EXP-001")
def test_the_resolved_config_is_portable(tmp_path: Path) -> None:
    """AC1: the base pack is stored by name and the map holds every MapParams field."""
    resolved = experiment_from_mapping(MINIMAL, tmp_path).resolved
    assert resolved["packs"] == ["base"]
    assert resolved["map"]["octaves"] == 3
    assert resolved["map"]["veins"] == []
    rebuilt = experiment_from_mapping(resolved, tmp_path / "elsewhere")
    assert rebuilt.map == experiment_from_mapping(MINIMAL, tmp_path).map
```

Append to `tests/pericles/test_rundir.py` (it imports `RunDirectory`, `RunDirectoryError`, `Path`, `pytest`):

```python
def test_create_on_a_regular_file_is_a_run_directory_error(tmp_path: Path) -> None:
    """AC1: a file in the way is reported, not a raw NotADirectoryError."""
    target = tmp_path / "run"
    target.write_text("not a directory", encoding="utf-8")
    with pytest.raises(RunDirectoryError, match="not a directory"):
        RunDirectory.create(target, {}, seed=1)


def test_a_corrupt_event_log_is_a_run_directory_error(tmp_path: Path) -> None:
    """AC3: a damaged events.sqlite is named, not a raw sqlite3.DatabaseError."""
    run = RunDirectory.create(tmp_path / "run", {}, seed=1)
    run.close()
    (tmp_path / "run" / "events.sqlite").write_bytes(b"garbage" * 100)
    opened = RunDirectory.open(tmp_path / "run")
    with pytest.raises(RunDirectoryError, match="events.sqlite is unreadable"):
        _ = opened.event_log


def test_skipped_lists_each_file_once(tmp_path: Path) -> None:
    """AC3: asking for snapshots twice does not repeat the skipped files."""
    run = RunDirectory.create(tmp_path / "run", {}, seed=1)
    (tmp_path / "run" / "snapshots" / "tick-0000000005.json").write_text("{", encoding="utf-8")
    list(run.snapshots())
    list(run.snapshots())
    assert run.skipped == [run.snapshot_path(5)]
    run.close()
```

Append to `tests/pericles/test_runner.py` (it has `initial`, `source_for`, `SourceAgents`, `run`, `resume`, `RunDirectory`, `Engine`, `default_config`):

```python
def test_resume_skips_a_snapshot_whose_agents_blob_will_not_load(
    tmp_path: Path, registry: Registry, small_map: TileMap
) -> None:
    """AC3: a malformed agents blob falls back to the previous snapshot."""
    state, walkable = initial(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=4)
    engine = Engine(registry, default_config())
    run(run_dir, engine, state, SourceAgents(source_for(walkable)), 20, 10)
    bad = run_dir.snapshot_path(20)
    payload = json.loads(bad.read_text(encoding="utf-8"))
    payload["agents"] = {"memory": {"v0": "not a memory"}}
    bad.write_text(json.dumps(payload), encoding="utf-8")

    def load(agents: dict[str, Any]) -> None:
        for value in agents.get("memory", {}).values():
            if not isinstance(value, dict):
                raise TypeError("memory entries are mappings")

    restored, _ = resume(run_dir, load)
    assert restored.tick == 10
    assert run_dir.skipped == [bad]
```

Add `import json` at the top of `tests/pericles/test_runner.py` if it is not there.

Append to `tests/pericles/test_controller.py`. Look at the file's existing imports and fixtures for how it builds a controller; it imports `scripted_controller` and `default_agent_config`. If it builds the engine context differently, use the same expression the other tests in that file use.

```python
@pytest.mark.req("REQ-AGT-008")
def test_load_is_atomic(registry: Registry) -> None:
    """AC2: a blob that fails half-way leaves the controller as it was."""
    controller = scripted_controller(Engine(registry, default_config()).context, default_agent_config())
    controller.fallbacks = 7
    with pytest.raises((TypeError, ValueError, KeyError, AttributeError)):
        controller.load({"fallbacks": 3, "memory": {"v0": "not a memory"}})
    assert controller.fallbacks == 7
    assert controller.memory == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_experiment_config.py tests/pericles/test_rundir.py tests/pericles/test_runner.py tests/pericles/test_controller.py -q`
Expected: the new tests FAIL (no `max_map_tiles`, skills accept `True`, duplicates accepted, `act_at` override rejected as missing keys, packs hold a path, raw `NotADirectoryError`, raw `DatabaseError`, duplicate skipped entries, `resume` takes one argument, `fallbacks` becomes 3).

- [ ] **Step 3: Implement**

`src/pericles/core/config.py`: add the field after `childhood_memory_limit`, and a check in the same validation list that holds the other positive-int checks:

```python
    # Experiment guard (ADR-0017 §9): a typo in map size must not hang map generation
    max_map_tiles: int = 1_048_576
```

```python
        (c.max_map_tiles >= 1, "max_map_tiles must be at least 1"),
```

`src/pericles/experiment/default_settings.yaml`: add `  max_map_tiles: 1048576` to the `engine:` section, after `childhood_memory_limit`.

`src/pericles/experiment/config.py`:

1. Make skills strict. Add `StrictFloat` to the pydantic import and change the field:

```python
    skills: dict[StrictStr, Annotated[StrictFloat | StrictInt, Field(ge=0)]] = Field(
        default_factory=dict
    )
```

and in `build_world` use `skills={k: float(v) for k, v in spec.skills.items()},`.

2. Replace `_merged` with a public deep merge. Update the two call sites, and Task 9's third call site, to `merged(...)`:

```python
REPLACED_WHOLE = ("calendar",)


def merged(section: str, data: object) -> dict[str, Any]:
    """The packaged defaults for `section` overridden key by key, one level deep.

    A nested mapping (such as `act_at`) merges with the default mapping; `calendar` replaces
    the default calendar whole (ADR-0016 §5)."""
    defaults = dict(default_settings_mapping()[section])
    overrides = {} if data is None else dict(as_mapping(data, section))
    out = dict(defaults)
    for key, value in overrides.items():
        default = out.get(key)
        if key not in REPLACED_WHOLE and isinstance(value, Mapping) and isinstance(default, Mapping):
            out[key] = {**default, **value}
        else:
            out[key] = value
    return out
```

3. Bound the map size and reject duplicate terrains. `_map` gains an `engine: EngineConfig` parameter. Call it as `_map(raw["map"], registry, engine)` *after* `engine` is built, which it already is. Insert the checks before `validate(params, registry)`:

```python
    tiles = params.width * params.height
    if tiles > engine.max_map_tiles:
        raise ExperimentError(
            f"map: {params.width} × {params.height} = {tiles} tiles is more than "
            f"engine.max_map_tiles {engine.max_map_tiles}"
        )
    for key, entries in (("bands", params.bands), ("veins", params.veins)):
        seen: set[str] = set()
        for i, entry in enumerate(entries):
            if entry.terrain in seen:
                raise ExperimentError(
                    f"map.{key}[{i}].terrain: duplicate terrain {entry.terrain!r}"
                )
            seen.add(entry.terrain)
```

4. Make the resolved config portable. Add `import dataclasses, json` at the top, and in `experiment_from_mapping` replace the `packs` and `map` entries of `resolved`:

```python
        "packs": [BASE if p == base_pack_path() else str(p) for p in packs],
        "map": json.loads(json.dumps(dataclasses.asdict(params))),
```

`_map` accepts `bands` and `veins` given as lists of mappings, which `asdict` produces after the JSON round trip, so the resolved map loads again.

`src/pericles/experiment/rundir.py`:

```python
import sqlite3
```

In `create`, before the non-empty check:

```python
        if path.exists() and not path.is_dir():
            raise RunDirectoryError(f"{path}: not a directory")
```

Replace the `event_log` property:

```python
    @property
    def event_log(self) -> EventLog:
        if self._event_log is None:
            try:
                log = EventLog(self.path / "events.sqlite")
                log.last_tick()
            except sqlite3.DatabaseError as error:
                raise RunDirectoryError(
                    f"{self.path}: events.sqlite is unreadable ({error})"
                ) from None
            self._event_log = log
        return self._event_log
```

Add `skip` and use it everywhere `skipped` is appended to (both places in `snapshots`):

```python
    def skip(self, path: Path) -> None:
        """Record an unusable snapshot file once."""
        if path not in self.skipped:
            self.skipped.append(path)
```

Replace `self.skipped.extend(strays)` with `for stray in strays: self.skip(stray)`, and `self.skipped.append(path)` with `self.skip(path)`.

`src/pericles/experiment/runner.py`: replace `resume`:

```python
def resume(
    run_dir: RunDirectory, load: Callable[[dict[str, Any]], None] | None = None
) -> tuple[WorldState, dict[str, Any]]:
    """Restore the newest usable snapshot the event log covers; truncate the log to it.

    `load` receives the snapshot's agents blob. A snapshot whose world or agents blob cannot
    be restored is skipped, and the next older one is tried."""
    last = run_dir.event_log.last_tick()
    logged = 0 if last is None else last + 1
    for snapshot in run_dir.snapshots():
        path = run_dir.snapshot_path(snapshot.tick)
        if snapshot.tick > logged:
            run_dir.skip(path)
            continue
        try:
            state = WorldState.from_dict(snapshot.world)
            if load is not None:
                load(snapshot.agents)
        except (KeyError, TypeError, ValueError, AttributeError):
            run_dir.skip(path)
            continue
        run_dir.event_log.truncate_after(state.tick - 1)
        return state, snapshot.agents
    raise RunDirectoryError(f"{run_dir.path}: no usable snapshot to resume from")
```

`src/pericles/agents/controller.py`: make `load` atomic:

```python
    def load(self, data: Mapping[str, Any]) -> None:
        """Restore from `to_dict` output. On error the controller is left unchanged."""
        fallbacks = int(data.get("fallbacks", 0))
        memory = {str(k): Memory.from_dict(v) for k, v in data.get("memory", {}).items()}
        self.fallbacks, self.memory = fallbacks, memory
```

`src/pericles/experiment/launch.py`, in `reopen`: build the controller *before* resuming, and pass its `load`:

```python
        controller = scripted_controller(engine.context, experiment.agents)
        state, _ = resume(run_dir, controller.load)
```

The controller load that followed the old `resume` call goes away.

If an existing test asserts the old `packs` value (an absolute base-pack path) in a resolved config, update it to `["base"]`. If an existing test asserts that `resolved["map"]` equals the raw map, update it to compare `experiment_from_mapping(resolved, …).map` instead.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS, all tests.

- [ ] **Step 5: Mutation-check and commit**

Run: `PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run --changed-since main`
Expected: core ≥ 80%, agents ≥ 70%, exit 0. Add tests for survivors in the changed lines.

```bash
git add -A
git commit -m "fix: bound map size, strict skills, duplicate terrains, deep settings merge, portable resolved config, safer run directories

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: ADR-0017, gateway types, the backend contract and the fake backend

**Files:**
- Create: `docs/adr/0017-llm-gateway.md`; modify `docs/adr/README.md`
- Create: `src/pericles/llm/types.py`, `src/pericles/llm/backend.py`, `src/pericles/llm/fake.py`
- Test: `tests/pericles/test_llm_fake.py`, `tests/pericles/test_core_boundaries.py`

**Interfaces:**
- Produces (exact; later tasks use these names):

```python
# pericles.llm.types
Role = Literal["system", "user", "assistant"]
@dataclass(frozen=True) class Message:  role: Role; content: str; def to_dict(self) -> dict[str, str]
@dataclass(frozen=True) class Sampling: temperature: float; top_p: float; max_tokens: int; def to_dict(self) -> dict[str, float | int]
@dataclass(frozen=True) class ModelSpec: backend: str; name: str; sampling: Sampling
@dataclass(frozen=True) class BackendCall: model: str; messages: tuple[Message, ...]; sampling: Sampling; seed: int; schema: Mapping[str, Any] | None = None; kind: str = ""; villager: str = ""
@dataclass(frozen=True) class Completion: text: str; tokens_in: int; tokens_out: int
@dataclass(frozen=True) class Request: kind: str; villager: str; tick: int; model: str; messages: tuple[Message, ...]; seed: int; output: type[BaseModel] | None = None; attempt: int = 0; template: str | None = None
@dataclass(frozen=True) class Result: request: Request; text: str; value: BaseModel | None; error: str | None; backend_error: str | None; tokens_in: int; tokens_out: int; latency_s: float; cached: bool; valid: bool (property)
# pericles.llm.backend
class BackendError(Exception); class LLMSetupError(Exception)
class Backend(Protocol): kind (property, str); concurrency (property, int); describe() -> str; check(models: Sequence[str]) -> None; complete(call: BackendCall) -> Completion
# pericles.llm.fake
@dataclass(frozen=True) class FakeError: message: str
Reply = str | FakeError
@dataclass(frozen=True) class FakeRule: replies: tuple[Reply, ...]; kind: str | None = None; villager: str | None = None; pattern: str | None = None; delay_s: float = 0.0; def matches(self, call: BackendCall) -> bool
class FakeBackend: __init__(rules=(), *, models: Sequence[str] | None = None, concurrency: int = 1, sleep=time.sleep); kind = "fake"; calls: list[BackendCall]; from_file(path, *, concurrency=1) (classmethod)
```

- [ ] **Step 1: Write ADR-0017**

Create `docs/adr/0017-llm-gateway.md`:

```markdown
# ADR-0017: LLM gateway, backends, cache and call log

- **Status:** Accepted
- **Date:** 2026-11-26
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)
- **Refines:** ADR-0006

## Context

M2a builds the gateway that ADR-0006 describes (REQ-LLM-001…009). Minds come in M2b, memory and reflection in M2c. Runs must replay bit-exactly from a response cache, model families must be comparable, and an Ollama server that stops mid-run must not corrupt a run. On 2026-11-26 the user split M2 into three plans and put the MLX backend in M2a.

## Decision

1. **Package.**
   - `pericles.llm` knows no villages. It imports only the standard library, pydantic, PyYAML and `pericles.core.canonical`.
   - Only `ollama.py` imports `urllib`, and only `mlx_runtime.py` imports `mlx` or `mlx_lm`.
   - Only `pericles.llm` and `pericles.experiment` construct backends. Agents will call only `Gateway` and the types.
2. **Requests name logical models.**
   - A `Request` names a key of `llm.models`, with its kind, villager, tick, messages, seed, an optional pydantic output model, the attempt number and the template version.
   - The gateway resolves the key to a `ModelSpec` (backend key, backend model name, `Sampling`) and builds a `BackendCall`.
3. **Backends.** `kind`, `concurrency`, `describe()`, `check(models)` and `complete(call)`.
   - `check` raises `LLMSetupError` when the backend is unreachable or a model is missing. `complete` raises `BackendError` for failures that may pass.
   - **Ollama** uses `/api/tags` and `/api/chat` with `stream: false`, the output schema as `format`, and `temperature`, `top_p`, `num_predict` and `seed` as options. A model name without a tag means `:latest`.
   - **MLX** runs in-process, one call at a time. It has no constrained decoding, so it appends one system message giving the JSON schema. The gateway validates its output like any other.
   - **Fake** follows rules matched by kind, villager or a regex on the last message, first match wins. Each rule serves its replies in order and repeats the last one. A reply is text or `{error: message}`, and a rule may add a delay. Rules can be loaded from YAML.
4. **Validation.**
   - The output schema is the pydantic model's JSON schema. The text is validated with `model_validate_json`, after removing one surrounding Markdown code fence if present.
   - An invalid output is a `Result` with `value=None` and `error="<field path>: <message>"`. It never raises. Retries with the error fed back are the M2b mind's job (REQ-AGT-005).
5. **Cache.**
   - The key is the SHA-256 of canonical JSON `{model: "<backend kind>:<backend model>", sampling, messages, schema, seed}`.
   - It is stored in `llm_cache/responses.sqlite` (key, text, tokens in, tokens out).
   - `off` bypasses the cache. `record` calls the backend and stores (replacing) every response. `replay` answers from the cache only, and a miss raises `CacheMiss`.
   - A replay run copies its source cache (`llm.cache_from`: a run directory, its `llm_cache` directory, or the file) into its own `llm_cache` at start, so every run directory is self-contained.
6. **Call log.**
   - One row per call goes to `llm_calls.sqlite`, cache hits and backend errors included. Each row holds tick, villager, kind, logical model, backend kind, backend model, prompt hash (of the messages), tokens in and out, latency, validity, error, attempt, cached flag, template version and the zlib-compressed raw output.
   - It is kept out of `events.sqlite`, because latency and tokens differ between a run and its replay. That would break REQ-LLM-005 AC3.
   - On resume it is truncated like the event log.
7. **Scheduling.**
   - `complete_all(requests)` looks up the cache on the calling thread. It groups the misses by (backend, model) and runs the groups in sorted order, one model at a time per backend, so a backend never swaps models within a batch. Each group runs on a pool of `concurrency` threads.
   - Cache writes and call-log rows are made on the calling thread, in request order, so results never depend on completion order.
8. **Failure policy.**
   - In **wait** mode a failing call is retried after `min(backoff_base_s × backoff_factor^(n-1), backoff_max_s)` seconds. After `max_backend_failures` failures in a row, every row is logged and `BackendUnavailable` is raised.
   - The runner lets it propagate before the engine steps, so the event log ends at the last whole tick. The CLI exits 3 and the run continues with `pericles resume`.
   - In **live** mode a failing call is tried once, and its `Result` carries `backend_error`. M2b's mind falls back and flags it.
9. **`llm:` experiment section.**
   - The packaged defaults in `default_settings.yaml` cover every `LLMConfig` field: mode, cache, `cache_from`, backoff, failure limit, default sampling, default concurrency, timeout and Ollama URL.
   - An experiment adds `backends` (`kind: ollama | mlx | fake`), `models` (`backend`, `name`, optional sampling) and `assign` (ratios).
   - Fake `replies` paths and `cache_from` resolve against the experiment file. The resolved config stores every value.
   - `engine.max_map_tiles` bounds `map.width × map.height`.
10. **Model assignment.**
    - A villager's `model:` pins it, and must name a key of `llm.models`, as must `engine.adult_model`.
    - Adults without a pin are split by `assign`. Exact counts come from the largest remainder (ties by model key). The unpinned adult ids are sorted, then shuffled with `random.Random(f"pericles-models:{seed}")`, then assigned in model-key order.
    - The resolved population records the result, so reloading it assigns nothing new.
11. **Startup.**
    - `pericles run` builds the backends and checks every configured model before it creates the run directory. A missing model or unreachable server exits 2 with the model, the URL and the `ollama pull` command.
    - `meta.json` records `llm_mode`, `cache_mode` and `reproducible`, which is false in live mode.

## Consequences

- Tests and CI run the whole gateway with `FakeBackend`. Ollama and MLX contract tests are `slow` and run on the user's Mac.
- A recorded run can be replayed without any model installed.
- A prompt or sampling change invalidates the cache, as intended (ADR-0006).
- MLX output is unconstrained, so weak MLX models produce more invalid outputs than the same model under Ollama's `format`. The call log makes that measurable.
- Live-mode fallback flagging (REQ-LLM-009 AC2) and retries with the validation error (REQ-AGT-005) belong to the M2b mind.
```

Add to `docs/adr/README.md` after the 0016 row:

```markdown
| [0017](0017-llm-gateway.md) | LLM gateway, backends, cache and call log | Accepted |
```

Run: `PYTHONPATH=tools uv run python -m pericles_tools.adr check`
Expected: exit 0.

- [ ] **Step 2: Write the failing tests**

Create `tests/pericles/test_llm_fake.py`:

```python
from pathlib import Path

import pytest

from pericles.llm.backend import Backend, BackendError, LLMSetupError
from pericles.llm.fake import FakeBackend, FakeError, FakeRule
from pericles.llm.types import BackendCall, Message, Request, Result, Sampling

SAMPLING = Sampling(temperature=0.5, top_p=0.9, max_tokens=64)


def call(kind: str = "plan", villager: str = "ada", text: str = "hello there") -> BackendCall:
    return BackendCall("m", (Message("system", "sys"), Message("user", text)), SAMPLING, 1, None, kind, villager)


@pytest.mark.req("REQ-LLM-001")
def test_the_fake_backend_implements_the_interface() -> None:
    """AC2: FakeBackend satisfies the Backend protocol."""
    backend: Backend = FakeBackend()
    assert backend.kind == "fake"
    assert backend.concurrency == 1
    assert backend.describe() == "fake backend"


@pytest.mark.req("REQ-LLM-004")
def test_rules_match_by_kind_villager_and_pattern_first_match_wins() -> None:
    """AC1: scripted responses keyed by call kind, villager or prompt pattern."""
    backend = FakeBackend(
        [
            FakeRule(("by-pattern",), pattern=r"storm"),
            FakeRule(("by-villager",), villager="bram"),
            FakeRule(("by-kind",), kind="vote"),
            FakeRule(("anything",)),
        ]
    )
    assert backend.complete(call(text="a storm comes")).text == "by-pattern"
    assert backend.complete(call(villager="bram")).text == "by-villager"
    assert backend.complete(call(kind="vote")).text == "by-kind"
    assert backend.complete(call()).text == "anything"


@pytest.mark.req("REQ-LLM-004")
def test_a_pattern_only_looks_at_the_last_message() -> None:
    """AC1: the system message does not count for a pattern."""
    backend = FakeBackend([FakeRule(("hit",), pattern="sys")])
    with pytest.raises(BackendError, match="no scripted reply for kind 'plan', villager 'ada'"):
        backend.complete(call())


@pytest.mark.req("REQ-LLM-004")
def test_replies_are_served_in_order_and_the_last_repeats() -> None:
    """AC1/AC2: a rule replays a recorded sequence; invalid output is just a reply."""
    backend = FakeBackend([FakeRule(("not json", '{"ok": true}'))])
    assert [backend.complete(call()).text for _ in range(3)] == [
        "not json",
        '{"ok": true}',
        '{"ok": true}',
    ]


@pytest.mark.req("REQ-LLM-004")
def test_errors_and_latency_are_simulated() -> None:
    """AC2: a FakeError raises BackendError; delay_s goes through the injected sleep."""
    slept: list[float] = []
    backend = FakeBackend(
        [FakeRule((FakeError("down"), "up"), delay_s=0.25)], sleep=slept.append
    )
    with pytest.raises(BackendError, match="fake backend: down"):
        backend.complete(call())
    assert backend.complete(call()).text == "up"
    assert slept == [0.25, 0.25]


@pytest.mark.req("REQ-LLM-004")
def test_tokens_are_counted_in_words_and_calls_are_recorded() -> None:
    """AC1: token counts are word counts, so tests can assert on metrics."""
    backend = FakeBackend([FakeRule(("one two three",))])
    completion = backend.complete(call(text="four five"))
    assert (completion.tokens_in, completion.tokens_out) == (3, 3)
    assert [c.villager for c in backend.calls] == ["ada"]


@pytest.mark.req("REQ-LLM-004")
def test_check_reports_models_the_fake_does_not_serve() -> None:
    """AC2: a fake can stand in for a server that lacks a model."""
    FakeBackend().check(["anything"])
    with pytest.raises(LLMSetupError, match="not available: b, c"):
        FakeBackend(models=["a"]).check(["a", "b", "c"])


@pytest.mark.req("REQ-LLM-004")
@pytest.mark.parametrize(
    ("rule", "message"),
    [
        ({"replies": ()}, "at least one reply"),
        ({"replies": ("x",), "delay_s": -1.0}, "non-negative"),
    ],
)
def test_bad_rules_are_rejected(rule: dict[str, object], message: str) -> None:
    """AC1: a rule needs a reply and a non-negative delay."""
    with pytest.raises(ValueError, match=message):
        FakeRule(**rule)  # type: ignore[arg-type]


@pytest.mark.req("REQ-LLM-004")
def test_rules_load_from_yaml(tmp_path: Path) -> None:
    """AC1: recorded responses replay from a YAML script."""
    script = tmp_path / "replies.yaml"
    script.write_text(
        "- {villager: bram, replies: ['{\"a\": 1}']}\n"
        "- {kind: plan, delay_s: 0.5, replies: [{error: busy}, 'ok']}\n",
        encoding="utf-8",
    )
    backend = FakeBackend.from_file(script, concurrency=2)
    assert backend.concurrency == 2
    assert backend.complete(call(villager="bram")).text == '{"a": 1}'
    assert backend.rules[1] == FakeRule((FakeError("busy"), "ok"), kind="plan", delay_s=0.5)


@pytest.mark.req("REQ-LLM-004")
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("{a: 1}", "expected a list of rules"),
        ("- 3\n", r"\[0\]: expected a mapping"),
        ("- {replies: [x], colour: red}\n", r"\[0\]\.colour: unknown key"),
        ("- {replies: []}\n", r"\[0\]\.replies: expected a non-empty list"),
        ("- {replies: [3]}\n", r"\[0\]\.replies\[0\]: a reply is text or"),
        ("- {replies: [x], kind: 3}\n", r"\[0\]\.kind: expected text"),
        ("- {replies: [x], delay_s: fast}\n", r"\[0\]\.delay_s: expected a number"),
        ("- {replies: [x], pattern: '('}\n", r"\[0\]: "),
        ("- [unclosed\n", "replies.yaml"),
    ],
)
def test_bad_scripts_name_the_entry(tmp_path: Path, text: str, message: str) -> None:
    """AC1: script errors are LLMSetupErrors that name the file and entry."""
    script = tmp_path / "replies.yaml"
    script.write_text(text, encoding="utf-8")
    with pytest.raises(LLMSetupError, match=message):
        FakeBackend.from_file(script)


@pytest.mark.req("REQ-LLM-001")
def test_result_validity_needs_no_validation_or_backend_error() -> None:
    """AC1: a Result is valid only without a validation error and a backend error."""
    request = Request("plan", "ada", 0, "m", (Message("user", "x"),), 1)

    def result(error: str | None, backend_error: str | None) -> Result:
        return Result(request, "", None, error, backend_error, 0, 0, 0.0, False)

    assert result(None, None).valid
    assert not result("goal: Field required", None).valid
    assert not result(None, "down").valid
    assert Message("user", "x").to_dict() == {"role": "user", "content": "x"}
    assert SAMPLING.to_dict() == {"temperature": 0.5, "top_p": 0.9, "max_tokens": 64}
```

Append to `tests/pericles/test_core_boundaries.py` (it defines `imported_modules`; add `import pericles` at the top if it is not imported):

```python
SRC = Path(pericles.__file__).parent
CLIENTS = ("urllib", "http.client", "requests", "httpx", "ollama", "openai", "mlx", "mlx_lm")
CLIENT_OWNERS = {"llm/ollama.py": ("urllib",), "llm/mlx_runtime.py": ("mlx", "mlx_lm")}
BACKEND_MODULES = (
    "pericles.llm.ollama",
    "pericles.llm.mlx",
    "pericles.llm.mlx_runtime",
    "pericles.llm.fake",
)
LLM_MAY_IMPORT = ("pericles.llm", "pericles.core.canonical")


def _sources() -> list[tuple[str, set[str]]]:
    found = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        package = ".".join(("pericles", *path.relative_to(SRC).parts[:-1]))
        found.append((relative, imported_modules(path, package)))
    return found


def _within(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == p or name.startswith(p + ".") for p in prefixes)


@pytest.mark.req("REQ-LLM-001")
def test_only_the_backend_modules_import_a_model_client() -> None:
    """AC1: no other module imports an HTTP or MLX client."""
    offenders = [
        f"{relative}: {name}"
        for relative, names in _sources()
        for name in names
        if _within(name, CLIENTS) and not _within(name, CLIENT_OWNERS.get(relative, ()))
    ]
    assert offenders == []


@pytest.mark.req("REQ-LLM-001")
def test_only_llm_and_experiment_construct_backends() -> None:
    """AC1: agents and the rest reach models only through the gateway."""
    offenders = [
        f"{relative}: {name}"
        for relative, names in _sources()
        if not relative.startswith(("llm/", "experiment/"))
        for name in names
        if _within(name, BACKEND_MODULES)
    ]
    assert offenders == []


@pytest.mark.req("REQ-LLM-001")
def test_llm_imports_no_other_pericles_package() -> None:
    """AC1: the gateway knows no villages."""
    offenders = [
        f"{relative}: {name}"
        for relative, names in _sources()
        if relative.startswith("llm/")
        for name in names
        if name.startswith("pericles") and name != "pericles" and not _within(name, LLM_MAY_IMPORT)
    ]
    assert offenders == []
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_llm_fake.py tests/pericles/test_core_boundaries.py -q`
Expected: `test_llm_fake.py` FAILS on import (`ModuleNotFoundError: pericles.llm.fake`). The boundary tests pass already (nothing violates them yet). That is fine, because they guard later tasks.

- [ ] **Step 4: Implement**

Create `src/pericles/llm/types.py`:

```python
"""Gateway value types (ADR-0017 §2)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass(frozen=True)
class Sampling:
    temperature: float
    top_p: float
    max_tokens: int

    def to_dict(self) -> dict[str, float | int]:
        return {"temperature": self.temperature, "top_p": self.top_p, "max_tokens": self.max_tokens}


@dataclass(frozen=True)
class ModelSpec:
    """A logical model: which backend serves it, under which name, with which sampling."""

    backend: str
    name: str
    sampling: Sampling


@dataclass(frozen=True)
class BackendCall:
    model: str
    messages: tuple[Message, ...]
    sampling: Sampling
    seed: int
    schema: Mapping[str, Any] | None = None
    kind: str = ""
    villager: str = ""


@dataclass(frozen=True)
class Completion:
    text: str
    tokens_in: int
    tokens_out: int


@dataclass(frozen=True)
class Request:
    """What a mind asks for; `model` is a key of `llm.models`."""

    kind: str
    villager: str
    tick: int
    model: str
    messages: tuple[Message, ...]
    seed: int
    output: type[BaseModel] | None = None
    attempt: int = 0
    template: str | None = None


@dataclass(frozen=True)
class Result:
    request: Request
    text: str
    value: BaseModel | None
    error: str | None
    backend_error: str | None
    tokens_in: int
    tokens_out: int
    latency_s: float
    cached: bool

    @property
    def valid(self) -> bool:
        return self.error is None and self.backend_error is None
```

Create `src/pericles/llm/backend.py`:

```python
"""The backend contract every model server implements (REQ-LLM-001; ADR-0017 §3)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pericles.llm.types import BackendCall, Completion


class BackendError(Exception):
    """A call failed for a reason that may pass: unreachable, timed out, server error."""


class LLMSetupError(Exception):
    """The LLM setup cannot work: a backend is unreachable at start or a model is missing."""


class Backend(Protocol):
    @property
    def kind(self) -> str: ...

    @property
    def concurrency(self) -> int: ...

    def describe(self) -> str: ...

    def check(self, models: Sequence[str]) -> None: ...

    def complete(self, call: BackendCall) -> Completion: ...
```

Create `src/pericles/llm/fake.py`:

```python
"""A scripted backend for tests and CI (REQ-LLM-004; ADR-0017 §3)."""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pericles.llm.backend import BackendError, LLMSetupError
from pericles.llm.types import BackendCall, Completion


@dataclass(frozen=True)
class FakeError:
    message: str


Reply = str | FakeError
RULE_KEYS = ("replies", "kind", "villager", "pattern", "delay_s")


@dataclass(frozen=True)
class FakeRule:
    replies: tuple[Reply, ...]
    kind: str | None = None
    villager: str | None = None
    pattern: str | None = None
    delay_s: float = 0.0

    def __post_init__(self) -> None:
        if not self.replies:
            raise ValueError("a fake rule needs at least one reply")
        if self.delay_s < 0:
            raise ValueError("delay_s must be non-negative")
        if self.pattern is not None:
            re.compile(self.pattern)

    def matches(self, call: BackendCall) -> bool:
        if self.kind is not None and call.kind != self.kind:
            return False
        if self.villager is not None and call.villager != self.villager:
            return False
        if self.pattern is None:
            return True
        last = call.messages[-1].content if call.messages else ""
        return re.search(self.pattern, last) is not None


class FakeBackend:
    kind = "fake"

    def __init__(
        self,
        rules: Sequence[FakeRule] = (),
        *,
        models: Sequence[str] | None = None,
        concurrency: int = 1,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.rules = tuple(rules)
        self.models = None if models is None else tuple(models)
        self.concurrency = concurrency
        self.calls: list[BackendCall] = []
        self._sleep = sleep
        self._served = [0] * len(self.rules)
        self._lock = threading.Lock()

    def describe(self) -> str:
        return "fake backend"

    def check(self, models: Sequence[str]) -> None:
        if self.models is None:
            return
        missing = [m for m in models if m not in self.models]
        if missing:
            raise LLMSetupError(f"fake backend: model(s) not available: {', '.join(missing)}")

    def complete(self, call: BackendCall) -> Completion:
        with self._lock:
            self.calls.append(call)
            index = next((i for i, r in enumerate(self.rules) if r.matches(call)), None)
            if index is None:
                raise BackendError(
                    f"fake backend: no scripted reply for kind {call.kind!r}, "
                    f"villager {call.villager!r}"
                )
            rule = self.rules[index]
            reply = rule.replies[min(self._served[index], len(rule.replies) - 1)]
            self._served[index] += 1
        if rule.delay_s:
            self._sleep(rule.delay_s)
        if isinstance(reply, FakeError):
            raise BackendError(f"fake backend: {reply.message}")
        tokens_in = sum(len(m.content.split()) for m in call.messages)
        return Completion(reply, tokens_in, len(reply.split()))

    @classmethod
    def from_file(cls, path: Path, *, concurrency: int = 1) -> FakeBackend:
        """Rules from YAML: a list of {replies, kind?, villager?, pattern?, delay_s?}.

        A reply is text or {error: message}."""
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise LLMSetupError(f"{path}: {error}") from None
        if not isinstance(raw, list):
            raise LLMSetupError(f"{path}: expected a list of rules")
        rules = [_rule(entry, f"{path}[{i}]") for i, entry in enumerate(raw)]
        return cls(rules, concurrency=concurrency)


def _reply(value: object, where: str) -> Reply:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and list(value) == ["error"] and isinstance(value["error"], str):
        return FakeError(value["error"])
    raise LLMSetupError(f"{where}: a reply is text or {{error: message}}")


def _rule(entry: object, where: str) -> FakeRule:
    if not isinstance(entry, dict):
        raise LLMSetupError(f"{where}: expected a mapping")
    unknown = sorted(str(k) for k in entry if k not in RULE_KEYS)
    if unknown:
        raise LLMSetupError(f"{where}.{unknown[0]}: unknown key")
    replies = entry.get("replies")
    if not isinstance(replies, list) or not replies:
        raise LLMSetupError(f"{where}.replies: expected a non-empty list")
    texts: dict[str, Any] = {}
    for key in ("kind", "villager", "pattern"):
        value = entry.get(key)
        if value is not None and not isinstance(value, str):
            raise LLMSetupError(f"{where}.{key}: expected text")
        texts[key] = value
    delay = entry.get("delay_s", 0.0)
    if isinstance(delay, bool) or not isinstance(delay, int | float):
        raise LLMSetupError(f"{where}.delay_s: expected a number")
    parsed = tuple(_reply(r, f"{where}.replies[{j}]") for j, r in enumerate(replies))
    try:
        return FakeRule(parsed, delay_s=float(delay), **texts)
    except (ValueError, re.error) as error:
        raise LLMSetupError(f"{where}: {error}") from None
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles/test_llm_fake.py tests/pericles/test_core_boundaries.py -q`
Expected: PASS.

- [ ] **Step 6: Gates, mutation, commit**

Run the gates, then `PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run --changed-since main`.
Expected: llm ≥ 70%. Add tests for survivors.

```bash
git add -A
git commit -m "feat(llm): gateway types, backend contract and scripted fake backend; ADR-0017

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Output validation and the response cache

**Files:**
- Create: `src/pericles/llm/validate.py`, `src/pericles/llm/cache.py`
- Test: `tests/pericles/test_llm_cache.py`

**Interfaces:**
- Consumes: `BackendCall`, `Completion`, `Message`, `Sampling` (Task 2).
- Produces:
  - `schema_of(output: type[BaseModel]) -> dict[str, Any]`.
  - `unfenced(text: str) -> str`.
  - `validate(output: type[BaseModel], text: str) -> tuple[BaseModel | None, str | None]`.
  - `CACHE_MODES = ("off", "record", "replay")`.
  - `cache_key(model: str, call: BackendCall) -> str`.
  - `class CacheMiss(Exception)`.
  - `class ResponseCache(path: Path | None, mode: str)` with `.mode`, `get(key) -> Completion | None`, `put(key, completion) -> None`, `__len__`, `close()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_llm_cache.py`:

```python
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from pericles.llm.cache import CACHE_MODES, CacheMiss, ResponseCache, cache_key
from pericles.llm.types import BackendCall, Completion, Message, Sampling
from pericles.llm.validate import schema_of, unfenced, validate


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str
    steps: list[str]


SAMPLING = Sampling(0.7, 0.9, 256)


def call(**changes: object) -> BackendCall:
    base: dict[str, object] = {
        "model": "qwen3:latest",
        "messages": (Message("user", "plan your day"),),
        "sampling": SAMPLING,
        "seed": 11,
        "schema": schema_of(Plan),
        "kind": "plan",
        "villager": "ada",
    }
    base.update(changes)
    return BackendCall(**base)  # type: ignore[arg-type]


@pytest.mark.req("REQ-LLM-005")
def test_the_key_hashes_model_sampling_prompt_schema_and_seed() -> None:
    """AC1: changing any part of the key changes the key; kind and villager do not count."""
    key = cache_key("ollama:qwen3:latest", call())
    assert len(key) == 64
    assert key == cache_key("ollama:qwen3:latest", call(kind="vote", villager="bram"))
    assert key != cache_key("mlx:qwen3:latest", call())
    assert key != cache_key("ollama:qwen3:latest", call(sampling=Sampling(0.8, 0.9, 256)))
    assert key != cache_key("ollama:qwen3:latest", call(messages=(Message("user", "other"),)))
    assert key != cache_key("ollama:qwen3:latest", call(schema=None))
    assert key != cache_key("ollama:qwen3:latest", call(seed=12))


@pytest.mark.req("REQ-LLM-005")
def test_record_stores_every_response_and_replay_serves_it(tmp_path: Path) -> None:
    """AC2: record stores (replacing), replay reads, a replay miss is an error."""
    path = tmp_path / "responses.sqlite"
    recorder = ResponseCache(path, "record")
    assert recorder.get("k") is None
    recorder.put("k", Completion("first", 3, 1))
    recorder.put("k", Completion("second", 4, 2))
    assert len(recorder) == 1
    recorder.close()
    replayer = ResponseCache(path, "replay")
    assert replayer.get("k") == Completion("second", 4, 2)
    replayer.put("other", Completion("ignored", 1, 1))
    with pytest.raises(CacheMiss):
        replayer.get("other")
    replayer.close()


@pytest.mark.req("REQ-LLM-005")
def test_off_bypasses_the_cache() -> None:
    """AC2: in off mode nothing is read or stored, and no file is needed."""
    cache = ResponseCache(None, "off")
    cache.put("k", Completion("x", 1, 1))
    assert cache.get("k") is None
    assert len(cache) == 0
    cache.close()


@pytest.mark.req("REQ-LLM-005")
def test_bad_cache_settings_are_rejected(tmp_path: Path) -> None:
    """AC2: only the three modes exist, and record and replay need a file."""
    assert CACHE_MODES == ("off", "record", "replay")
    with pytest.raises(ValueError, match="cache mode must be one of"):
        ResponseCache(tmp_path / "c.sqlite", "sometimes")
    with pytest.raises(ValueError, match="cache mode 'record' needs a path"):
        ResponseCache(None, "record")


@pytest.mark.req("REQ-LLM-001")
@pytest.mark.parametrize(
    ("text", "error"),
    [
        ('{"goal": "eat", "steps": ["gather"]}', None),
        ('```json\n{"goal": "eat", "steps": []}\n```', None),
        ('```\n{"goal": "eat", "steps": []}\n```  ', None),
        ('{"steps": []}', "goal: Field required"),
        ('{"goal": "eat", "steps": [], "mood": "ok"}', "mood: Extra inputs are not permitted"),
        ('{"goal": 3, "steps": []}', "goal: Input should be a valid string"),
        ("not json", "Invalid JSON"),
        ("", "Invalid JSON"),
    ],
)
def test_validation_names_the_field(text: str, error: str | None) -> None:
    """AC1: every output is validated against its schema; errors name the field."""
    value, message = validate(Plan, text)
    if error is None:
        assert isinstance(value, Plan) and message is None
    else:
        assert value is None and message is not None and message.startswith(error)


@pytest.mark.req("REQ-LLM-001")
def test_unfenced_removes_only_one_surrounding_fence() -> None:
    """AC1: text without a fence, or with text around it, is left alone."""
    assert unfenced('{"a": 1}') == '{"a": 1}'
    assert unfenced('see ```json\n{"a": 1}\n```') == 'see ```json\n{"a": 1}\n```'
    assert unfenced('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert schema_of(Plan)["required"] == ["goal", "steps"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_llm_cache.py -q`
Expected: FAIL on import (`pericles.llm.cache`).

- [ ] **Step 3: Implement**

Create `src/pericles/llm/validate.py`:

```python
"""Validate model output against a pydantic output model (ADR-0017 §4)."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ValidationError

FENCE = re.compile(r"^```(?:json)?[ \t]*\n(.*)\n```$", re.DOTALL)


def schema_of(output: type[BaseModel]) -> dict[str, Any]:
    return output.model_json_schema()


def unfenced(text: str) -> str:
    """The text inside one surrounding Markdown code fence, else the text unchanged."""
    match = FENCE.match(text.strip())
    return match.group(1) if match else text


def validate(output: type[BaseModel], text: str) -> tuple[BaseModel | None, str | None]:
    """(value, None) if `text` is valid, else (None, "<field path>: <message>")."""
    try:
        return output.model_validate_json(unfenced(text)), None
    except ValidationError as error:
        first = error.errors()[0]
        loc = ".".join(str(part) for part in first["loc"])
        return None, f"{loc}: {first['msg']}" if loc else str(first["msg"])
```

Create `src/pericles/llm/cache.py`:

```python
"""Response cache: off, record or replay (REQ-LLM-005; ADR-0017 §5)."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from pericles.core.canonical import canonical_json
from pericles.llm.types import BackendCall, Completion

CACHE_MODES = ("off", "record", "replay")
SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    key TEXT PRIMARY KEY,
    text TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL
);
"""


class CacheMiss(Exception):
    """Replay mode found no cached response for a request."""


def cache_key(model: str, call: BackendCall) -> str:
    """SHA-256 of the model ("<backend kind>:<name>"), sampling, messages, schema and seed."""
    payload = {
        "model": model,
        "sampling": call.sampling.to_dict(),
        "messages": [m.to_dict() for m in call.messages],
        "schema": None if call.schema is None else dict(call.schema),
        "seed": call.seed,
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


class ResponseCache:
    def __init__(self, path: Path | None, mode: str) -> None:
        if mode not in CACHE_MODES:
            raise ValueError(f"cache mode must be one of {CACHE_MODES}, got {mode!r}")
        if mode != "off" and path is None:
            raise ValueError(f"cache mode {mode!r} needs a path")
        self.mode = mode
        self._conn: sqlite3.Connection | None = None
        if path is not None and mode != "off":
            self._conn = sqlite3.connect(path)
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def get(self, key: str) -> Completion | None:
        """The cached response in replay mode (a miss raises CacheMiss); None otherwise."""
        if self.mode != "replay" or self._conn is None:
            return None
        row = self._conn.execute(
            "SELECT text, tokens_in, tokens_out FROM responses WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            raise CacheMiss(key)
        return Completion(str(row[0]), int(row[1]), int(row[2]))

    def put(self, key: str, completion: Completion) -> None:
        if self.mode != "record" or self._conn is None:
            return
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?, ?)",
                (key, completion.text, completion.tokens_in, completion.tokens_out),
            )

    def __len__(self) -> int:
        if self._conn is None:
            return 0
        return int(self._conn.execute("SELECT COUNT(*) FROM responses").fetchone()[0])

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles/test_llm_cache.py -q`
Expected: PASS. If a pydantic message differs from the table (pydantic versions word "Invalid JSON" as `Invalid JSON: expected value at line 1 column 1`), keep the test's `startswith` prefix and adjust only the expected prefix to what pydantic ≥ 2.9 prints. Record that in the report.

- [ ] **Step 5: Gates, mutation, commit**

```bash
git add -A
git commit -m "feat(llm): output validation and the off/record/replay response cache

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The call log

**Files:**
- Create: `src/pericles/llm/calls.py`
- Test: `tests/pericles/test_llm_calls.py`

**Interfaces:**
- Produces:
  - `CallRecord`, a frozen dataclass with fields `tick: int`, `villager: str`, `kind: str`, `model: str`, `backend: str`, `backend_model: str`, `prompt_hash: str`, `tokens_in: int`, `tokens_out: int`, `latency_s: float`, `valid: bool`, `error: str | None`, `attempt: int`, `cached: bool`, `template: str | None` and `raw: str`, in that order.
  - `CallLog(path: Path)` with `append(record)`, `records(start: int = 0, end: int | None = None) -> Iterator[CallRecord]` (in insertion order), `truncate_after(tick: int)` and `close()`.

- [ ] **Step 1: Write the failing test**

Create `tests/pericles/test_llm_calls.py`:

```python
import sqlite3
import zlib
from dataclasses import replace
from pathlib import Path

import pytest

from pericles.llm.calls import CallLog, CallRecord

RECORD = CallRecord(
    tick=5,
    villager="ada",
    kind="plan",
    model="qwen",
    backend="ollama",
    backend_model="qwen3:latest",
    prompt_hash="ab" * 32,
    tokens_in=120,
    tokens_out=40,
    latency_s=1.25,
    valid=False,
    error="goal: Field required",
    attempt=1,
    cached=False,
    template="plan-v1",
    raw='{"steps": []}',
)


@pytest.mark.req("REQ-LLM-008")
def test_every_field_round_trips(tmp_path: Path) -> None:
    """AC1: model, prompt hash, tokens, latency, validity, retry count and raw output."""
    log = CallLog(tmp_path / "llm_calls.sqlite")
    log.append(RECORD)
    log.append(replace(RECORD, tick=6, valid=True, error=None, cached=True, template=None))
    assert list(log.records()) == [
        RECORD,
        replace(RECORD, tick=6, valid=True, error=None, cached=True, template=None),
    ]
    log.close()


@pytest.mark.req("REQ-LLM-008")
def test_raw_output_is_stored_compressed(tmp_path: Path) -> None:
    """AC1: the raw output is zlib-compressed on disk."""
    path = tmp_path / "llm_calls.sqlite"
    log = CallLog(path)
    log.append(replace(RECORD, raw="x" * 1000))
    log.close()
    blob = sqlite3.connect(path).execute("SELECT raw FROM calls").fetchone()[0]
    assert len(blob) < 100
    assert zlib.decompress(blob).decode("utf-8") == "x" * 1000


@pytest.mark.req("REQ-LLM-008")
def test_records_filter_by_tick_and_truncate(tmp_path: Path) -> None:
    """AC1: the log follows the event log on resume."""
    log = CallLog(tmp_path / "llm_calls.sqlite")
    for tick in (1, 2, 2, 3):
        log.append(replace(RECORD, tick=tick))
    assert [r.tick for r in log.records(2)] == [2, 2, 3]
    assert [r.tick for r in log.records(1, 3)] == [1, 2, 2]
    log.truncate_after(1)
    assert [r.tick for r in log.records()] == [1]
    log.close()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/pericles/test_llm_calls.py -q`
Expected: FAIL on import.

- [ ] **Step 3: Implement**

Create `src/pericles/llm/calls.py`:

```python
"""One row per LLM call, outside the event log (REQ-LLM-008; ADR-0017 §6)."""

from __future__ import annotations

import sqlite3
import zlib
from collections.abc import Iterator
from dataclasses import astuple, dataclass, fields
from pathlib import Path


@dataclass(frozen=True)
class CallRecord:
    tick: int
    villager: str
    kind: str
    model: str
    backend: str
    backend_model: str
    prompt_hash: str
    tokens_in: int
    tokens_out: int
    latency_s: float
    valid: bool
    error: str | None
    attempt: int
    cached: bool
    template: str | None
    raw: str


COLUMNS = tuple(f.name for f in fields(CallRecord))
SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER NOT NULL,
    villager TEXT NOT NULL,
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    backend TEXT NOT NULL,
    backend_model TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    tokens_in INTEGER NOT NULL,
    tokens_out INTEGER NOT NULL,
    latency_s REAL NOT NULL,
    valid INTEGER NOT NULL,
    error TEXT,
    attempt INTEGER NOT NULL,
    cached INTEGER NOT NULL,
    template TEXT,
    raw BLOB NOT NULL
);
"""


class CallLog:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def append(self, record: CallRecord) -> None:
        values = list(astuple(record))
        values[COLUMNS.index("raw")] = zlib.compress(record.raw.encode("utf-8"))
        placeholders = ", ".join("?" for _ in COLUMNS)
        with self._conn:
            self._conn.execute(
                f"INSERT INTO calls ({', '.join(COLUMNS)}) VALUES ({placeholders})", values
            )

    def records(self, start: int = 0, end: int | None = None) -> Iterator[CallRecord]:
        query = f"SELECT {', '.join(COLUMNS)} FROM calls WHERE tick >= ?"
        params: list[int] = [start]
        if end is not None:
            query += " AND tick < ?"
            params.append(end)
        for row in self._conn.execute(query + " ORDER BY id", params):
            item = dict(zip(COLUMNS, row, strict=True))
            item["raw"] = zlib.decompress(item["raw"]).decode("utf-8")
            item["valid"] = bool(item["valid"])
            item["cached"] = bool(item["cached"])
            yield CallRecord(**item)

    def truncate_after(self, tick: int) -> None:
        with self._conn:
            self._conn.execute("DELETE FROM calls WHERE tick > ?", (tick,))

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/pericles/test_llm_calls.py -q`
Expected: PASS.

- [ ] **Step 5: Gates, mutation, commit**

```bash
git add -A
git commit -m "feat(llm): call log with compressed raw output

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The gateway

**Files:**
- Create: `src/pericles/llm/gateway.py`
- Test: `tests/pericles/test_llm_gateway.py`

**Interfaces:**
- Consumes: Tasks 2–4.
- Produces:
  - `MODES = ("wait", "live")`.
  - `FailurePolicy(mode, backoff_base_s, backoff_factor, backoff_max_s, max_backend_failures)` with `delay(failures: int) -> float`.
  - `class BackendUnavailable(Exception)`.
  - `prompt_hash(call: BackendCall) -> str`.
  - `check_models(models: Mapping[str, ModelSpec], backends: Mapping[str, Backend]) -> None`.
  - `Gateway(models, backends, cache, policy, calls=None, *, clock=time.monotonic, sleep=time.sleep)` with `.models`, `.backends`, `.cache`, `.calls`, `check()`, `complete(request) -> Result`, `complete_all(requests) -> list[Result]` and `close()`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_llm_gateway.py`:

```python
import threading
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from pericles.llm.backend import BackendError, LLMSetupError
from pericles.llm.cache import CacheMiss, ResponseCache
from pericles.llm.calls import CallLog
from pericles.llm.fake import FakeBackend, FakeError, FakeRule
from pericles.llm.gateway import (
    BackendUnavailable,
    FailurePolicy,
    Gateway,
    check_models,
    prompt_hash,
)
from pericles.llm.types import BackendCall, Completion, Message, ModelSpec, Request, Sampling


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pick: int


SAMPLING = Sampling(0.7, 0.9, 64)
WAIT = FailurePolicy("wait", 2.0, 3.0, 10.0, 4)
LIVE = FailurePolicy("live", 2.0, 3.0, 10.0, 4)


def request(villager: str = "ada", model: str = "m", tick: int = 3, attempt: int = 0) -> Request:
    return Request(
        "plan",
        villager,
        tick,
        model,
        (Message("user", f"hello {villager}"),),
        seed=tick,
        output=Choice,
        attempt=attempt,
        template="plan-v1",
    )


def gateway(
    backends: dict[str, FakeBackend],
    tmp_path: Path,
    *,
    mode: str = "record",
    policy: FailurePolicy = WAIT,
    models: dict[str, ModelSpec] | None = None,
    slept: list[float] | None = None,
) -> Gateway:
    models = models or {"m": ModelSpec("f", "fake-m", SAMPLING)}
    cache = ResponseCache(None if mode == "off" else tmp_path / "responses.sqlite", mode)
    ticks = iter(float(n) for n in range(1000))
    return Gateway(
        models,
        backends,  # type: ignore[arg-type]
        cache,
        policy,
        CallLog(tmp_path / f"calls-{mode}.sqlite"),
        clock=lambda: next(ticks),
        sleep=(slept if slept is not None else []).append,
    )


@pytest.mark.req("REQ-LLM-001")
def test_a_valid_reply_is_validated_and_logged(tmp_path: Path) -> None:
    """AC1: a request goes through the gateway to the backend and comes back validated."""
    backend = FakeBackend([FakeRule(('{"pick": 2}',))])
    g = gateway({"f": backend}, tmp_path)
    result = g.complete(request())
    assert result.valid and result.value == Choice(pick=2) and not result.cached
    assert result.latency_s == 1.0
    sent = backend.calls[0]
    assert (sent.model, sent.seed, sent.kind, sent.villager) == ("fake-m", 3, "plan", "ada")
    assert sent.schema == Choice.model_json_schema()
    g.close()


@pytest.mark.req("REQ-LLM-008")
def test_every_call_is_logged_with_its_metrics(tmp_path: Path) -> None:
    """AC1: model, prompt hash, tokens, latency, validity, retry count, raw output."""
    backend = FakeBackend([FakeRule(('{"pick": "x"}',))])
    g = gateway({"f": backend}, tmp_path)
    result = g.complete(request(attempt=2))
    assert result.error is not None and result.error.startswith("pick:")
    assert g.calls is not None
    (record,) = list(g.calls.records())
    assert (record.model, record.backend, record.backend_model) == ("m", "fake", "fake-m")
    assert record.prompt_hash == prompt_hash(backend.calls[0])
    assert (record.tokens_in, record.tokens_out, record.latency_s) == (2, 2, 1.0)
    assert (record.valid, record.attempt, record.cached) == (False, 2, False)
    assert record.error == result.error
    assert (record.raw, record.template, record.tick) == ('{"pick": "x"}', "plan-v1", 3)
    g.close()


@pytest.mark.req("REQ-LLM-005")
def test_replay_answers_from_the_cache_without_a_backend(tmp_path: Path) -> None:
    """AC2: record stores, replay serves without calling the backend; a miss is an error."""
    recorder = gateway({"f": FakeBackend([FakeRule(('{"pick": 1}',))])}, tmp_path)
    recorder.complete(request())
    recorder.close()
    silent = FakeBackend()
    replayer = gateway({"f": silent}, tmp_path, mode="replay")
    result = replayer.complete(request())
    assert result.cached and result.value == Choice(pick=1) and result.latency_s == 0.0
    assert silent.calls == []
    assert replayer.calls is not None
    assert [r.cached for r in replayer.calls.records()] == [True]
    with pytest.raises(CacheMiss, match="no cached response for plan by bram at tick 3"):
        replayer.complete(request("bram"))
    replayer.close()


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_backs_off_then_succeeds(tmp_path: Path) -> None:
    """AC1: a backend error pauses with exponential backoff and retries."""
    backend = FakeBackend([FakeRule((FakeError("busy"), FakeError("busy"), '{"pick": 1}'))])
    slept: list[float] = []
    g = gateway({"f": backend}, tmp_path, slept=slept)
    assert g.complete(request()).valid
    assert slept == [2.0, 6.0]
    assert g.calls is not None
    rows = list(g.calls.records())
    assert [(r.valid, r.error) for r in rows] == [
        (False, "backend: fake backend: busy"),
        (False, "backend: fake backend: busy"),
        (True, None),
    ]
    g.close()


@pytest.mark.req("REQ-LLM-009")
def test_wait_mode_gives_up_after_max_backend_failures(tmp_path: Path) -> None:
    """AC1: after max_backend_failures in a row the gateway raises BackendUnavailable."""
    slept: list[float] = []
    g = gateway({"f": FakeBackend([FakeRule((FakeError("down"),))])}, tmp_path, slept=slept)
    with pytest.raises(BackendUnavailable, match="fake backend: 4 failures in a row; last: fake backend: down"):
        g.complete(request())
    assert slept == [2.0, 6.0, 10.0]
    assert g.calls is not None
    assert len(list(g.calls.records())) == 4
    g.close()


@pytest.mark.req("REQ-LLM-009")
def test_live_mode_returns_a_backend_error_at_once(tmp_path: Path) -> None:
    """AC2 (gateway part): in live mode a failure is one try and a flagged result."""
    slept: list[float] = []
    backend = FakeBackend(
        [FakeRule((FakeError("down"),), villager="ada"), FakeRule(('{"pick": 5}',))]
    )
    g = gateway({"f": backend}, tmp_path, policy=LIVE, slept=slept)
    failed, fine = g.complete_all([request("ada"), request("bram")])
    assert failed.backend_error == "fake backend: down" and failed.value is None
    assert not failed.valid
    assert fine.value == Choice(pick=5)
    assert slept == []
    g.close()


def test_failure_policy_delay_is_capped() -> None:
    """The n-th failure in a row waits base * factor^(n-1), at most backoff_max_s."""
    assert [WAIT.delay(n) for n in (1, 2, 3, 4)] == [2.0, 6.0, 10.0, 10.0]


@pytest.mark.req("REQ-LLM-007")
def test_results_follow_request_order_not_completion_order(tmp_path: Path) -> None:
    """AC2: shuffling the requests changes no villager's result."""
    rules = [FakeRule((f'{{"pick": {n}}}',), villager=v) for n, v in enumerate("abcde")]
    forward = gateway({"f": FakeBackend(rules, concurrency=3)}, tmp_path, mode="off")
    backward = gateway({"f": FakeBackend(rules, concurrency=3)}, tmp_path, mode="off")
    ids = list("abcde")
    one = {r.request.villager: r.value for r in forward.complete_all([request(v) for v in ids])}
    two = {r.request.villager: r.value for r in backward.complete_all([request(v) for v in reversed(ids)])}
    assert one == two == {v: Choice(pick=n) for n, v in enumerate(ids)}
    forward.close()
    backward.close()


class Tracking(FakeBackend):
    """Counts calls in flight and records the model order."""

    def __init__(self, rules: Sequence[FakeRule], concurrency: int, gate: threading.Barrier | None) -> None:
        super().__init__(rules, concurrency=concurrency)
        self.in_flight = 0
        self.peak = 0
        self.order: list[str] = []
        self.gate = gate
        self.lock = threading.Lock()

    def complete(self, call: BackendCall) -> Completion:
        with self.lock:
            self.in_flight += 1
            self.peak = max(self.peak, self.in_flight)
            self.order.append(call.model)
        if self.gate is not None:
            self.gate.wait(timeout=5)
        try:
            return super().complete(call)
        finally:
            with self.lock:
                self.in_flight -= 1


@pytest.mark.req("REQ-LLM-007")
def test_requests_are_batched_by_model_within_the_concurrency_limit(tmp_path: Path) -> None:
    """AC1: one model at a time per backend, at most `concurrency` calls in flight."""
    backend = Tracking([FakeRule(('{"pick": 0}',))], concurrency=2, gate=threading.Barrier(2))
    models = {
        "x": ModelSpec("f", "model-x", SAMPLING),
        "y": ModelSpec("f", "model-y", SAMPLING),
    }
    g = gateway({"f": backend}, tmp_path, mode="off", models=models)
    mixed = [request(v, model=m) for v, m in zip("abcd", "yxyx", strict=True)]
    results = g.complete_all(mixed)
    assert [r.request.villager for r in results] == list("abcd")
    assert backend.order == ["model-x", "model-x", "model-y", "model-y"]
    assert backend.peak == 2
    g.close()


@pytest.mark.req("REQ-LLM-002")
def test_check_asks_each_backend_for_its_models(tmp_path: Path) -> None:
    """AC1 (gateway part): a configured model the backend lacks fails fast."""
    models = {
        "a": ModelSpec("one", "alpha", SAMPLING),
        "b": ModelSpec("one", "beta", SAMPLING),
        "c": ModelSpec("two", "gamma", SAMPLING),
    }
    backends = {"one": FakeBackend(models=["alpha", "beta"]), "two": FakeBackend(models=[])}
    with pytest.raises(LLMSetupError, match="not available: gamma"):
        check_models(models, backends)  # type: ignore[arg-type]
    check_models({k: v for k, v in models.items() if k != "c"}, backends)  # type: ignore[arg-type]


def test_gateway_rejects_unknown_backends_models_and_modes(tmp_path: Path) -> None:
    """A model must name a backend, a request a model, a policy a mode."""
    with pytest.raises(ValueError, match="model 'm': unknown backend 'f'"):
        gateway({}, tmp_path)
    with pytest.raises(ValueError, match="mode must be one of"):
        gateway({"f": FakeBackend()}, tmp_path, policy=FailurePolicy("eventually", 1.0, 1.0, 1.0, 1))
    g = gateway({"f": FakeBackend()}, tmp_path)
    with pytest.raises(ValueError, match="unknown model 'nope'"):
        g.complete(request(model="nope"))
    g.close()


def test_a_request_without_an_output_model_is_not_validated(tmp_path: Path) -> None:
    """Free text (e.g. a board post rendered later) passes through unvalidated."""
    g = gateway({"f": FakeBackend([FakeRule(("just words",))])}, tmp_path)
    plain = Request("post", "ada", 1, "m", (Message("user", "say hi"),), seed=1)
    result = g.complete(plain)
    assert result.valid and result.value is None and result.text == "just words"
    g.close()


def test_backend_error_type_is_reexported_for_callers() -> None:
    """Callers catch BackendError from pericles.llm.backend."""
    assert issubclass(BackendUnavailable, Exception)
    assert not issubclass(BackendUnavailable, BackendError)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_llm_gateway.py -q`
Expected: FAIL on import (`pericles.llm.gateway`).

- [ ] **Step 3: Implement**

Create `src/pericles/llm/gateway.py`:

```python
"""The one way to call a model (REQ-LLM-001, -005, -007, -008, -009; ADR-0017)."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from pericles.core.canonical import canonical_json
from pericles.llm.backend import Backend, BackendError
from pericles.llm.cache import CacheMiss, ResponseCache, cache_key
from pericles.llm.calls import CallLog, CallRecord
from pericles.llm.types import BackendCall, Completion, ModelSpec, Request, Result
from pericles.llm.validate import schema_of, validate

MODES = ("wait", "live")


@dataclass(frozen=True)
class FailurePolicy:
    mode: str
    backoff_base_s: float
    backoff_factor: float
    backoff_max_s: float
    max_backend_failures: int

    def delay(self, failures: int) -> float:
        """Seconds to wait after the `failures`-th failure in a row (counting from 1)."""
        return min(self.backoff_base_s * self.backoff_factor ** (failures - 1), self.backoff_max_s)


class BackendUnavailable(Exception):
    """Wait mode: a backend failed `max_backend_failures` times in a row. Stop and resume."""


@dataclass(frozen=True)
class _Outcome:
    completion: Completion | None
    latency_s: float
    errors: tuple[str, ...]


def prompt_hash(call: BackendCall) -> str:
    text = canonical_json([m.to_dict() for m in call.messages])
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def check_models(models: Mapping[str, ModelSpec], backends: Mapping[str, Backend]) -> None:
    """Fail fast: each backend confirms it can serve the models configured on it."""
    for key in sorted(backends):
        names = sorted({spec.name for spec in models.values() if spec.backend == key})
        if names:
            backends[key].check(names)


class Gateway:
    def __init__(
        self,
        models: Mapping[str, ModelSpec],
        backends: Mapping[str, Backend],
        cache: ResponseCache,
        policy: FailurePolicy,
        calls: CallLog | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        for key in sorted(models):
            if models[key].backend not in backends:
                raise ValueError(f"model {key!r}: unknown backend {models[key].backend!r}")
        if policy.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {policy.mode!r}")
        self.models = dict(models)
        self.backends = dict(backends)
        self.cache = cache
        self.policy = policy
        self.calls = calls
        self._clock = clock
        self._sleep = sleep

    def check(self) -> None:
        check_models(self.models, self.backends)

    def complete(self, request: Request) -> Result:
        return self.complete_all([request])[0]

    def complete_all(self, requests: Sequence[Request]) -> list[Result]:
        specs = [self._spec(r) for r in requests]
        calls = [self._call(r, s) for r, s in zip(requests, specs, strict=True)]
        keys = [
            cache_key(f"{self.backends[s.backend].kind}:{s.name}", c)
            for s, c in zip(specs, calls, strict=True)
        ]
        hits: dict[int, Completion] = {}
        for i, request in enumerate(requests):
            try:
                hit = self.cache.get(keys[i])
            except CacheMiss:
                raise CacheMiss(
                    f"replay: no cached response for {request.kind} by {request.villager} "
                    f"at tick {request.tick} (model {request.model})"
                ) from None
            if hit is not None:
                hits[i] = hit
        groups: dict[tuple[str, str], list[int]] = {}
        for i, spec in enumerate(specs):
            if i not in hits:
                groups.setdefault((spec.backend, spec.name), []).append(i)
        outcomes: dict[int, _Outcome] = {}
        for backend_key, name in sorted(groups):
            backend = self.backends[backend_key]
            indices = groups[(backend_key, name)]
            with ThreadPoolExecutor(max_workers=backend.concurrency) as pool:
                done = list(pool.map(lambda i, b=backend: self._attempt(b, calls[i]), indices))
            outcomes.update(zip(indices, done, strict=True))
        results: list[Result] = []
        unavailable: str | None = None
        for i, request in enumerate(requests):
            spec, call = specs[i], calls[i]
            backend = self.backends[spec.backend]
            if i in hits:
                result = self._result(request, hits[i], 0.0, cached=True)
                self._log(request, spec, call, result)
                results.append(result)
                continue
            outcome = outcomes[i]
            for error in outcome.errors:
                self._log_failure(request, spec, call, error)
            if outcome.completion is None:
                last = outcome.errors[-1]
                if self.policy.mode == "wait" and unavailable is None:
                    unavailable = (
                        f"{backend.describe()}: {len(outcome.errors)} failures in a row; "
                        f"last: {last}"
                    )
                results.append(Result(request, "", None, None, last, 0, 0, 0.0, False))
                continue
            self.cache.put(keys[i], outcome.completion)
            result = self._result(request, outcome.completion, outcome.latency_s, cached=False)
            self._log(request, spec, call, result)
            results.append(result)
        if unavailable is not None:
            raise BackendUnavailable(unavailable)
        return results

    def close(self) -> None:
        self.cache.close()
        if self.calls is not None:
            self.calls.close()

    def _spec(self, request: Request) -> ModelSpec:
        if request.model not in self.models:
            raise ValueError(f"unknown model {request.model!r}")
        return self.models[request.model]

    @staticmethod
    def _call(request: Request, spec: ModelSpec) -> BackendCall:
        schema = None if request.output is None else schema_of(request.output)
        return BackendCall(
            spec.name,
            request.messages,
            spec.sampling,
            request.seed,
            schema,
            request.kind,
            request.villager,
        )

    def _attempt(self, backend: Backend, call: BackendCall) -> _Outcome:
        tries = 1 if self.policy.mode == "live" else self.policy.max_backend_failures
        errors: list[str] = []
        for failure in range(1, tries + 1):
            start = self._clock()
            try:
                completion = backend.complete(call)
            except BackendError as error:
                errors.append(str(error))
                if failure < tries:
                    self._sleep(self.policy.delay(failure))
                continue
            return _Outcome(completion, self._clock() - start, tuple(errors))
        return _Outcome(None, 0.0, tuple(errors))

    @staticmethod
    def _result(request: Request, completion: Completion, latency: float, *, cached: bool) -> Result:
        value, error = (None, None)
        if request.output is not None:
            value, error = validate(request.output, completion.text)
        return Result(
            request,
            completion.text,
            value,
            error,
            None,
            completion.tokens_in,
            completion.tokens_out,
            latency,
            cached,
        )

    def _log(self, request: Request, spec: ModelSpec, call: BackendCall, result: Result) -> None:
        if self.calls is None:
            return
        self.calls.append(
            CallRecord(
                request.tick,
                request.villager,
                request.kind,
                request.model,
                self.backends[spec.backend].kind,
                spec.name,
                prompt_hash(call),
                result.tokens_in,
                result.tokens_out,
                result.latency_s,
                result.valid,
                result.error,
                request.attempt,
                result.cached,
                request.template,
                result.text,
            )
        )

    def _log_failure(self, request: Request, spec: ModelSpec, call: BackendCall, error: str) -> None:
        if self.calls is None:
            return
        self.calls.append(
            CallRecord(
                request.tick,
                request.villager,
                request.kind,
                request.model,
                self.backends[spec.backend].kind,
                spec.name,
                prompt_hash(call),
                0,
                0,
                0.0,
                False,
                f"backend: {error}",
                request.attempt,
                False,
                request.template,
                "",
            )
        )
```

`test_wait_mode_backs_off_then_succeeds` uses a clock that advances by 1 on each read. The successful attempt's latency is the difference of two reads, which is 1.0. If ruff's `B023` complains about the lambda in the pool, the default-argument binding `b=backend` already satisfies it. Keep it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles/test_llm_gateway.py -q`
Expected: PASS.

- [ ] **Step 5: Gates, mutation, commit**

Run the gates and the mutation gate.
Expected: llm ≥ 70%. The backoff arithmetic and the `strict=True` zips are typical survivors. Kill them with the delay test and the ordering tests above, extended if needed.

```bash
git add -A
git commit -m "feat(llm): gateway with cache, validation, per-model batching, call metrics and backoff

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The Ollama backend

**Files:**
- Create: `src/pericles/llm/ollama.py`
- Test: `tests/pericles/test_llm_ollama.py` (unit, against a stub server), `tests/pericles/test_llm_ollama_contract.py` (slow, live Ollama)

**Interfaces:**
- Consumes: `Backend` contract, `BackendCall`, `Completion`, `BackendError`, `LLMSetupError`.
- Produces:
  - `Transport = Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]]`.
  - `http_json(method: str, url: str, body: dict[str, Any] | None, timeout_s: float) -> dict[str, Any]`.
  - `OllamaBackend(url: str, timeout_s: float, concurrency: int, transport: Transport = http_json)` with `kind = "ollama"` and `available() -> list[str]`.
  - `tagged(name: str) -> str`.

- [ ] **Step 1: Write the failing unit tests**

Create `tests/pericles/test_llm_ollama.py`:

```python
import json
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from pericles.llm.backend import Backend, BackendError, LLMSetupError
from pericles.llm.ollama import OllamaBackend, http_json, tagged
from pericles.llm.types import BackendCall, Message, Sampling

CALL = BackendCall(
    "qwen3",
    (Message("system", "be brief"), Message("user", "plan")),
    Sampling(0.7, 0.9, 128),
    42,
    {"type": "object"},
    "plan",
    "ada",
)


class Stub:
    """A local HTTP server answering canned (status, body) per path."""

    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, bytes]] = {}
        self.seen: list[tuple[str, str, Any]] = []
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                stub.seen.append((self.command, self.path, body))
                status, payload = stub.routes.get(self.path, (404, b'{"error": "no route"}'))
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            do_GET = do_POST = _answer

            def log_message(self, *args: Any) -> None:
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def stub() -> Iterator[Stub]:
    server = Stub()
    yield server
    server.close()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.req("REQ-LLM-002")
def test_http_json_posts_json_and_reads_json(stub: Stub) -> None:
    """AC2: the transport speaks JSON both ways."""
    stub.routes["/api/chat"] = (200, b'{"ok": true}')
    assert http_json("POST", stub.url + "/api/chat", {"a": 1}, 5.0) == {"ok": True}
    assert stub.seen == [("POST", "/api/chat", {"a": 1})]


@pytest.mark.req("REQ-LLM-009")
@pytest.mark.parametrize(
    ("route", "message"),
    [
        ((500, b"model crashed"), "HTTP 500: model crashed"),
        ((200, b"not json"), "not JSON"),
        ((200, b"[1, 2]"), "not a JSON object"),
    ],
)
def test_http_failures_are_backend_errors(stub: Stub, route: tuple[int, bytes], message: str) -> None:
    """AC1: server errors and garbage are BackendErrors, so the gateway backs off."""
    stub.routes["/x"] = route
    with pytest.raises(BackendError, match=message):
        http_json("GET", stub.url + "/x", None, 5.0)


@pytest.mark.req("REQ-LLM-009")
def test_a_refused_connection_is_a_backend_error() -> None:
    """AC1: an Ollama that is not running is a BackendError naming the URL."""
    url = f"http://127.0.0.1:{free_port()}/api/tags"
    with pytest.raises(BackendError, match=url):
        http_json("GET", url, None, 2.0)


@pytest.mark.req("REQ-LLM-001")
def test_ollama_implements_the_interface() -> None:
    """AC2: OllamaBackend satisfies the Backend protocol."""
    backend: Backend = OllamaBackend("http://localhost:11434/", 30.0, 2)
    assert (backend.kind, backend.concurrency) == ("ollama", 2)
    assert backend.describe() == "ollama at http://localhost:11434"


@pytest.mark.req("REQ-LLM-002")
def test_complete_sends_schema_sampling_and_seed(stub: Stub) -> None:
    """AC2: schema-constrained output via `format`; sampling and seed as options."""
    stub.routes["/api/chat"] = (
        200,
        b'{"message": {"role": "assistant", "content": "{}"}, "prompt_eval_count": 30, "eval_count": 4}',
    )
    completion = OllamaBackend(stub.url, 5.0, 1).complete(CALL)
    assert (completion.text, completion.tokens_in, completion.tokens_out) == ("{}", 30, 4)
    _, path, body = stub.seen[0]
    assert path == "/api/chat"
    assert body == {
        "model": "qwen3",
        "messages": [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "plan"},
        ],
        "stream": False,
        "format": {"type": "object"},
        "options": {"temperature": 0.7, "top_p": 0.9, "num_predict": 128, "seed": 42},
    }


@pytest.mark.req("REQ-LLM-002")
def test_complete_without_schema_sends_no_format(stub: Stub) -> None:
    """AC2: free-text calls are not constrained."""
    stub.routes["/api/chat"] = (200, b'{"message": {"content": "hi"}}')
    completion = OllamaBackend(stub.url, 5.0, 1).complete(
        BackendCall("m", (Message("user", "x"),), Sampling(0.1, 1.0, 8), 1)
    )
    assert (completion.text, completion.tokens_in, completion.tokens_out) == ("hi", 0, 0)
    assert "format" not in stub.seen[0][2]


@pytest.mark.req("REQ-LLM-009")
def test_an_unexpected_reply_shape_is_a_backend_error(stub: Stub) -> None:
    """AC1: a reply without message.content is a BackendError, not a KeyError."""
    stub.routes["/api/chat"] = (200, b'{"done": true}')
    with pytest.raises(BackendError, match="unexpected reply"):
        OllamaBackend(stub.url, 5.0, 1).complete(CALL)


@pytest.mark.req("REQ-LLM-002")
def test_check_lists_models_and_names_the_missing_ones(stub: Stub) -> None:
    """AC1: lists the models and fails fast with a clear message."""
    stub.routes["/api/tags"] = (
        200,
        b'{"models": [{"name": "qwen3:latest"}, {"name": "llama3.1:8b"}]}',
    )
    backend = OllamaBackend(stub.url, 5.0, 1)
    assert backend.available() == ["llama3.1:8b", "qwen3:latest"]
    backend.check(["qwen3", "llama3.1:8b"])
    with pytest.raises(LLMSetupError) as error:
        backend.check(["qwen3", "mistral-nemo"])
    text = str(error.value)
    assert f"ollama at {stub.url}" in text
    assert "not available: mistral-nemo" in text
    assert "ollama pull mistral-nemo" in text
    assert "llama3.1:8b, qwen3:latest" in text


@pytest.mark.req("REQ-LLM-002")
def test_check_on_an_unreachable_server_says_how_to_start_it() -> None:
    """AC1: an Ollama that is not running fails fast."""
    backend = OllamaBackend(f"http://127.0.0.1:{free_port()}", 2.0, 1)
    with pytest.raises(LLMSetupError, match="cannot reach ollama at .*`ollama serve`"):
        backend.check(["qwen3"])


@pytest.mark.req("REQ-LLM-002")
def test_a_tag_listing_of_the_wrong_shape_is_a_setup_error(stub: Stub) -> None:
    """AC1: a server that is not Ollama is reported, not a KeyError."""
    stub.routes["/api/tags"] = (200, b'{"models": "none"}')
    with pytest.raises(LLMSetupError, match="unexpected model listing"):
        OllamaBackend(stub.url, 5.0, 1).check(["qwen3"])


def test_a_name_without_a_tag_means_latest() -> None:
    """Ollama treats `qwen3` and `qwen3:latest` as the same model."""
    assert tagged("qwen3") == "qwen3:latest"
    assert tagged("qwen3:8b") == "qwen3:8b"
```

- [ ] **Step 2: Write the slow contract tests**

Create `tests/pericles/test_llm_ollama_contract.py`:

```python
"""Contract tests against the local Ollama. Run with `uv run pytest -m slow`."""

import os

import pytest
from pydantic import BaseModel, ConfigDict

from pericles.llm.backend import LLMSetupError
from pericles.llm.ollama import OllamaBackend
from pericles.llm.types import BackendCall, Message, Sampling
from pericles.llm.validate import schema_of, validate

pytestmark = pytest.mark.slow
URL = os.environ.get("PERICLES_OLLAMA_URL", "http://localhost:11434")
MODEL = os.environ.get("PERICLES_OLLAMA_MODEL", "llama3.1:8b")


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colour: str
    count: int


@pytest.mark.req("REQ-LLM-002")
def test_the_configured_model_is_listed() -> None:
    """AC1/AC3: the live server lists the contract-test model."""
    OllamaBackend(URL, 30.0, 1).check([MODEL])


@pytest.mark.req("REQ-LLM-002")
def test_a_missing_model_fails_fast() -> None:
    """AC1/AC3: a model that is not pulled is named."""
    with pytest.raises(LLMSetupError, match="pericles-no-such-model"):
        OllamaBackend(URL, 30.0, 1).check(["pericles-no-such-model"])


@pytest.mark.req("REQ-LLM-002")
def test_schema_constrained_output_validates() -> None:
    """AC2/AC3: with `format`, the live model returns JSON matching the schema."""
    call = BackendCall(
        MODEL,
        (Message("user", "Name a colour and a small number, as JSON."),),
        Sampling(0.2, 0.9, 64),
        7,
        schema_of(Answer),
    )
    completion = OllamaBackend(URL, 300.0, 1).complete(call)
    value, error = validate(Answer, completion.text)
    assert error is None and isinstance(value, Answer)
    assert completion.tokens_in > 0 and completion.tokens_out > 0
```

- [ ] **Step 3: Run the unit tests to verify they fail**

Run: `uv run pytest tests/pericles/test_llm_ollama.py -q`
Expected: FAIL on import (`pericles.llm.ollama`).

- [ ] **Step 4: Implement**

Create `src/pericles/llm/ollama.py`:

```python
"""Ollama over HTTP, standard library only (REQ-LLM-002; ADR-0017 §3)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence
from typing import Any

from pericles.llm.backend import BackendError, LLMSetupError
from pericles.llm.types import BackendCall, Completion

Transport = Callable[[str, str, dict[str, Any] | None, float], dict[str, Any]]
DETAIL = 200


def http_json(method: str, url: str, body: dict[str, Any] | None, timeout_s: float) -> dict[str, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            text = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:DETAIL]
        raise BackendError(f"{method} {url}: HTTP {error.code}: {detail}") from None
    except (urllib.error.URLError, OSError) as error:
        raise BackendError(f"{method} {url}: {error}") from None
    try:
        payload = json.loads(text)
    except ValueError:
        raise BackendError(f"{method} {url}: reply is not JSON: {text[:DETAIL]!r}") from None
    if not isinstance(payload, dict):
        raise BackendError(f"{method} {url}: reply is not a JSON object")
    return payload


def tagged(name: str) -> str:
    """Ollama's name for a model: no tag means `:latest`."""
    return name if ":" in name else f"{name}:latest"


class OllamaBackend:
    kind = "ollama"

    def __init__(
        self, url: str, timeout_s: float, concurrency: int, transport: Transport = http_json
    ) -> None:
        self.url = url.rstrip("/")
        self.timeout_s = timeout_s
        self.concurrency = concurrency
        self._transport = transport

    def describe(self) -> str:
        return f"ollama at {self.url}"

    def available(self) -> list[str]:
        payload = self._transport("GET", f"{self.url}/api/tags", None, self.timeout_s)
        models = payload.get("models")
        if not isinstance(models, list) or not all(
            isinstance(m, dict) and isinstance(m.get("name"), str) for m in models
        ):
            raise LLMSetupError(f"{self.describe()}: unexpected model listing")
        return sorted(str(m["name"]) for m in models)

    def check(self, models: Sequence[str]) -> None:
        try:
            available = self.available()
        except BackendError as error:
            raise LLMSetupError(
                f"cannot reach {self.describe()} ({error}); is `ollama serve` running?"
            ) from None
        have = {tagged(name) for name in available}
        missing = [m for m in models if tagged(m) not in have]
        if missing:
            raise LLMSetupError(
                f"{self.describe()}: model(s) not available: {', '.join(missing)}. "
                f"Available: {', '.join(available) or 'none'}. "
                f"Pull with `ollama pull {missing[0]}`."
            )

    def complete(self, call: BackendCall) -> Completion:
        body: dict[str, Any] = {
            "model": call.model,
            "messages": [m.to_dict() for m in call.messages],
            "stream": False,
            "options": {
                "temperature": call.sampling.temperature,
                "top_p": call.sampling.top_p,
                "num_predict": call.sampling.max_tokens,
                "seed": call.seed,
            },
        }
        if call.schema is not None:
            body["format"] = dict(call.schema)
        payload = self._transport("POST", f"{self.url}/api/chat", body, self.timeout_s)
        message = payload.get("message")
        text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(text, str):
            raise BackendError(f"{self.describe()}: unexpected reply {str(payload)[:DETAIL]}")
        return Completion(
            text, int(payload.get("prompt_eval_count", 0)), int(payload.get("eval_count", 0))
        )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles/test_llm_ollama.py -q`
Expected: PASS.

Run (needs the local Ollama with `llama3.1:8b`): `uv run pytest tests/pericles/test_llm_ollama_contract.py -m slow -q`
Expected: 3 passed. If Ollama is not running in the implementer's environment, report the slow run as not executed. Do not mark it passed. The controller runs it on the user's Mac before the PR.

- [ ] **Step 6: Gates, mutation, commit**

```bash
git add -A
git commit -m "feat(llm): Ollama backend with schema-constrained output, model check and slow contract tests

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The MLX backend

**Files:**
- Modify: `pyproject.toml` (optional extra `mlx`, mypy override, `do_not_mutate`)
- Create: `src/pericles/llm/mlx.py`, `src/pericles/llm/mlx_runtime.py`
- Test: `tests/pericles/test_llm_mlx.py` (unit), `tests/pericles/test_llm_mlx_contract.py` (slow)

**Interfaces:**
- Produces:
  - `MLXRuntime` protocol with `load(name: str) -> object`, `chat_prompt(handle: object, messages: list[dict[str, str]]) -> str`, `count(handle: object, text: str) -> int` and `generate(handle: object, prompt: str, sampling: Sampling, seed: int) -> str`.
  - `MLXBackend(concurrency: int = 1, runtime: MLXRuntime | None = None)` with `kind = "mlx"`.
  - `schema_instruction(schema: Mapping[str, Any]) -> str`.
  - `pericles.llm.mlx_runtime.MlxLmRuntime`.

- [ ] **Step 1: Add the optional dependency and tool config**

In `pyproject.toml`, add after `[project.scripts]`:

```toml
[project.optional-dependencies]
# Apple Silicon only: `uv sync --extra mlx` (REQ-LLM-003; ADR-0017 §3)
mlx = ["mlx-lm>=0.21; sys_platform == 'darwin' and platform_machine == 'arm64'"]
```

Append a mypy override:

```toml
[[tool.mypy.overrides]]
module = ["mlx", "mlx.*", "mlx_lm", "mlx_lm.*"]
ignore_missing_imports = true
```

In `[tool.mutmut]` add:

```toml
# runs only where MLX is installed; covered by the slow MLX contract test
do_not_mutate = ["src/pericles/llm/mlx_runtime.py"]
```

Run: `uv lock && uv sync --extra mlx`
Expected: `mlx-lm` installs on the user's Mac (arm64). On another platform the marker skips it and `uv sync` still succeeds.

- [ ] **Step 2: Write the failing unit tests**

Create `tests/pericles/test_llm_mlx.py`:

```python
import json
from typing import Any

import pytest

from pericles.llm.backend import Backend, BackendError, LLMSetupError
from pericles.llm.mlx import MLXBackend, schema_instruction
from pericles.llm.types import BackendCall, Message, Sampling

SAMPLING = Sampling(0.3, 0.8, 32)


class FakeRuntime:
    def __init__(self, fail_load: str | None = None, fail_generate: bool = False) -> None:
        self.loaded: list[str] = []
        self.prompts: list[list[dict[str, str]]] = []
        self.generated: list[tuple[str, Sampling, int]] = []
        self.fail_load = fail_load
        self.fail_generate = fail_generate

    def load(self, name: str) -> object:
        if name == self.fail_load:
            raise FileNotFoundError(f"no such model {name}")
        self.loaded.append(name)
        return {"name": name}

    def chat_prompt(self, handle: object, messages: list[dict[str, str]]) -> str:
        self.prompts.append(messages)
        return "|".join(m["content"] for m in messages)

    def count(self, handle: object, text: str) -> int:
        return len(text)

    def generate(self, handle: object, prompt: str, sampling: Sampling, seed: int) -> str:
        if self.fail_generate:
            raise RuntimeError("metal out of memory")
        self.generated.append((prompt, sampling, seed))
        return '{"ok": true}'


def call(schema: dict[str, Any] | None = None) -> BackendCall:
    return BackendCall("mlx-community/tiny", (Message("user", "hi"),), SAMPLING, 9, schema)


@pytest.mark.req("REQ-LLM-001")
def test_mlx_implements_the_interface() -> None:
    """AC2: MLXBackend satisfies the Backend protocol."""
    backend: Backend = MLXBackend(runtime=FakeRuntime())
    assert (backend.kind, backend.concurrency, backend.describe()) == ("mlx", 1, "mlx (in-process)")


@pytest.mark.req("REQ-LLM-003")
def test_a_model_is_loaded_once_by_name_or_path() -> None:
    """AC1: loads an MLX model by name or path, and keeps it loaded."""
    runtime = FakeRuntime()
    backend = MLXBackend(runtime=runtime)
    backend.check(["mlx-community/tiny", "/models/local"])
    backend.complete(call())
    assert runtime.loaded == ["mlx-community/tiny", "/models/local"]


@pytest.mark.req("REQ-LLM-003")
def test_complete_passes_sampling_seed_and_counts_tokens() -> None:
    """AC1: sampling and seed reach the runtime; tokens are counted with its tokenizer."""
    runtime = FakeRuntime()
    completion = MLXBackend(runtime=runtime).complete(call())
    assert completion.text == '{"ok": true}'
    assert runtime.generated == [("hi", SAMPLING, 9)]
    assert (completion.tokens_in, completion.tokens_out) == (2, len('{"ok": true}'))


@pytest.mark.req("REQ-LLM-003")
def test_the_schema_goes_into_the_prompt() -> None:
    """AC1: without constrained decoding, the JSON schema is stated in a system message."""
    runtime = FakeRuntime()
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}}
    MLXBackend(runtime=runtime).complete(call(schema))
    sent = runtime.prompts[0]
    assert sent[0] == {"role": "user", "content": "hi"}
    assert sent[1] == {"role": "system", "content": schema_instruction(schema)}
    assert json.dumps(schema, sort_keys=True) in schema_instruction(schema)


@pytest.mark.req("REQ-LLM-003")
def test_load_failures_are_setup_errors() -> None:
    """AC1: a model that cannot be loaded fails fast, naming it."""
    with pytest.raises(LLMSetupError, match="mlx: cannot load model 'gone'"):
        MLXBackend(runtime=FakeRuntime(fail_load="gone")).check(["gone"])


@pytest.mark.req("REQ-LLM-003")
def test_generation_failures_are_backend_errors() -> None:
    """AC1: a runtime failure mid-run is a BackendError, so the gateway backs off."""
    with pytest.raises(BackendError, match="mlx: metal out of memory"):
        MLXBackend(runtime=FakeRuntime(fail_generate=True)).complete(call())


@pytest.mark.req("REQ-LLM-003")
def test_a_missing_mlx_install_says_how_to_install_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: without mlx-lm, check() explains `uv sync --extra mlx`."""
    import pericles.llm.mlx as module

    def missing() -> object:
        raise ImportError("No module named 'mlx_lm'")

    monkeypatch.setattr(module, "default_runtime", missing)
    with pytest.raises(LLMSetupError, match="uv sync --extra mlx"):
        MLXBackend().check(["mlx-community/tiny"])
```

Create `tests/pericles/test_llm_mlx_contract.py`:

```python
"""Contract test against a real MLX model. Run with `uv run pytest -m slow`."""

import os

import pytest
from pydantic import BaseModel, ConfigDict

pytestmark = pytest.mark.slow
pytest.importorskip("mlx_lm")

from pericles.llm.mlx import MLXBackend  # noqa: E402
from pericles.llm.types import BackendCall, Message, Sampling  # noqa: E402
from pericles.llm.validate import schema_of, validate  # noqa: E402

MODEL = os.environ.get("PERICLES_MLX_MODEL", "mlx-community/Qwen2.5-0.5B-Instruct-4bit")


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    colour: str


@pytest.mark.req("REQ-LLM-003")
def test_a_real_model_loads_and_answers_in_json() -> None:
    """AC1: loads by name, implements the interface, output passes JSON validation."""
    backend = MLXBackend()
    backend.check([MODEL])
    completion = backend.complete(
        BackendCall(
            MODEL,
            (Message("user", 'Reply with {"colour": "<a colour>"} and nothing else.'),),
            Sampling(0.0, 1.0, 32),
            3,
            schema_of(Answer),
        )
    )
    value, error = validate(Answer, completion.text)
    assert error is None and isinstance(value, Answer), completion.text
    assert completion.tokens_in > 0 and completion.tokens_out > 0
```

- [ ] **Step 3: Run the unit tests to verify they fail**

Run: `uv run pytest tests/pericles/test_llm_mlx.py -q`
Expected: FAIL on import.

- [ ] **Step 4: Implement**

Create `src/pericles/llm/mlx.py`:

```python
"""MLX in-process backend, Apple Silicon only (REQ-LLM-003; ADR-0017 §3)."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from pericles.llm.backend import BackendError, LLMSetupError
from pericles.llm.types import BackendCall, Completion, Sampling


class MLXRuntime(Protocol):
    def load(self, name: str) -> object: ...

    def chat_prompt(self, handle: object, messages: list[dict[str, str]]) -> str: ...

    def count(self, handle: object, text: str) -> int: ...

    def generate(self, handle: object, prompt: str, sampling: Sampling, seed: int) -> str: ...


def default_runtime() -> MLXRuntime:
    from pericles.llm.mlx_runtime import MlxLmRuntime

    return MlxLmRuntime()


def schema_instruction(schema: Mapping[str, Any]) -> str:
    return (
        "Respond with only a JSON object that matches this JSON schema: "
        + json.dumps(dict(schema), sort_keys=True)
    )


class MLXBackend:
    kind = "mlx"

    def __init__(self, concurrency: int = 1, runtime: MLXRuntime | None = None) -> None:
        self.concurrency = concurrency
        self._runtime = runtime
        self._handles: dict[str, object] = {}
        self._lock = threading.Lock()

    def describe(self) -> str:
        return "mlx (in-process)"

    def _ready(self) -> MLXRuntime:
        if self._runtime is None:
            try:
                self._runtime = default_runtime()
            except ImportError as error:
                raise LLMSetupError(
                    f"mlx: mlx-lm is not installed ({error}); run `uv sync --extra mlx` "
                    "on Apple Silicon"
                ) from None
        return self._runtime

    def _handle(self, name: str) -> object:
        if name not in self._handles:
            self._handles[name] = self._ready().load(name)
        return self._handles[name]

    def check(self, models: Sequence[str]) -> None:
        with self._lock:
            for name in models:
                try:
                    self._handle(name)
                except LLMSetupError:
                    raise
                except Exception as error:
                    raise LLMSetupError(f"mlx: cannot load model {name!r}: {error}") from None

    def complete(self, call: BackendCall) -> Completion:
        messages = [m.to_dict() for m in call.messages]
        if call.schema is not None:
            messages.append({"role": "system", "content": schema_instruction(call.schema)})
        with self._lock:  # MLX runs one generation at a time in-process
            try:
                runtime = self._ready()
                handle = self._handle(call.model)
                prompt = runtime.chat_prompt(handle, messages)
                text = runtime.generate(handle, prompt, call.sampling, call.seed)
                return Completion(text, runtime.count(handle, prompt), runtime.count(handle, text))
            except LLMSetupError:
                raise
            except Exception as error:
                raise BackendError(f"mlx: {error}") from None
```

Create `src/pericles/llm/mlx_runtime.py`:

```python
"""The real mlx-lm runtime (excluded from mutation; see the slow MLX contract test)."""

from __future__ import annotations

from typing import Any, cast

from pericles.llm.types import Sampling

Handle = tuple[Any, Any]  # (model, tokenizer)


class MlxLmRuntime:
    def __init__(self) -> None:
        import mlx.core as mx
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        self._mx: Any = mx
        self._load: Any = load
        self._generate: Any = generate
        self._make_sampler: Any = make_sampler

    def load(self, name: str) -> object:
        model, tokenizer = self._load(name)
        return (model, tokenizer)

    def chat_prompt(self, handle: object, messages: list[dict[str, str]]) -> str:
        _, tokenizer = cast(Handle, handle)
        return str(
            tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        )

    def count(self, handle: object, text: str) -> int:
        _, tokenizer = cast(Handle, handle)
        return len(tokenizer.encode(text))

    def generate(self, handle: object, prompt: str, sampling: Sampling, seed: int) -> str:
        model, tokenizer = cast(Handle, handle)
        self._mx.random.seed(seed)
        sampler = self._make_sampler(temp=sampling.temperature, top_p=sampling.top_p)
        return str(
            self._generate(
                model, tokenizer, prompt=prompt, max_tokens=sampling.max_tokens, sampler=sampler
            )
        )
```

The boundary test from Task 2 allows `mlx` and `mlx_lm` only in `llm/mlx_runtime.py`. `mlx.py` imports `pericles.llm.mlx_runtime` lazily, which is allowed.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/pericles/test_llm_mlx.py tests/pericles/test_core_boundaries.py -q`
Expected: PASS.

Run on the user's Mac (downloads ~300 MB the first time): `uv run pytest tests/pericles/test_llm_mlx_contract.py -m slow -q`
Expected: 1 passed. Elsewhere it is skipped because `mlx_lm` is missing. Report which happened.

- [ ] **Step 6: Gates, mutation, commit**

```bash
git add -A
git commit -m "feat(llm): MLX backend as an optional Apple Silicon extra, schema in the prompt

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `LLMConfig` and the `llm:` settings section

**Files:**
- Create: `src/pericles/llm/config.py`
- Modify: `src/pericles/experiment/settings.py`, `src/pericles/experiment/defaults.py`, `src/pericles/experiment/default_settings.yaml`
- Test: `tests/pericles/test_llm_config.py`, `tests/pericles/test_settings.py`

**Interfaces:**
- Consumes: `ModelSpec`, `Sampling` (Task 2), `CACHE_MODES` (Task 3), `MODES` (Task 5).
- Produces:
  - `pericles.llm.config.BACKEND_KINDS = ("ollama", "mlx", "fake")`.
  - `BackendSpec(kind: str, concurrency: int, timeout_s: float, url: str | None = None, replies: str | None = None)`.
  - `LLMConfig`, with the fields shown below.
  - `pericles.experiment.settings.llm_config_from_mapping(data: object, where: str = "llm") -> LLMConfig`.
  - `llm_config_to_mapping(config: LLMConfig) -> dict[str, Any]`.
  - `load_llm_settings(path: Path) -> LLMConfig`.
  - `SECTIONS = ("engine", "agents", "llm")`.
  - `pericles.experiment.defaults.default_llm_config(**overrides) -> LLMConfig`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_llm_config.py`:

```python
import math
from dataclasses import replace

import pytest

from pericles.llm.config import BACKEND_KINDS, BackendSpec, LLMConfig
from pericles.llm.types import ModelSpec, Sampling

OLLAMA = BackendSpec("ollama", 1, 300.0, url="http://localhost:11434")
QWEN = ModelSpec("local", "qwen3:latest", Sampling(0.7, 0.9, 512))


def config(**changes: object) -> LLMConfig:
    values: dict[str, object] = {
        "backends": {"local": OLLAMA},
        "models": {"qwen": QWEN},
        "assign": {"qwen": 1.0},
    }
    values.update(changes)
    return replace(LLMConfig(), **values)  # type: ignore[arg-type]


@pytest.mark.req("REQ-LLM-006")
def test_a_complete_config_is_valid_and_frozen() -> None:
    """AC1: backends, models with sampling, and an assignment split."""
    made = config()
    assert made.models["qwen"].sampling.temperature == 0.7
    assert BACKEND_KINDS == ("ollama", "mlx", "fake")
    with pytest.raises(TypeError):
        made.models["other"] = QWEN  # type: ignore[index]


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"mode": "fast"}, "mode must be one of"),
        ({"cache": "always"}, "cache must be one of"),
        ({"cache": "replay"}, "cache 'replay' needs cache_from"),
        ({"backoff_base_s": 0.0}, "backoff_base_s must be positive"),
        ({"backoff_factor": 0.5}, "backoff_factor must be at least 1"),
        ({"backoff_max_s": 0.5}, "backoff_max_s must be at least backoff_base_s"),
        ({"max_backend_failures": 0}, "max_backend_failures must be at least 1"),
        ({"temperature": -0.1}, "temperature must be finite and non-negative"),
        ({"temperature": math.nan}, "temperature must be finite and non-negative"),
        ({"top_p": 0.0}, "top_p must be in"),
        ({"top_p": 1.5}, "top_p must be in"),
        ({"max_tokens": 0}, "max_tokens must be at least 1"),
        ({"concurrency": 0}, "concurrency must be at least 1"),
        ({"timeout_s": 0.0}, "timeout_s must be positive"),
        ({"backends": {"local": BackendSpec("vllm", 1, 1.0)}}, "backends.local.kind: must be one of"),
        ({"backends": {"local": BackendSpec("ollama", 1, 1.0)}}, "backends.local.url: an ollama backend needs a url"),
        ({"backends": {"local": BackendSpec("fake", 0, 1.0)}}, "backends.local.concurrency: must be at least 1"),
        ({"backends": {"local": BackendSpec("fake", 1, 0.0)}}, "backends.local.timeout_s: must be positive"),
        ({"models": {"qwen": replace(QWEN, backend="cloud")}}, "models.qwen.backend: unknown backend 'cloud'"),
        ({"models": {"qwen": replace(QWEN, sampling=Sampling(0.7, 0.9, 0))}}, "models.qwen.max_tokens: must be at least 1"),
        ({"models": {"qwen": replace(QWEN, sampling=Sampling(-1.0, 0.9, 5))}}, "models.qwen.temperature"),
        ({"models": {"qwen": replace(QWEN, sampling=Sampling(0.5, 2.0, 5))}}, "models.qwen.top_p"),
        ({"assign": {"llama": 1.0}}, "assign.llama: unknown model"),
        ({"assign": {"qwen": 0.0}}, "assign.qwen: ratio must be finite and positive"),
        ({"assign": {"qwen": math.inf}}, "assign.qwen: ratio must be finite and positive"),
    ],
)
def test_invalid_configs_name_the_field(changes: dict[str, object], message: str) -> None:
    """AC1: every part of the model configuration is checked."""
    with pytest.raises(ValueError, match=message):
        config(**changes)
```

Append to `tests/pericles/test_settings.py` (it already has helpers that write a settings file to `tmp_path`; use `Path.write_text` directly if not):

```python
@pytest.mark.req("REQ-LLM-006")
def test_llm_section_loads_backends_models_and_assignment(tmp_path: Path) -> None:
    """AC1: models take per-model sampling and fall back to the section defaults."""
    path = tmp_path / "settings.yaml"
    path.write_text(
        "llm:\n"
        "  temperature: 0.5\n"
        "  backends:\n"
        "    local: {kind: ollama}\n"
        "    test: {kind: fake, concurrency: 3, replies: replies.yaml}\n"
        "  models:\n"
        "    qwen: {backend: local, name: 'qwen3:latest', top_p: 0.8}\n"
        "    fake: {backend: test, name: echo, temperature: 0, max_tokens: 16}\n"
        "  assign: {qwen: 2, fake: 1}\n",
        encoding="utf-8",
    )
    llm = load_llm_settings(path)
    assert llm.backends["local"] == BackendSpec("ollama", 1, 300.0, url="http://localhost:11434")
    assert llm.backends["test"] == BackendSpec("fake", 3, 300.0, replies="replies.yaml")
    assert llm.models["qwen"] == ModelSpec("local", "qwen3:latest", Sampling(0.5, 0.8, 512))
    assert llm.models["fake"] == ModelSpec("test", "echo", Sampling(0.0, 0.9, 16))
    assert dict(llm.assign) == {"qwen": 2.0, "fake": 1.0}


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("llm: {colour: red}\n", r"^llm\.colour: unknown setting"),
        ("llm: {backends: {local: {kind: ollama, port: 1}}}\n", r"^llm\.backends\.local\.port: unknown setting"),
        ("llm: {backends: {local: {}}}\n", r"^llm\.backends\.local\.kind: missing"),
        ("llm: {backends: [1]}\n", r"^llm\.backends: expected a mapping"),
        ("llm: {models: {q: {backend: x}}}\n", r"^llm\.models\.q\.name: missing"),
        ("llm: {assign: {q: high}}\n", r"^llm\.assign\.q: expected a number"),
        ("llm: {assign: {q: true}}\n", r"^llm\.assign\.q: expected a number"),
        ("llm: {models: {q: {backend: x, name: n}}}\n", r"^llm: models\.q\.backend: unknown backend 'x'"),
    ],
)
def test_llm_settings_errors_name_the_field(tmp_path: Path, text: str, message: str) -> None:
    """AC1: configuration errors start with the dotted path."""
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(SettingsError, match=message):
        load_llm_settings(path)


@pytest.mark.req("REQ-LLM-006")
def test_llm_config_round_trips_through_its_mapping() -> None:
    """AC1: the resolved config can be read back."""
    llm = replace(
        default_llm_config(),
        backends={"t": BackendSpec("fake", 1, 5.0)},
        models={"m": ModelSpec("t", "echo", Sampling(0.1, 0.5, 8))},
        assign={"m": 1.0},
    )
    assert llm_config_from_mapping(llm_config_to_mapping(llm)) == llm


def test_default_settings_list_every_llm_parameter() -> None:
    """No magic values: the packaged file names every LLMConfig field."""
    section = default_settings_mapping()["llm"]
    assert set(section) == {f.name for f in dataclasses.fields(LLMConfig)}
    assert default_llm_config() == LLMConfig()
```

Add the imports these tests need at the top of `tests/pericles/test_settings.py`: `import dataclasses`, `from dataclasses import replace`, `from pericles.llm.config import BackendSpec, LLMConfig`, `from pericles.llm.types import ModelSpec, Sampling`, `from pericles.experiment.settings import llm_config_from_mapping, llm_config_to_mapping, load_llm_settings` (next to the existing settings imports), and `from pericles.experiment.defaults import default_llm_config, default_settings_mapping`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_llm_config.py tests/pericles/test_settings.py -q`
Expected: FAIL on import.

- [ ] **Step 3: Implement `LLMConfig`**

Create `src/pericles/llm/config.py`:

```python
"""Gateway configuration: modes, backends, models, assignment (ADR-0017 §9)."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from pericles.llm.cache import CACHE_MODES
from pericles.llm.gateway import MODES
from pericles.llm.types import ModelSpec, Sampling

BACKEND_KINDS = ("ollama", "mlx", "fake")


@dataclass(frozen=True)
class BackendSpec:
    kind: str
    concurrency: int
    timeout_s: float
    url: str | None = None
    replies: str | None = None


def _sampling_errors(where: str, s: Sampling) -> list[str]:
    errors = []
    if not (math.isfinite(s.temperature) and s.temperature >= 0):
        errors.append(f"{where}temperature must be finite and non-negative")
    if not 0 < s.top_p <= 1:
        errors.append(f"{where}top_p must be in (0, 1]")
    if s.max_tokens < 1:
        errors.append(f"{where}max_tokens must be at least 1")
    return errors


@dataclass(frozen=True)
class LLMConfig:
    mode: str = "wait"
    cache: str = "record"
    cache_from: str | None = None
    backoff_base_s: float = 2.0
    backoff_factor: float = 2.0
    backoff_max_s: float = 60.0
    max_backend_failures: int = 5
    temperature: float = 0.7
    top_p: float = 0.9
    max_tokens: int = 512
    concurrency: int = 1
    timeout_s: float = 300.0
    ollama_url: str = "http://localhost:11434"
    backends: Mapping[str, BackendSpec] = field(default_factory=dict)
    models: Mapping[str, ModelSpec] = field(default_factory=dict)
    assign: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for name in ("backends", "models", "assign"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        errors = self._errors()
        if errors:
            raise ValueError(errors[0])

    def _errors(self) -> list[str]:
        errors: list[str] = []
        if self.mode not in MODES:
            errors.append(f"mode must be one of {MODES}")
        if self.cache not in CACHE_MODES:
            errors.append(f"cache must be one of {CACHE_MODES}")
        if self.cache == "replay" and self.cache_from is None:
            errors.append("cache 'replay' needs cache_from")
        if self.backoff_base_s <= 0:
            errors.append("backoff_base_s must be positive")
        if self.backoff_factor < 1:
            errors.append("backoff_factor must be at least 1")
        if self.backoff_max_s < self.backoff_base_s:
            errors.append("backoff_max_s must be at least backoff_base_s")
        if self.max_backend_failures < 1:
            errors.append("max_backend_failures must be at least 1")
        errors += _sampling_errors("", Sampling(self.temperature, self.top_p, self.max_tokens))
        if self.concurrency < 1:
            errors.append("concurrency must be at least 1")
        if self.timeout_s <= 0:
            errors.append("timeout_s must be positive")
        for key in sorted(self.backends):
            b = self.backends[key]
            if b.kind not in BACKEND_KINDS:
                errors.append(f"backends.{key}.kind: must be one of {BACKEND_KINDS}")
            if b.kind == "ollama" and not b.url:
                errors.append(f"backends.{key}.url: an ollama backend needs a url")
            if b.concurrency < 1:
                errors.append(f"backends.{key}.concurrency: must be at least 1")
            if b.timeout_s <= 0:
                errors.append(f"backends.{key}.timeout_s: must be positive")
        for key in sorted(self.models):
            m = self.models[key]
            if m.backend not in self.backends:
                errors.append(f"models.{key}.backend: unknown backend {m.backend!r}")
            errors += [
                e.replace(" must", ": must", 1)
                for e in _sampling_errors(f"models.{key}.", m.sampling)
            ]
        for key in sorted(self.assign):
            if key not in self.models:
                errors.append(f"assign.{key}: unknown model")
            elif not (math.isfinite(self.assign[key]) and self.assign[key] > 0):
                errors.append(f"assign.{key}: ratio must be finite and positive")
        return errors
```

`pericles.llm.config` importing `pericles.llm.gateway` for `MODES` is inside `pericles.llm`, so the boundary test allows it.

- [ ] **Step 4: Implement the settings section**

`src/pericles/experiment/default_settings.yaml`, add a new top-level section after `agents:`:

```yaml
# LLM gateway (ADR-0017 §9). An experiment adds backends, models and assign.
llm:
  mode: wait                  # wait: the tick waits for every decision; live: fall back on failure
  cache: record               # off | record | replay
  cache_from: null            # replay: a run directory, its llm_cache directory, or responses.sqlite
  backoff_base_s: 2.0
  backoff_factor: 2.0
  backoff_max_s: 60.0
  max_backend_failures: 5
  temperature: 0.7            # default sampling for models that do not set their own
  top_p: 0.9
  max_tokens: 512
  concurrency: 1              # default calls in flight per backend
  timeout_s: 300.0
  ollama_url: http://localhost:11434
  backends: {}
  models: {}
  assign: {}
```

`src/pericles/experiment/settings.py`: set `SECTIONS = ("engine", "agents", "llm")` and add:

```python
import math

from pericles.llm.config import BackendSpec, LLMConfig
from pericles.llm.types import ModelSpec, Sampling

LLM_NESTED = {"backends", "models", "assign"}


@dataclasses.dataclass(frozen=True)
class _BackendEntry:
    kind: str
    concurrency: int | None = None
    timeout_s: float | None = None
    url: str | None = None
    replies: str | None = None


@dataclasses.dataclass(frozen=True)
class _ModelEntry:
    backend: str
    name: str
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None


def _or(value: Any, default: Any) -> Any:
    return default if value is None else value


def llm_config_from_mapping(data: object, where: str = "llm") -> LLMConfig:
    llm = as_mapping(data, where)
    values = values_for(LLMConfig, llm, where, nested=LLM_NESTED)
    try:
        base = LLMConfig(**values)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None
    backends: dict[str, BackendSpec] = {}
    raw_backends = as_mapping(llm.get("backends", {}), f"{where}.backends")
    for key in sorted(raw_backends):
        at = f"{where}.backends.{key}"
        b = _BackendEntry(**values_for(_BackendEntry, as_mapping(raw_backends[key], at), at, set()))
        url = _or(b.url, base.ollama_url if b.kind == "ollama" else None)
        backends[key] = BackendSpec(
            b.kind, _or(b.concurrency, base.concurrency), _or(b.timeout_s, base.timeout_s), url, b.replies
        )
    models: dict[str, ModelSpec] = {}
    raw_models = as_mapping(llm.get("models", {}), f"{where}.models")
    for key in sorted(raw_models):
        at = f"{where}.models.{key}"
        m = _ModelEntry(**values_for(_ModelEntry, as_mapping(raw_models[key], at), at, set()))
        sampling = Sampling(
            float(_or(m.temperature, base.temperature)),
            float(_or(m.top_p, base.top_p)),
            int(_or(m.max_tokens, base.max_tokens)),
        )
        models[key] = ModelSpec(m.backend, m.name, sampling)
    assign: dict[str, float] = {}
    raw_assign = as_mapping(llm.get("assign", {}), f"{where}.assign")
    for key in sorted(raw_assign):
        ratio = raw_assign[key]
        if isinstance(ratio, bool) or not isinstance(ratio, int | float):
            raise SettingsError(f"{where}.assign.{key}: expected a number")
        assign[key] = float(ratio)
    try:
        return dataclasses.replace(base, backends=backends, models=models, assign=assign)
    except ValueError as error:
        raise SettingsError(f"{where}: {error}") from None


def llm_config_to_mapping(config: LLMConfig) -> dict[str, Any]:
    """Every value of `config`, in the shape `llm_config_from_mapping` reads."""
    out: dict[str, Any] = {
        f.name: getattr(config, f.name)
        for f in dataclasses.fields(LLMConfig)
        if f.name not in LLM_NESTED
    }
    out["backends"] = {k: dataclasses.asdict(v) for k, v in sorted(config.backends.items())}
    out["models"] = {
        k: {"backend": m.backend, "name": m.name, **m.sampling.to_dict()}
        for k, m in sorted(config.models.items())
    }
    out["assign"] = dict(sorted(config.assign.items()))
    return out


def load_llm_settings(path: Path) -> LLMConfig:
    return llm_config_from_mapping(_read(path).get("llm", {}))
```

`math` is imported only if the implementer needs it for a check. Remove the import if ruff flags it as unused. `values_for` validates `_ModelEntry.temperature: float | None` strictly. An integer such as `temperature: 0` passes, because pydantic's strict float accepts ints. If it does not in the installed pydantic, change the annotation to `float | int | None` and record that in the report.

`src/pericles/experiment/defaults.py`:

```python
from pericles.llm.config import LLMConfig
from pericles.experiment.settings import load_llm_settings  # extend the existing import


def default_llm_config(**overrides: Any) -> LLMConfig:
    return dataclasses.replace(load_llm_settings(DEFAULT_SETTINGS), **overrides)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS, all tests. The experiment loader still ignores `llm` until Task 9.

- [ ] **Step 6: Gates, mutation, commit**

```bash
git add -A
git commit -m "feat(llm): LLMConfig and the llm settings section with per-model sampling

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The `llm:` experiment section and model assignment

**Files:**
- Create: `src/pericles/experiment/models.py`
- Modify: `src/pericles/experiment/config.py`
- Test: `tests/pericles/test_model_assignment.py`, `tests/pericles/test_experiment_config.py`

**Interfaces:**
- Consumes:
  - `LLMConfig`, `llm_config_from_mapping` and `llm_config_to_mapping` (Task 8).
  - `merged` (Task 1).
- Produces:
  - `pericles.experiment.models.quotas(n: int, ratios: Mapping[str, float]) -> dict[str, int]`.
  - `assign_models(specs: Sequence[VillagerSpec], adult_age_days: int, ratios: Mapping[str, float], seed: int) -> tuple[VillagerSpec, ...]`.
  - `Experiment.llm: LLMConfig`, a new field placed *after* `agents` and *before* `registry`.
  - `"llm"` in `SECTIONS`.
  - `resolved["llm"]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_model_assignment.py`:

```python
import pytest

from pericles.experiment.config import VillagerSpec
from pericles.experiment.models import assign_models, quotas


def villager(vid: str, age: int = 200, model: str | None = None) -> VillagerSpec:
    return VillagerSpec(id=vid, name=vid.upper(), age_days=age, model=model)


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize(
    ("n", "ratios", "expected"),
    [
        (10, {"a": 1.0, "b": 1.0}, {"a": 5, "b": 5}),
        (7, {"a": 1.0, "b": 1.0}, {"a": 4, "b": 3}),
        (10, {"a": 0.7, "b": 0.3}, {"a": 7, "b": 3}),
        (5, {"a": 1.0, "b": 1.0, "c": 1.0}, {"a": 2, "b": 2, "c": 1}),
        (3, {"b": 2.0, "a": 1.0}, {"a": 1, "b": 2}),
        (0, {"a": 1.0}, {"a": 0}),
    ],
)
def test_quotas_use_the_largest_remainder(n: int, ratios: dict[str, float], expected: dict[str, int]) -> None:
    """AC1: groups are split by ratio with exact counts; ties go to the model key."""
    assert quotas(n, ratios) == expected


@pytest.mark.req("REQ-LLM-006")
def test_unpinned_adults_are_split_by_ratio_with_the_seed() -> None:
    """AC1: pins are kept; children get nothing; the split is seeded and exact."""
    specs = [villager(f"v{i}") for i in range(8)] + [villager("kid", age=5), villager("pin", model="b")]
    one = assign_models(specs, 120, {"a": 3.0, "b": 1.0}, seed=1)
    again = assign_models(specs, 120, {"a": 3.0, "b": 1.0}, seed=1)
    other = assign_models(specs, 120, {"a": 3.0, "b": 1.0}, seed=2)
    models = {s.id: s.model for s in one}
    assert one == again
    assert models["kid"] is None and models["pin"] == "b"
    adults = [models[f"v{i}"] for i in range(8)]
    assert adults.count("a") == 6 and adults.count("b") == 2
    assert [s.id for s in one] == [s.id for s in specs]
    assert {s.id: s.model for s in other} != models


@pytest.mark.req("REQ-LLM-006")
def test_no_ratios_assign_nothing() -> None:
    """AC1: without `assign`, unpinned villagers keep no model (scripted)."""
    specs = (villager("a"), villager("b", model="m"))
    assert assign_models(specs, 120, {}, seed=1) == specs
```

Append to `tests/pericles/test_experiment_config.py`. Also update `MINIMAL` so that villager `b`'s `"model": "m"` names a defined model: add this key to `MINIMAL` (after `"run"`):

```python
    "llm": {
        "backends": {"test": {"kind": "fake"}},
        "models": {"m": {"backend": "test", "name": "fake-m"}},
    },
```

Then add:

```python
@pytest.mark.req("REQ-LLM-006")
def test_the_llm_section_assigns_models_and_is_resolved(tmp_path: Path) -> None:
    """AC1: pinned villagers keep their model; the split is recorded in the resolved config."""
    data = changed("llm.assign", {"m": 1.0})
    data["population"].append(
        {"id": "c", "name": "C", "sex": "male", "age_days": 300}
    )
    experiment = experiment_from_mapping(data, tmp_path)
    models = {spec.id: spec.model for spec in experiment.population}
    assert models == {"a": "m", "b": "m", "c": "m"}
    assert experiment.llm.models["m"].name == "fake-m"
    resolved = experiment.resolved
    assert [p.get("model") for p in resolved["population"]] == ["m", "m", "m"]
    assert resolved["llm"]["models"]["m"]["temperature"] == 0.7
    again = experiment_from_mapping(resolved, tmp_path)
    assert again.population == experiment.population and again.llm == experiment.llm


@pytest.mark.req("REQ-LLM-006")
def test_paths_in_the_llm_section_resolve_against_the_experiment(tmp_path: Path) -> None:
    """AC1: fake replies and cache_from are stored as absolute paths."""
    data = changed("llm.backends.test", {"kind": "fake", "replies": "replies.yaml"})
    data["llm"]["cache"] = "replay"
    data["llm"]["cache_from"] = "old-run"
    experiment = experiment_from_mapping(data, tmp_path)
    assert experiment.llm.backends["test"].replies == str((tmp_path / "replies.yaml").resolve())
    assert experiment.llm.cache_from == str((tmp_path / "old-run").resolve())


@pytest.mark.req("REQ-LLM-006")
@pytest.mark.parametrize(
    ("path", "value", "prefix"),
    [
        ("population.1.model", "ghost", r"population\[1\]\.model: unknown model 'ghost'"),
        ("engine", {"model_rule": "fixed", "adult_model": "ghost"}, r"engine\.adult_model: unknown model 'ghost'"),
        ("llm.models.m.backend", "nowhere", r"llm: models\.m\.backend: unknown backend"),
        ("llm.assign", {"ghost": 1.0}, r"llm: assign\.ghost: unknown model"),
        ("llm.colour", "red", r"llm\.colour: unknown setting"),
    ],
)
def test_model_errors_name_the_field(tmp_path: Path, path: str, value: object, prefix: str) -> None:
    """AC1: an undefined model or backend is a field error."""
    with pytest.raises(ExperimentError, match=f"^{prefix}"):
        experiment_from_mapping(changed(path, value), tmp_path)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_model_assignment.py tests/pericles/test_experiment_config.py -q`
Expected: FAIL (`pericles.experiment.models` missing, `llm: unknown section`).

- [ ] **Step 3: Implement**

Create `src/pericles/experiment/models.py`:

```python
"""Assign models to villagers: pins first, then a seeded ratio split (REQ-LLM-006; ADR-0017 §10)."""

from __future__ import annotations

import random
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pericles.experiment.config import VillagerSpec


def quotas(n: int, ratios: Mapping[str, float]) -> dict[str, int]:
    """Exact counts summing to `n`, by the largest remainder; ties go to the model key."""
    total = sum(ratios.values())
    exact = {m: n * r / total for m, r in ratios.items()}
    counts = {m: int(v) for m, v in exact.items()}
    left = n - sum(counts.values())
    for m in sorted(exact, key=lambda m: (-(exact[m] - counts[m]), m))[:left]:
        counts[m] += 1
    return dict(sorted(counts.items()))


def assign_models(
    specs: Sequence[VillagerSpec], adult_age_days: int, ratios: Mapping[str, float], seed: int
) -> tuple[VillagerSpec, ...]:
    if not ratios:
        return tuple(specs)
    free = sorted(s.id for s in specs if s.model is None and s.age_days >= adult_age_days)
    random.Random(f"pericles-models:{seed}").shuffle(free)
    order = [m for m, count in quotas(len(free), ratios).items() for _ in range(count)]
    chosen = dict(zip(free, order, strict=True))
    return tuple(
        s.model_copy(update={"model": chosen[s.id]}) if s.id in chosen else s for s in specs
    )
```

`src/pericles/experiment/config.py`:

1. `SECTIONS = ("seed", "packs", "map", "population", "run", "engine", "agents", "llm")`.
2. Import `LLMConfig`, `llm_config_from_mapping`, `llm_config_to_mapping` and `assign_models`, plus `dataclasses` if Task 1 did not already.
3. Add `llm: LLMConfig` to `Experiment` between `agents` and `registry`, and pass it positionally in the constructor call.
4. Add helpers:

```python
def _llm_paths(llm: LLMConfig, base_dir: Path) -> LLMConfig:
    """Fake replies and cache_from resolve against the experiment file (ADR-0017 §9)."""

    def absolute(path: str | None) -> str | None:
        return None if path is None else str((base_dir / path).resolve())

    backends = {
        key: dataclasses.replace(spec, replies=absolute(spec.replies))
        for key, spec in llm.backends.items()
    }
    return dataclasses.replace(llm, backends=backends, cache_from=absolute(llm.cache_from))


def _check_models(
    population: Sequence[VillagerSpec], engine: EngineConfig, llm: LLMConfig
) -> None:
    for i, spec in enumerate(population):
        if spec.model is not None and spec.model not in llm.models:
            raise ExperimentError(
                f"population[{i}].model: unknown model {spec.model!r}; define it under llm.models"
            )
    if engine.adult_model is not None and engine.adult_model not in llm.models:
        raise ExperimentError(
            f"engine.adult_model: unknown model {engine.adult_model!r}; define it under llm.models"
        )
```

5. In `experiment_from_mapping`, inside the existing `try`, after `agents = …`:

```python
        llm = _llm_paths(llm_config_from_mapping(merged("llm", raw.get("llm")), "llm"), base_dir)
```

After `population = _population(...)`:

```python
        _check_models(population, engine, llm)
        population = assign_models(population, engine.adult_age_days, llm.assign, seed)
```

Add `"llm": llm_config_to_mapping(llm)` to `resolved`. The `population` entry of `resolved` is built from the assigned `population`, so the split is recorded.

`base_dir / path` with an absolute `path` gives `path`, so reloading a resolved config keeps the paths.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS, all tests. `experiments/baseline.yaml` has no `llm:` and no `model:`, so it loads with the defaults and stays all-scripted.

- [ ] **Step 5: Gates, mutation, commit**

```bash
git add -A
git commit -m "feat(experiment): llm section, model pins and a seeded ratio split recorded in the resolved config

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Runs with the gateway — fail fast, replay, clean stop

**Files:**
- Create: `src/pericles/experiment/llm.py`
- Modify: `src/pericles/experiment/rundir.py`, `src/pericles/experiment/launch.py`, `src/pericles/experiment/cli.py`
- Test: `tests/pericles/test_llm_runs.py`, `tests/pericles/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `CACHE_FILE = "responses.sqlite"` and `CALLS_FILE = "llm_calls.sqlite"`.
  - `build_backends(config: LLMConfig) -> dict[str, Backend]`.
  - `policy_of(config: LLMConfig) -> FailurePolicy`.
  - `replay_source(path: Path) -> Path`.
  - `open_gateway(config: LLMConfig, backends: Mapping[str, Backend], run_dir: RunDirectory) -> Gateway`.
  - `run_meta(config: LLMConfig) -> dict[str, Any]`.
  - `Session.gateway: Gateway` and `Session.close()`.
  - `RunDirectory.create(path, config, seed, extra: Mapping[str, Any] | None = None)`.
  - `cli.EXIT_BACKEND = 3`.

- [ ] **Step 1: Write the failing tests**

Create `tests/pericles/test_llm_runs.py`:

```python
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from pericles.core.content.registry import Registry
from pericles.core.engine import Engine
from pericles.core.events import Event
from pericles.core.geometry import Coord
from pericles.core.intents import Intent, MoveTo
from pericles.core.mapgen import TileMap
from pericles.core.state import Villager, WorldState
from pericles.experiment.defaults import default_config
from pericles.experiment.llm import CACHE_FILE, CALLS_FILE, open_gateway, replay_source
from pericles.experiment.rundir import RunDirectory
from pericles.experiment.runner import resume, run
from pericles.llm.backend import Backend, LLMSetupError
from pericles.llm.config import BackendSpec, LLMConfig
from pericles.llm.fake import FakeBackend, FakeError, FakeRule
from pericles.llm.gateway import BackendUnavailable, Gateway
from pericles.llm.types import Message, ModelSpec, Request, Sampling


class Probe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pick: int


class ProbeAgents:
    """Test agents: every 7 ticks each villager asks the gateway where to walk."""

    def __init__(self, gateway: Gateway, walkable: list[Coord]) -> None:
        self.gateway = gateway
        self.walkable = walkable

    def intents(self, state: WorldState) -> Sequence[Intent]:
        if state.tick % 7:
            return []
        ids = sorted(state.villagers)
        requests = [
            Request("probe", v, state.tick, "m", (Message("user", f"{v} at {state.tick}"),), state.tick, Probe)
            for v in ids
        ]
        results = self.gateway.complete_all(requests)
        return [
            MoveTo(v, self.walkable[r.value.pick % len(self.walkable)])
            for v, r in zip(ids, results, strict=True)
            if isinstance(r.value, Probe)
        ]

    def observe(self, state: WorldState, events: Sequence[Event]) -> None:
        return None

    def to_dict(self) -> dict[str, Any]:
        return {}


def setup(small_map: TileMap, registry: Registry) -> tuple[WorldState, list[Coord]]:
    walkable = [
        Coord(x, y)
        for y in range(small_map.height)
        for x in range(small_map.width)
        if registry.terrains[small_map.terrain_at(Coord(x, y))].walkable
    ]
    villagers = [Villager(f"v{i}", f"V{i}", small_map.start(), model="m") for i in range(3)]
    return WorldState.new(5, small_map, villagers), walkable


def config(cache: str, cache_from: Path | None = None) -> LLMConfig:
    return LLMConfig(
        cache=cache,
        cache_from=None if cache_from is None else str(cache_from),
        backoff_base_s=0.001,
        backoff_max_s=0.001,
        max_backend_failures=2,
        backends={"test": BackendSpec("fake", 1, 1.0)},
        models={"m": ModelSpec("test", "fake-m", Sampling(0.7, 0.9, 16))},
    )


def drive(
    path: Path, llm: LLMConfig, backend: Backend, small_map: TileMap, registry: Registry, until: int = 30
) -> RunDirectory:
    state, walkable = setup(small_map, registry)
    run_dir = RunDirectory.create(path, {}, seed=5)
    gateway = open_gateway(llm, {"test": backend}, run_dir)
    try:
        run(run_dir, Engine(registry, default_config()), state, ProbeAgents(gateway, walkable), until, 10)
    finally:
        gateway.close()
    return run_dir


@pytest.mark.req("REQ-LLM-005")
def test_a_replayed_run_has_the_same_event_digest(
    tmp_path: Path, small_map: TileMap, registry: Registry
) -> None:
    """LLM-005 AC3: replay mode reproduces the event log without any backend call."""
    picks = tuple(f'{{"pick": {n * 37}}}' for n in range(40))
    recorded = drive(tmp_path / "rec", config("record"), FakeBackend([FakeRule(picks)]), small_map, registry)
    silent = FakeBackend()
    replayed = drive(
        tmp_path / "rep", config("replay", tmp_path / "rec"), silent, small_map, registry
    )
    assert silent.calls == []
    assert replayed.event_log.digest() == recorded.event_log.digest()
    assert (tmp_path / "rep" / "llm_cache" / CACHE_FILE).exists()
    recorded.close()
    replayed.close()


@pytest.mark.req("REQ-LLM-005")
def test_replay_source_accepts_a_run_its_cache_dir_or_the_file(tmp_path: Path) -> None:
    """AC2: cache_from may point at the run, its llm_cache, or responses.sqlite."""
    cache = tmp_path / "run" / "llm_cache"
    cache.mkdir(parents=True)
    (cache / CACHE_FILE).write_bytes(b"")
    for given in (tmp_path / "run", cache, cache / CACHE_FILE):
        assert replay_source(given) == cache / CACHE_FILE
    with pytest.raises(LLMSetupError, match="llm.cache_from: no responses.sqlite"):
        replay_source(tmp_path / "nowhere")


@pytest.mark.req("REQ-LLM-009")
def test_a_backend_that_stays_down_stops_the_run_cleanly_and_it_resumes(
    tmp_path: Path, small_map: TileMap, registry: Registry
) -> None:
    """AC1: after max_backend_failures the run stops at a tick boundary and can be resumed."""
    engine = Engine(registry, default_config())
    state, walkable = setup(small_map, registry)
    run_dir = RunDirectory.create(tmp_path / "run", {}, seed=5)
    # Tick 0: three good replies (one per villager). Tick 7: every call fails twice -> stop.
    flaky = FakeBackend([FakeRule(('{"pick": 1}', '{"pick": 2}', '{"pick": 3}', FakeError("down")))])
    gateway = open_gateway(config("record"), {"test": flaky}, run_dir)
    with pytest.raises(BackendUnavailable, match="2 failures in a row"):
        run(run_dir, engine, state, ProbeAgents(gateway, walkable), 30, 10)
    gateway.close()
    assert run_dir.event_log.last_tick() == 6  # ticks 0-6 are whole; tick 7 never stepped
    assert gateway.calls is not None
    restored, _ = resume(run_dir)
    assert restored.tick == 0  # the only snapshot is tick 0
    healthy = FakeBackend([FakeRule(('{"pick": 4}',))])
    gateway = open_gateway(config("record"), {"test": healthy}, run_dir)
    assert gateway.calls is not None
    gateway.calls.truncate_after(restored.tick - 1)
    run(run_dir, engine, restored, ProbeAgents(gateway, walkable), 30, 10)
    assert run_dir.event_log.last_tick() == 29
    assert all(r.tick >= restored.tick for r in gateway.calls.records())
    assert (tmp_path / "run" / CALLS_FILE).exists()
    gateway.close()
    run_dir.close()
```

The schedule is as follows. Calls happen every 7 ticks, three villagers each. The rule serves its three good replies at tick 0, and from then on repeats `FakeError("down")`. At tick 7 the first call fails twice (`max_backend_failures=2`), so the gateway logs the rows and raises before `engine.step` runs for tick 7. The event log therefore ends at tick 6, and the only snapshot (taken every 10 ticks) is tick 0. The gateway closing its call log before `resume` is deliberate: the second gateway opens the same `llm_calls.sqlite` again.

Append to `tests/pericles/test_cli.py`. It runs `main([...])` and reads `capsys`. Use its existing baseline helpers to write an experiment file:

```python
@pytest.mark.req("REQ-LLM-002")
def test_a_missing_model_fails_fast_and_leaves_no_run_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """AC1: the model check runs before the run directory is created."""
    data = yaml.safe_load(BASELINE.read_text(encoding="utf-8"))
    data["llm"] = {
        "backends": {"local": {"kind": "ollama", "url": "http://127.0.0.1:9"}},
        "models": {"q": {"backend": "local", "name": "qwen3"}},
        "assign": {"q": 1.0},
    }
    path = tmp_path / "exp.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert main(["run", str(path), "--out", str(tmp_path / "out"), "--days", "1"]) == 2
    assert "cannot reach ollama at http://127.0.0.1:9" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


@pytest.mark.req("REQ-LLM-009")
def test_backend_unavailable_exits_3_with_resume_advice(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC1: a run stopped by the backend says how to continue."""
    import pericles.experiment.cli as cli

    def stopped(session: object, days: int | None = None) -> object:
        raise BackendUnavailable("ollama at http://x: 5 failures in a row; last: down")

    monkeypatch.setattr(cli, "advance", stopped)
    out = tmp_path / "out"
    assert main(["run", str(BASELINE), "--out", str(out), "--days", "1"]) == cli.EXIT_BACKEND == 3
    err = capsys.readouterr().err
    assert "5 failures in a row" in err
    assert f"pericles resume {out}" in err


def test_meta_records_the_llm_modes(tmp_path: Path) -> None:
    """meta.json says how the LLM was run, and that wait mode is reproducible."""
    assert main(["run", str(BASELINE), "--out", str(tmp_path / "out"), "--days", "1"]) == 0
    meta = json.loads((tmp_path / "out" / "meta.json").read_text(encoding="utf-8"))
    assert (meta["llm_mode"], meta["cache_mode"], meta["reproducible"]) == ("wait", "record", True)
```

Add the imports these need at the top of `tests/pericles/test_cli.py` if absent: `json`, `yaml`, `from pericles.llm.gateway import BackendUnavailable`. `BASELINE` is the path to `experiments/baseline.yaml` that the file already uses. If it is named differently there, use that name.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/pericles/test_llm_runs.py tests/pericles/test_cli.py -q`
Expected: FAIL on import (`pericles.experiment.llm`).

- [ ] **Step 3: Implement**

Create `src/pericles/experiment/llm.py`:

```python
"""Backends, cache and call log for a run directory (ADR-0017 §5-§8, §11)."""

from __future__ import annotations

import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pericles.experiment.rundir import RunDirectory
from pericles.llm.backend import Backend, LLMSetupError
from pericles.llm.cache import ResponseCache
from pericles.llm.calls import CallLog
from pericles.llm.config import LLMConfig
from pericles.llm.fake import FakeBackend
from pericles.llm.gateway import FailurePolicy, Gateway
from pericles.llm.mlx import MLXBackend
from pericles.llm.ollama import OllamaBackend

CACHE_DIR = "llm_cache"
CACHE_FILE = "responses.sqlite"
CALLS_FILE = "llm_calls.sqlite"


def build_backends(config: LLMConfig) -> dict[str, Backend]:
    backends: dict[str, Backend] = {}
    for key in sorted(config.backends):
        spec = config.backends[key]
        if spec.kind == "ollama":
            assert spec.url is not None  # LLMConfig requires it
            backends[key] = OllamaBackend(spec.url, spec.timeout_s, spec.concurrency)
        elif spec.kind == "mlx":
            backends[key] = MLXBackend(spec.concurrency)
        elif spec.replies is not None:
            backends[key] = FakeBackend.from_file(Path(spec.replies), concurrency=spec.concurrency)
        else:
            backends[key] = FakeBackend(concurrency=spec.concurrency)
    return backends


def policy_of(config: LLMConfig) -> FailurePolicy:
    return FailurePolicy(
        config.mode,
        config.backoff_base_s,
        config.backoff_factor,
        config.backoff_max_s,
        config.max_backend_failures,
    )


def replay_source(path: Path) -> Path:
    """The responses.sqlite of a run directory, its llm_cache directory, or the file itself."""
    for candidate in (path, path / CACHE_FILE, path / CACHE_DIR / CACHE_FILE):
        if candidate.is_file():
            return candidate
    raise LLMSetupError(f"llm.cache_from: no {CACHE_FILE} under {path}")


def run_meta(config: LLMConfig) -> dict[str, Any]:
    return {
        "llm_mode": config.mode,
        "cache_mode": config.cache,
        "reproducible": config.mode != "live",
    }


def open_gateway(
    config: LLMConfig, backends: Mapping[str, Backend], run_dir: RunDirectory
) -> Gateway:
    """The run's gateway. A replay run first copies its source cache into its own llm_cache."""
    cache_path = run_dir.path / CACHE_DIR / CACHE_FILE
    if config.cache == "replay" and not cache_path.exists():
        assert config.cache_from is not None  # LLMConfig requires it
        shutil.copyfile(replay_source(Path(config.cache_from)), cache_path)
    return Gateway(
        config.models,
        backends,
        ResponseCache(cache_path, config.cache),
        policy_of(config),
        CallLog(run_dir.path / CALLS_FILE),
    )
```

The `assert` lines restate invariants that `LLMConfig` enforces. If the mutation gate reports their mutants as survivors, mark those two lines `# pragma: no mutate` with that reason.

`src/pericles/experiment/rundir.py`, in `create`: add a keyword `extra: Mapping[str, Any] | None = None` and merge it into `meta` with `meta.update(dict(extra or {}))` before writing.

`src/pericles/experiment/launch.py`:

```python
from pericles.experiment.llm import build_backends, open_gateway, replay_source, run_meta
from pericles.llm.gateway import BackendUnavailable, Gateway, check_models


@dataclass
class Session:
    run_dir: RunDirectory
    experiment: Experiment
    engine: Engine
    state: WorldState
    controller: Controller
    gateway: Gateway

    def close(self) -> None:
        self.gateway.close()
        self.run_dir.close()


def _backends(experiment: Experiment) -> dict[str, Backend]:
    """Build and check every backend before anything is written (ADR-0017 §11)."""
    backends = build_backends(experiment.llm)
    check_models(experiment.llm.models, backends)
    return backends


def start(experiment: Experiment, out: Path) -> Session:
    """Build and check everything first, so a run that cannot start leaves no directory."""
    state = build_world(experiment)
    engine = Engine(experiment.registry, experiment.engine)
    controller = scripted_controller(engine.context, experiment.agents)
    backends = _backends(experiment)
    if experiment.llm.cache == "replay":  # a resumed replay run already holds its copy
        assert experiment.llm.cache_from is not None
        replay_source(Path(experiment.llm.cache_from))
    run_dir = RunDirectory.create(
        out, experiment.resolved, seed=experiment.seed, extra=run_meta(experiment.llm)
    )
    gateway = open_gateway(experiment.llm, backends, run_dir)
    return Session(run_dir, experiment, engine, state, controller, gateway)


def reopen(out: Path) -> Session:
    """Continue from the last usable snapshot; the run directory is closed if that fails."""
    run_dir = RunDirectory.open(out)
    try:
        experiment = experiment_from_mapping(run_dir.config, run_dir.path)
        engine = Engine(experiment.registry, experiment.engine)
        controller = scripted_controller(engine.context, experiment.agents)
        backends = _backends(experiment)
        state, _ = resume(run_dir, controller.load)
        gateway = open_gateway(experiment.llm, backends, run_dir)
        if gateway.calls is not None:
            gateway.calls.truncate_after(state.tick - 1)
    except BaseException:
        run_dir.close()
        raise
    return Session(run_dir, experiment, engine, state, controller, gateway)
```

In `advance`, wrap the `run(...)` call so the metrics are still written when a backend stops the run:

```python
    try:
        session.state = run(...)  # unchanged arguments
    except BackendUnavailable:
        _write_metrics(session)
        raise
    _write_metrics(session)
    return session.state
```

`_write_metrics(session)` holds the existing two lines that compute `daily_survival(...)` and call `write_metrics`. On a stop, compute through `log.last_tick() + 1` instead of `session.state.tick`:

```python
def _write_metrics(session: Session) -> None:
    log = session.run_dir.event_log
    last = log.last_tick()
    through = 0 if last is None else last + 1
    rows = daily_survival(session.run_dir.config, log.events(), through)
    session.run_dir.write_metrics(rows)
```

After a normal run `last + 1 == session.state.tick`, so the existing metrics tests still hold. Import `Backend` from `pericles.llm.backend` for the annotation.

`src/pericles/experiment/cli.py`:

```python
from pericles.llm.backend import LLMSetupError
from pericles.llm.cache import CacheMiss
from pericles.llm.gateway import BackendUnavailable

EXIT_BACKEND = 3
```

- Add `LLMSetupError` to the `except` tuple around `start` and `reopen`, so it exits 2.
- Replace `session.run_dir.close()` with `session.close()`.
- Wrap `advance`:

```python
    try:
        for path in session.run_dir.skipped:
            print(f"pericles: skipped unusable snapshot {path}", file=sys.stderr)
        state = advance(session, args.days)
    except BackendUnavailable as error:
        print(f"pericles: {error}", file=sys.stderr)
        print(
            f"pericles: the run stopped cleanly; continue it with "
            f"`pericles resume {session.run_dir.path}`",
            file=sys.stderr,
        )
        return EXIT_BACKEND
    except CacheMiss as error:
        print(f"pericles: {error}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        session.close()
```

If an existing test constructs `Session(...)` directly with five arguments, add a gateway built with `Gateway({}, {}, ResponseCache(None, "off"), FailurePolicy("wait", 1.0, 1.0, 1.0, 1))`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS, all tests. Fix the two literals in the stop test as Step 1 explains.

- [ ] **Step 5: Gates, mutation, commit**

```bash
git add -A
git commit -m "feat(experiment): gateway in every run — fail-fast model check, replay from a cache, clean stop and resume

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Requirements, traceability and README

**Files:**
- Modify: `docs/requirements/llm.md`, `docs/requirements/traceability.md` (generated), `README.md`

- [ ] **Step 1: Set the statuses**

In `docs/requirements/llm.md`, change `Accepted` to `Implemented` on the status line of REQ-LLM-001, -002, -003, -004, -005, -006, -007 and -008. Leave REQ-LLM-009 `Accepted`, because AC2 needs the M2b mind. Change nothing in `nfr.md`: REQ-NFR-001's golden run is M2b's.

- [ ] **Step 2: Regenerate and check the traceability matrix**

Run: `PYTHONPATH=tools uv run python -m pericles_tools.traceability matrix && PYTHONPATH=tools uv run python -m pericles_tools.traceability check`
Expected: exit 0. Every Implemented requirement has linked tests.

- [ ] **Step 3: Document how to use the models**

In `README.md`, under the commands section, add:

````markdown
### Language models

Villagers with a `model:` call a model through the gateway (ADR-0017). Configure backends and models in the experiment's `llm:` section:

```yaml
llm:
  cache: record            # off | record | replay (replay needs cache_from: <run dir>)
  backends:
    local: {kind: ollama}  # http://localhost:11434 by default
  models:
    qwen: {backend: local, name: "qwen3:latest", temperature: 0.7}
  assign: {qwen: 1.0}      # split adults without a pinned model by ratio
```

- Ollama: install it, run `ollama serve`, and `ollama pull` each model. `pericles run` checks the models before it starts.
- MLX (Apple Silicon): `uv sync --extra mlx`, then use `kind: mlx` with a Hugging Face name or a local path.
- Contract tests against live models: `uv run pytest -m slow` (set `PERICLES_OLLAMA_MODEL` or `PERICLES_MLX_MODEL` to choose the model).
- A run stopped by an unreachable backend exits 3. Continue it with `pericles resume <run dir>`.
````

- [ ] **Step 4: Full gates and the slow tests on the Mac**

Run the six gates, then:
- `PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run --changed-since main`. Expected: core ≥ 80%, agents ≥ 70%, llm ≥ 70%.
- `uv run pytest -m slow -q`. Expected: the Ollama and MLX contract tests pass on the user's Mac. Report the counts.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "docs: LLM gateway requirements implemented, traceability, model setup in the README

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
