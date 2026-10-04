# K10. Branding without templating

Purpose: record the decision why the organisation is fetched at runtime and never written into `index.html`.
Read this when: you work on how a deployment shows its organisation's name or logo.
Related: [decisions](README.md), [configuration](../guides/configuration.md), [K4](k04-static-ui-served-by-the-bff.md), [design.md](../design.md) section 3 (K10).

Status: Accepted, 2026-10-01. Built: the BFF routes `/api/branding` and `/api/branding/logo/{light|dark}` (`branding.py`). Planned: the UI package's reading of them.

## Context

The same built UI runs for every deployment, each with its own organisation. Templating `index.html` would need server rendering ([K4](k04-static-ui-served-by-the-bff.md)).

## Decision

The page asks `/api/branding` before its first render and shows no organisation mark until it has the answer. Nothing is injected into `index.html`. The organisation is a deployment setting (`ORGANIZATION_*`, `SHOW_ORGANIZATION`); neither branding route asks for a session, because the sign-in page shows the organisation before there is one.

## Consequences

- The page waits for one small request before its first render.
- A logo that cannot be used is logged once at start and the organisation's name is shown instead.
- Logos are served with a sandboxing Content-Security-Policy, so an SVG opened on its own runs nothing in the module's origin.
