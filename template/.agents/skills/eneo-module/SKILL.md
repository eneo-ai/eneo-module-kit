---
name: eneo-module
description: Set up or extend a module created from Eneo Module Kit, including its pages, guarded backend routes and connection to Eneo. Use inside a module repository; shared kit changes belong in the kit repository.
---

# Build an Eneo module

Work from the module root: the directory containing `backend/`, `web/` and `AGENTS.md`.
Read [the module rules](../../../AGENTS.md) and [its README](../../../README.md) first.
They name the installed stack, commands and extension points. This skill is a workflow;
the rules and linked guides remain the technical reference.

## Set up a new module

First run `node stub-eneo/dev.mjs --check` from the module root. It must end with
`OK: signed in through the stub Eneo, the page is served, and /api/example answered {"greeting":"Hej Erik Lund"}`
and exit code 0. If it says there is no Python or the UI is not built, the folder is not set up
(a plain copy of the template or a fresh clone): clone `https://github.com/eneo-ai/eneo-module-kit.git`
outside the module and, from that checkout, run `node scripts/new-module.mjs <the module root>`
(Node 22.22.2+, Python 3.12+), then run the check again. Do not install the kit's packages from
the GitHub release `v0.1.0` (it does not fit the template: `npm error code ERESOLVE`), npm or
PyPI, do not use `--force` or `--legacy-peer-deps`, and do not rewrite a lock by hand. The kit's
[new-module guide](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md)
has the steps by hand and [what to do when it does not work](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md#when-it-does-not-work).

Set the product name in `web/src/config.ts`, the browser title and the `<noscript>` text in `web/index.html`, the icons in `web/public/`,
the drafts' prefix in `web/src/drafts.ts`, and the API title in `backend/main.py`. The stub run needs no `.env`
(`dev.mjs` uses the stub's values); copy `.env.example` to `.env` only for Docker Compose or a real Eneo, and only if
no `.env` exists. Develop against `stub-eneo/` first; a real instance additionally needs its
registered module key, callback URL and service key. Never print or commit real secrets.

Verify login, the example page and logout before replacing the example with the requested
feature. The `--check` run is that proof for login and the example route. The stub proves local behavior; it does not prove the deployment's TLS, cookies
or Eneo permissions.

## Add a feature at its owner

| Work | Start here | Read when needed |
|---|---|---|
| Page or UI state | `web/src/App.tsx`, `web/src/pages/Flows.tsx`, `web/src/Frame.tsx` | From `web/`: `npm run astryx -- docs eneo-module`, then `build "<idea>"` and `component <Name>` through the same script. Keep the existing providers, the router's root and the shell; a new page is a route with its title and calls `useRouteReady` once it has its content. |
| Module API | `backend/routes.py`, `backend/tests/test_routes.py` | [Build a module](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/build-a-module.md): route guards, calling Eneo and transport helpers. |
| Proxied Eneo API | `PROXY_RULES` in `backend/main.py`, `backend/tests/test_app.py` | Verify the actual Eneo endpoint, method and permission contract before adding a rule. A module owns its allowlist. |
| Login or session behavior | Existing `RequireSession`, `web/src/session.ts`, `web/src/AccountMenu.tsx` | `web/node_modules/@eneo-ai/module-kit/README.md` after installation, and `npm run astryx -- docs eneo-module` from `web/`. Reuse the package rather than creating another token or refresh client. |
| Configuration, release or deployment | `.env.example`, `Dockerfile`, `docker-compose*.yml`, `.github/workflows/` | [Configuration](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/configuration.md), [release and deploy](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/deploy.md) and [security checklist](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/security-checklist.md). |

Eneo owns identity and upstream permissions. The kit owns the module handoff, session,
guarded transport and shared UI. The module owns its domain data, routes, persistence
and behavior after logout. A shared kit defect is fixed in the kit repository; do not
patch `node_modules`, installed Python packages or copy their internals into the module.

## Validate the result

Use the existing fixture and nearest test for the behavior being changed. Backend route
changes run `python -m unittest discover -s backend/tests -t backend` from the module root;
these checks also detect a route without `require_session`, and a write without
`require_same_origin` or `require_expected_user`.

For UI work, add relevant loading, empty, error and signed-out states to
`web/tests/e2e/screens.ts`. From `web/`, run `npm run lint`, `npm test` and a focused browser test,
for example `npm run test:e2e -- --project=chromium tests/e2e/flow.spec.ts`. Inspect the
changed states visually, including mobile and both themes when layout or color changes.
Run the full `npm run test:e2e` on the final unchanged candidate, as required by `AGENTS.md`.
When a browser test fails, here or only in CI, follow the kit's [quality guide](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/quality.md).

Use an absolute `PYTHON` path for the browser tests. If default ports are occupied, set
both `E2E_APP_PORT` and `E2E_STUB_PORT`; stop only processes started for this work.
Report what passed, what was skipped or not run, and what still requires a real Eneo instance.
