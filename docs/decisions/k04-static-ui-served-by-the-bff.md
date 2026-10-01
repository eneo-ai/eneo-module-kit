# K4. The UI is a static app served by the BFF

Purpose: record the decision why the UI is built to static files and served by the same process as the BFF.
Read this when: you consider server rendering for a module, or an inline script or style in the page.
Related: [decisions](README.md), [K2](k02-one-stack.md), [K9](k09-colour-mode-in-the-ui-package.md), [K10](k10-branding-without-templating.md), [architecture](../architecture.md#how-the-app-is-assembled).

Status: Accepted, 2026-10-01. Built: serving in `packages/bff/src/eneo_module_bff/web.py`. Planned: the UI package and template that produce the static app.

## Context

A server-rendered UI would need a second server process or a proxy hop in front of uploads and WebSockets. A trial on 2026-10-01 built a Vite 8 app with Astryx 0.6.3 and the built Eneo theme, served it from FastAPI, and ran it in Chromium and WebKit with no console or CSP errors under `script-src 'self'; style-src 'self'` (no `unsafe-inline` at all). A deep link returned the page; a missing asset and an unknown `/api/*` path returned 404, not HTML.

## Decision

The UI is a static app. `create_app(static_dir=...)` serves its `assets/` and its one `index.html` for every page, and answers 404 for `/api/*` and for a path that names a missing file. No server rendering.

## Consequences

- The Content-Security-Policy has no inline script and no inline style. If a component later needs inline style attributes, only `style-src` is widened, with a note in [design.md](../design.md).
- Anything that a server render would have injected (colour mode, branding) is handled in the browser: [K9](k09-colour-mode-in-the-ui-package.md), [K10](k10-branding-without-templating.md).
- `static_dir` must hold an `assets/` directory, or `create_app` raises.
- Speech-to-text can adopt the UI package only once it is a static app too.
