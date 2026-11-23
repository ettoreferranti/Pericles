# Pericles

A research sandbox for studying how a village society evolves when every adult villager is driven
by a local LLM (Ollama / MLX), under engine parameters and natural-language laws that the
experimenter can change during a run.

- Design spec: [docs/superpowers/specs/2026-11-22-pericles-design.md](docs/superpowers/specs/2026-11-22-pericles-design.md)
- Requirements: [docs/requirements/](docs/requirements/README.md)
- Architecture decisions: [docs/adr/](docs/adr/README.md)

Status: M1c Life and population complete; M1d Running villages next.

## Development

Requirements: macOS or Linux, Python ≥ 3.12 with [uv](https://docs.astral.sh/uv/), Node ≥ 20 with pnpm, and [Ollama](https://ollama.com) for live runs.

```bash
uv sync && uv run pytest
cd viewer && pnpm install && pnpm dev
```

See [CLAUDE.md](CLAUDE.md) for all commands and working agreements.
