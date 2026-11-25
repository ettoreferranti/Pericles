# Pericles

A research sandbox for studying how a village society evolves when every adult villager is driven
by a local LLM (Ollama / MLX), under engine parameters and natural-language laws that the
experimenter can change during a run.

- Design spec: [docs/superpowers/specs/2026-11-22-pericles-design.md](docs/superpowers/specs/2026-11-22-pericles-design.md)
- Requirements: [docs/requirements/](docs/requirements/README.md)
- Architecture decisions: [docs/adr/](docs/adr/README.md)

Status: M1 Headless sim is done (M1a to M1d), with every M1 requirement Implemented, including REQ-NFR-003 (at least 1000 scripted ticks/s with 150 villagers on a 128×128 map). Next is M2, LLM minds.

## Run a village

```bash
uv run pericles run experiments/baseline.yaml --out runs/baseline
uv run pericles resume runs/baseline --days 90
PYTHONPATH=tools uv run python -m pericles_tools.bench     # REQ-NFR-003 check
uv run pytest -m long                                      # baseline village tests
uv run pytest -m perf                                      # perf test (target machine)
```

## Development

Requirements: macOS or Linux, Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/), Node ≥ 20 with pnpm, and [Ollama](https://ollama.com) for live runs.

```bash
uv sync && uv run pytest
cd viewer && pnpm install && pnpm dev
```

See [CLAUDE.md](CLAUDE.md) for all commands and working agreements.
