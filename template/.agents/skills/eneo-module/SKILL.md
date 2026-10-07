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

Start from the copied template, including its dotfiles. Read the kit's
[new-module guide](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md)
for package installation and local startup. Check whether the package versions are released:
before the first release, use the documented tarball and BFF package path rather than
retrying a registry install or rewriting the lock by hand.

Set the product name in `web/src/config.ts`, the browser title in `web/index.html`,
and the API title in `backend/main.py`. Copy `.env.example` to `.env` only if no `.env`
exists. Develop against `stub-eneo/` first; a real instance additionally needs its
registered module key, callback URL and service key. Never print or commit real secrets.

Verify login, the example page and logout before replacing the example with the requested
feature. The stub proves local behavior; it does not prove the deployment's TLS, cookies
or Eneo permissions.

## Add a feature at its owner

| Work | Start here | Read when needed |
|---|---|---|
| Page or UI state | `web/src/App.tsx`, `web/src/pages/Flows.tsx`, `web/src/Frame.tsx` | From `web/`: `npm run astryx -- docs eneo-module`, then `build "<idea>"` and `component <Name>` through the same script. Keep the existing providers and shell. |
| Module API | `backend/routes.py`, `backend/tests/test_routes.py` | [Build a module](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/build-a-module.md): route guards, calling Eneo and transport helpers. |
| Proxied Eneo API | `PROXY_RULES` in `backend/main.py`, `backend/tests/test_app.py` | Verify the actual Eneo endpoint, method and permission contract before adding a rule. A module owns its allowlist. |
| Login or session behavior | Existing `RequireSession`, `web/src/session.ts`, `web/src/AccountMenu.tsx` | `web/node_modules/@eneo-ai/module-kit/README.md` after installation, and `npm run astryx -- docs eneo-module` from `web/`. Reuse the package rather than creating another token or refresh client. |
| Configuration or deployment | `.env.example`, `Dockerfile`, `docker-compose.yml` | [Configuration](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/configuration.md) and [security checklist](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/security-checklist.md). |

Eneo owns identity and upstream permissions. The kit owns the module handoff, session,
guarded transport and shared UI. The module owns its domain data, routes, persistence
and behavior after logout. A shared kit defect is fixed in the kit repository; do not
patch `node_modules`, installed Python packages or copy their internals into the module.

## Validate the result

Use the existing fixture and nearest test for the behavior being changed. Backend route
changes run `python -m unittest discover -s backend/tests -t backend` from the module root;
these checks also detect missing session and write guards.

For UI work, add relevant loading, empty, error and signed-out states to
`web/tests/e2e/screens.ts`. From `web/`, run `npm run lint` and a focused browser test,
for example `npm run test:e2e -- --project=chromium tests/e2e/flow.spec.ts`. Inspect the
changed states visually, including mobile and both themes when layout or color changes.
Run the full `npm run test:e2e` on the final unchanged candidate, as required by `AGENTS.md`.

Use an absolute `PYTHON` path for the browser tests. If default ports are occupied, set
both `E2E_APP_PORT` and `E2E_STUB_PORT`; stop only processes started for this work.
Report what passed, what was skipped or not run, and what still requires a real Eneo instance.
