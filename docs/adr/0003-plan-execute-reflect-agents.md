# ADR-0003: Plan, reactive execution and reflection agent architecture

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

Villager minds must produce coherent long-term behaviour (saving for a building, keeping grudges) while keeping LLM calls few and outputs easy to validate and compare across models. Alternatives considered: one call per decision from an action menu (cheap but purely reactive), and free-form tool calling (tool-calling quality varies wildly between Ollama models, which would confound the model comparison).

## Decision

Each adult has goals, a short plan, memories, opinions and knowledge. The LLM is called to **plan or re-plan**, to hold **dialogue**, for **meetings and votes**, for **board posts**, and for a daily **reflection** that condenses events into durable memories and opinion updates. A deterministic executor turns plan steps into engine intents. All outputs are JSON validated against schemas. Invalid outputs get up to 2 retries with error feedback, then a utility-AI fallback. Every failure is logged as an agent-quality metric.

## Consequences

+ Coherent, memory-driven behaviour; comparable structured outputs.
+ Fallback keeps the simulation alive with weak models.
− More components (memory retrieval, triggers, executor) to build and test.
