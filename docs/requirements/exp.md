# EXP: Experiments, Interventions and Analysis

### REQ-EXP-001: Experiment configuration
Must · M4 · Proposed
- AC1: `experiment.yaml` defines seed, map parameters, content packs, initial population (names, traits, knowledge, models), engine parameters, initial laws and scheduled interventions.
- AC2: The config is validated at load. Errors name the field and the problem.

### REQ-EXP-002: Run modes
Must · M4 · Proposed
- AC1: `pericles run` supports `--headless`, `--mode wait|live` and `--cache record|replay|off`.
- AC2: `meta.json` records versions, seed, mode, cache mode and a `reproducible` flag (false for live mode).

### REQ-EXP-003: Run directory
Must · M1 · Proposed
- AC1: A run writes the config snapshot, `events.sqlite`, periodic snapshots, `llm_cache/`, metrics and `meta.json`.
- AC2: Event writes are transactional per tick.
- AC3: A run can be resumed from its last snapshot after a crash.

### REQ-EXP-004: Interventions
Must · M4 · Proposed
- AC1: Parameter changes, law changes and god powers can be scheduled in config or applied live. Each is applied at a tick boundary and logged as an intervention event.
- AC2: The intervention list of a run can be exported as a schedule. Re-running with it (and the cache in replay mode) reproduces the run.

### REQ-EXP-005: God powers
Must · M4 · Proposed
- AC1: Drought: applies yield modifiers to the configured actions for a duration.
- AC2: Raid: spawns a raider band at the map edge that targets stores. Palisades and defending villagers reduce losses by documented formulas. Raiders leave after a duration.
- AC3: Epidemic: infects a seeded initial set, with health drain and proximity spread per the parameters.
- AC4: Windfall/removal: adds or removes resource stock in an area.

### REQ-EXP-006: Metrics
Must · M4 · Proposed
- AC1: The analysis computes the five metric families (survival and growth; productivity and economy; social and legal; agent quality; model-group dynamics) per in-game day from the event log alone.
- AC2: In mixed-model runs, every metric can be broken down by model group.

### REQ-EXP-007: Comparison report
Must · M4 · Proposed
- AC1: `pericles report <run>...` generates a self-contained HTML report comparing runs, with time series and summary tables.
- AC2: `pericles.analysis.load_run()` returns pandas DataFrames of events and metrics.

### REQ-EXP-008: Sweeps
Should · M4 · Proposed
- AC1: `pericles sweep` runs an experiment across N seeds × M models one after another and writes a combined report with per-cell aggregates (mean, spread).
- AC2: An interrupted sweep resumes and skips the completed cells.
