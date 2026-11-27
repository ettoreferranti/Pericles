# Pericles

A research sandbox for studying how a village society evolves when every adult villager is driven
by a local LLM (Ollama / MLX), under engine parameters and natural-language laws that the
experimenter can change during a run.

- Design spec: [docs/superpowers/specs/2026-11-22-pericles-design.md](docs/superpowers/specs/2026-11-22-pericles-design.md)
- Requirements: [docs/requirements/](docs/requirements/README.md)
- Architecture decisions: [docs/adr/](docs/adr/README.md)

Status: M1 Headless sim is done (M1a to M1d), with every M1 requirement Implemented, including REQ-NFR-003 (at least 1000 scripted ticks/s with 150 villagers on a 128×128 map). M2a, the LLM gateway, is done. Next is M2b, LLM plan minds.

## Run a village

```bash
uv run pericles run experiments/baseline.yaml --out runs/baseline
uv run pericles resume runs/baseline --days 90
PYTHONPATH=tools uv run python -m pericles_tools.bench     # REQ-NFR-003 check
uv run pytest -m long                                      # baseline village tests
uv run pytest -m perf                                      # perf test (target machine)
```

### Language models

Villagers with a `model:` are planned by that model (ADR-0018). When a trigger fires (idle, step done or failed, a need reaching its level, or every `replan_hours`), the villager asks for a short plan of village jobs, which plain code then carries out. Invalid plans are retried with the error, then the scripted mind takes over for `fallback_hours`. Plans, retries and fallbacks appear in `events.sqlite`. `experiments/llm-village.yaml` is a ready example: `uv run pericles run experiments/llm-village.yaml --out runs/llm`.

All calls go through the gateway (ADR-0017), which checks the models when a run starts (it fails fast if a model is missing) and keeps a response cache and call log. Configure backends and models in the experiment's `llm:` section:

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
- Replay a recorded run without any model installed: `cache: replay` with `cache_from:` pointing at the recorded run directory.
- Contract tests against live models: `uv run pytest -m slow` (set `PERICLES_OLLAMA_MODEL` or `PERICLES_MLX_MODEL` to choose the model).
- A run stopped by an unreachable backend exits 3. Continue it with `pericles resume <run dir>`.

## Development

Requirements: macOS or Linux, Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/), Node ≥ 20 with pnpm, and [Ollama](https://ollama.com) for live runs.

```bash
uv sync && uv run pytest
cd viewer && pnpm install && pnpm dev
```

See [CLAUDE.md](CLAUDE.md) for all commands and working agreements.
