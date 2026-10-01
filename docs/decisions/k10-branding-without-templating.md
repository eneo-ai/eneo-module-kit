# K10. Branding without templating

Purpose: record the decision why the organisation is fetched at runtime and never written into `index.html`.
Read this when: you work on how a deployment shows its organisation's name or logo.
Related: [decisions](README.md), [configuration](../guides/configuration.md), [UI package: branding](../guides/ui-package.md#branding), [K4](k04-static-ui-served-by-the-bff.md), [design.md](../design.md) section 3 (K10).

Status: Accepted, 2026-10-01. Built: the BFF routes `/api/branding` and `/api/branding/logo/{light|dark}` (`branding.py`) and the UI package's `BrandingProvider` and `Brand` (`packages/ui/src/branding.tsx`).

## Context

The same built UI runs for every deployment, each with its own organisation. Templating `index.html` would need server rendering ([K4](k04-static-ui-served-by-the-bff.md)).

## Decision

`BrandingProvider` asks `/api/branding` once, when the app starts, with a deadline of 2 s, and the page shows the product name alone until it has the answer (and if none comes). Nothing is injected into `index.html`. The organisation is a deployment setting (`ORGANIZATION_*`, `SHOW_ORGANIZATION`); neither branding route asks for a session, because the sign-in page shows the organisation before there is one. The kit ships no organisation's mark: a module that bundles a logo passes its URL as `defaultLogo`, and an organisation whose `logo` is `default` without one is shown as its name.

## Consequences

- The header may show the name first and the organisation a moment later; it never shows another organisation's mark.
- A logo that cannot be used is logged once at start and the organisation's name is shown instead.
- Logos are served with a sandboxing Content-Security-Policy, so an SVG opened on its own runs nothing in the module's origin.
- The choice between a deployment's light and dark logo is CSS (`base.css`), so no script runs for it.
