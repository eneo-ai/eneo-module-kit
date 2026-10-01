# K2. One stack

Purpose: record the decision why the kit is not framework-agnostic.
Read this when: someone proposes Next.js, Hono, Tailwind or a second UI library, or a different split of work between UI and server.
Related: [decisions](README.md), [K1](k01-one-repository-three-parts.md), [K3](k03-fastapi-not-hono.md), [K4](k04-static-ui-served-by-the-bff.md).

Status: Accepted, 2026-10-01. Built: the BFF half. Planned: the UI half.

## Context

A kit that supports several stacks multiplies what it must test and document. A module also wants one process and one runtime in its image, and no proxy hop in front of uploads and WebSockets.

## Decision

Vite + React + Astryx for the UI, FastAPI for the BFF, one process and one container. The kit does not force its stack on the other half: the UI package imports nothing from a router or a meta-framework, and the BFF's HTTP surface is documented (`packages/bff/README.md`, [design.md](../design.md) section 5).

## Consequences

- No Next.js, Hono, Tailwind or second UI library in the kit.
- Either half can be replaced later, because the contract between them is the documented HTTP surface.
- A module on another UI stack can still use the BFF package.
