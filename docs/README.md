# Documentation index

Purpose: find the right page of the kit's documentation, and see what each page covers and whether it is current.
Read this when: you do not know where a fact lives, or you are adding a page.
Related: [repository README](../README.md), [AGENTS.md](../AGENTS.md), [glossary](glossary.md).

Docs are English. Every page starts with `Purpose`, `Read this when` and `Related`. One fact lives in one page; other pages link to it. A claim about code names a path, not a line.

Status: **current** matches the code today; **planned** describes something not built yet; **temporary** is build scaffolding that is removed at the end of the build.

## Start here

| Page | Purpose | Audience | Status |
|---|---|---|---|
| [README](../README.md) | What the kit is, what is built, quick start | Everyone | current |
| [architecture](architecture.md) | Diagrams: parts, handoff, session, proxy, uploads, files, UI layers, branding, image, deployment, CI | Developers, reviewers, agents | current |
| [glossary](glossary.md) | The terms of the docs and the code | Everyone | current |

## Guides

| Page | Purpose | Audience | Status |
|---|---|---|---|
| [new module](guides/new-module.md) | Start from `template/`: copy, rename, install, run against the stub, test, image, register, what CI proves | Module developers | current |
| [build a module](guides/build-a-module.md) | The backend in detail: `create_app`, guards, proxy rules, uploads, signed files, tests | Module developers | current |
| [UI package](guides/ui-package.md) | Install and wire `@eneo-ai/module-kit`; its names, colour mode, links, branding, shell, theme | Module developers | current |
| [configuration](guides/configuration.md) | Every environment variable, default and check | Module developers, operators | current |
| [local development](guides/local-development.md) | The template's stub Eneo and a walk through the login | Module developers | current |
| [security checklist](guides/security-checklist.md) | What the kit enforces, what a module must do, known limits | Module developers, reviewers | current |

## Reference and decisions

| Page | Purpose | Audience | Status |
|---|---|---|---|
| [BFF package README](../packages/bff/README.md) | Public names, HTTP surface, answers, limits, how to develop the package | BFF developers | current |
| [UI package README](../packages/ui/README.md) | The package's exports in brief | UI developers | current |
| [template README](../template/README.md) | The module template in brief, with the pre-release way to try it | Module developers | current |
| [decisions](decisions/README.md) | K1 to K15, one short page each | Anyone asking why | current |
| [module contract](module-contract.md) | The calls between the BFF and Eneo, with examples, and what the BFF does with each failure | Stub and Eneo-side developers, debuggers | current |
| [design](design.md) | The long form: the module contract with Eneo (section 2), the HTTP surface (5), limits (6), open questions (7) | Developers, the owner | current |

## For agents

| Page | Purpose | Audience | Status |
|---|---|---|---|
| [AGENTS.md](../AGENTS.md) | Directory map, commands, rules, how to find things | Coding agents | current |
| `CLAUDE.md` | Imports `AGENTS.md` | Claude Code | current |
| [template/AGENTS.md](../template/AGENTS.md) | The rules of a module made from the template (copied into every module) | Coding agents in a module | current |

## Build scaffolding

| Path | Purpose | Status |
|---|---|---|
| `docs/plans/2026-10-01-module-kit-plan.md` | The implementation plan of the kit | temporary |
| `docs/reference/astryx-phase0-reference.patch` | The verified Astryx foundation copied from speech-to-text, the source the UI package was built from | temporary |
| `.beads/` | The issue tracker (`br`, prefix `kit`): work order and status | temporary |

Permanent pages do not depend on these.

## Adding a page

1. Start with the three header lines.
2. Put a fact in one place; link to it from elsewhere.
3. Prefer a table for facts, and a copy-pasteable command that says which directory it runs from.
4. Diagrams are Mermaid, `flowchart` or `sequenceDiagram` only, with a sentence above each saying what to look at.
5. Add the page to the table above.
