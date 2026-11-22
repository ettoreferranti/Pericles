# ADR-0002: Python simulation core with Three.js viewer

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

We need a headless, deterministic simulation that integrates with Ollama and MLX (Python-native), and analysis tooling (pandas, notebooks). We also need simple 3D visualisation. Alternatives considered: TypeScript everywhere (Stryker is excellent, but MLX needs a bridge and analysis is weaker), Godot (rendering for free, but simulation coupled to the engine and poor mutation testing), Rust + Bevy (fast but slow to iterate, and the bottleneck is LLM latency anyway).

## Decision

The simulation, agents, LLM gateway, experiment runner, server and analysis are Python (managed with `uv`; `ruff`, `mypy --strict`). The viewer is a separate TypeScript + Three.js app (Vite, `pnpm`) that talks to the core over WebSocket and can also replay a run directory.

## Consequences

+ Native MLX/Ollama, first-class data analysis, headless overnight runs.
+ Viewer is optional and swappable.
− Two languages and two toolchains (pytest/mutmut and Vitest/Stryker).
− A WebSocket protocol must be versioned and tested.
