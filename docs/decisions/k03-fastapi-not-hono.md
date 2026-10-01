# K3. FastAPI, not Hono

Purpose: record the decision why the BFF is Python and FastAPI.
Read this when: you wonder whether to rewrite the BFF in TypeScript.
Related: [decisions](README.md), [K2](k02-one-stack.md), [design.md](../design.md) section 3 (K3).

Status: Accepted, 2026-10-01. Built: `packages/bff`.

## Context

The login and proxy code already exists in speech-to-text with about 2,800 lines of tests, and it is the security boundary between a browser and Eneo. It also matches Eneo's own stack.

## Decision

Extract that code with its tests into a FastAPI package. Hono could do the job and would give one language across the kit; that is a reason to revisit later, not to rewrite now.

## Consequences

- Behaviour is carried over with its tests, not redesigned.
- The BFF needs Python 3.12; Node is needed only to build a module's UI.
- A rewrite is a new decision, taken with the same tests as the bar.
