# K12. For agents: AGENTS.md, the pinned Astryx CLI, and the UI package as an Astryx integration

Purpose: record the decision how a module made from the template teaches an agent to produce the same kind of UI each time.
Read this when: you set up agent instructions for a module, or consider a custom MCP server or skill.
Related: [decisions](README.md), [AGENTS.md](../../AGENTS.md), [template/AGENTS.md](../../template/AGENTS.md), [design.md](../design.md) section 3 (K12).

Status: Accepted, 2026-10-01. Built: this repository's `AGENTS.md`, and the template's `AGENTS.md`, `CLAUDE.md`, `astryx` script and generated `web/AGENTS.md`. Built: the UI package's integration manifest, two reference templates, documentation topic and eight generated agent guidance lines.

## Context

Agents guess props and layouts unless the project tells them where the truth is. Every module should start with the same setup so no module has to be corrected one by one.

## Decision

Every module made from the template has an `AGENTS.md` with the module's rules and a `CLAUDE.md` that imports it and `web/AGENTS.md`, the pinned Astryx CLI behind an `astryx` npm script, and the block `astryx init --features agents` generates. The UI package registers its templates and documentation through `packages/ui/astryx.integration.mjs`, so `astryx build "en sida i en Eneo-modul"` proposes `eneo-module-page` first. No custom MCP server and no skill.

## Consequences

- Astryx's hosted MCP server is optional for discovery; the pinned CLI is the source of truth.
- A skill is added only when agents are seen skipping these files.
- The CLI discovers these contributions from the installed package. Check the packed tarball in a separate consumer; a workspace build alone does not prove a new module can find them.
- The templates supply reference source. The module's route still owns its data, loading and errors, and its `Frame` supplies the shell where one already exists.
