# ADR-0010: Money as coins minted from gold at a Mint

- **Status:** Accepted
- **Date:** 2026-11-22
- **Spec:** [Pericles design](../superpowers/specs/2026-11-22-pericles-design.md)

## Context

The economy must support barter, and possibly simple money, without assuming money exists. Alternatives considered: barter only (money may emerge in an informal way), and an abstract currency balance per villager (too presumptive).

## Decision

Barter is always possible. **Coins** are an ordinary item produced from gold ore by a minting recipe at a **Mint** building. Whether a Mint exists at the start, and who knows how to mint, are run parameters. Coin adoption is measured, not scripted.

## Consequences

+ 'Do villagers adopt money, and when?' becomes an observable outcome.
+ Fits the data-driven content model (ADR-0005).
− Taxes and wages in coins need law hooks to be enforceable.
