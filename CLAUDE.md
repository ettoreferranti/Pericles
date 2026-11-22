# Pericles — working agreements

Read first: `docs/superpowers/specs/2026-11-22-pericles-design.md`, `docs/requirements/README.md`, `docs/adr/README.md`.

## Commands

```bash
uv sync                                                   # install
uv run pytest                                             # tests (slow excluded; `-m slow` for Ollama contract tests)
uv run mypy && uv run ruff check . && uv run ruff format --check .
PYTHONPATH=tools uv run python -m pericles_tools.traceability check    # requirement ↔ test rules
PYTHONPATH=tools uv run python -m pericles_tools.traceability matrix   # writes docs/requirements/traceability.md
PYTHONPATH=tools uv run python -m pericles_tools.adr check
PYTHONPATH=tools uv run python -m pericles_tools.mutation_gate run [--changed-since origin/main]
PYTHONPATH=tools uv run python -m pericles_tools.backlog [--apply]     # GitHub issues from requirements
cd viewer && pnpm test && pnpm typecheck && pnpm lint && pnpm mutation
```

## Rules

- TDD: failing test first. Every test that verifies a requirement carries
  `@pytest.mark.req("REQ-…")` (literal IDs; `pytest.mark.req` spelled out) and names the AC in its docstring.
- Product tests live in `tests/pericles/` (these run under mutmut). Tooling tests live in `tests/tools/`.
- `pericles.core` never imports `agents`, `llm`, `experiment`, `server` or `analysis`. The engine is deterministic: no wall clock, no unseeded randomness.
- Significant design decisions get an ADR (`docs/adr/`, next number, add to the index). ADRs are amended or superseded, never deleted.
- Requirement changes follow `docs/requirements/README.md` → "Revising requirements". Mark a milestone done in `milestones.md` only when all its requirements have passing tests.
- Mutation thresholds: core ≥ 80%, agents/llm ≥ 70%, viewer ≥ 70%. Fix surviving mutants by adding tests. Never lower thresholds without an ADR.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
