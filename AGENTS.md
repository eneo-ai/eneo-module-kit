# Agent instructions: eneo-module-kit

The starter for Eneo modules. Read `README.md` first: it states what the kit contains, what stays in each module,
and the choices already made.

## Before writing code

- Design: `docs/design.md`. Plan: `docs/plans/2026-10-01-module-kit-plan.md`. Read "Global Constraints" and "How to
  work" in the plan every time.
- Work order and status live in Beads in this repository (prefix `kit`): `br ready --json`, claim, close with
  evidence. Each bead names the files it may touch and what is out of scope. Do not start a bead that is not ready.
- The source to extract from is `eneo-ai/eneo-mod-speech-to-text` at commit `f81a7dd`, cloned beside this
  repository: `backend/app/` and `backend/tests/` for the BFF. The verified Astryx foundation (theme, providers,
  test shims, gate changes) is in `docs/reference/astryx-phase0-reference.patch`.
- Never change the speech-to-text repository from here. This repository copies from it.

## Rules that are already decided

- One stack: Vite + React + Astryx for the UI, FastAPI for the BFF, one process and one container. Do not add
  Next.js, Hono, Tailwind or a second UI library.
- The BFF package holds the module contract with Eneo (login handoff, session, token refresh, deny-by-default proxy,
  transport primitives). A module's route allowlist and its own protocols stay in the module.
- The UI package imports nothing from a router or a meta-framework.
- Astryx is pinned to an exact version. Run its CLI through the package script (`npm run astryx -- <command>`), read
  `npm run astryx -- component <Name>` before using a component, and never guess a prop.
- No ejected Astryx components and no authored StyleX. A design-system shortfall is fixed once, in the theme.
- User-facing text in the template is Swedish. No fonts or scripts from other origins.
- Accessibility bar: WCAG 2.2 AA, 44 px touch targets, a visible focus indicator, proven by the gate the template
  ships.

## What the template must give every new module

- `AGENTS.md` with the module's rules, and a `CLAUDE.md` that imports it.
- The pinned Astryx CLI with an `astryx` npm script, and the block `astryx init --features agents` generates.
- The UI package registered as an Astryx integration, so `astryx build` proposes the Eneo shell and the generated
  block carries the kit's own lines.
- No custom MCP server and no skill. Add a skill only when agents are seen skipping these files.
