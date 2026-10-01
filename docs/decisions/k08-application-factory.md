# K8. An application factory

Purpose: record the decision why `create_app` builds the app from settings, and what hangs off `app.state`.
Read this when: you are tempted to add a module-level setting, client, cache or app to the package.
Related: [decisions](README.md), [architecture](../architecture.md#how-the-app-is-assembled), [build a module](../guides/build-a-module.md#9-test-it).

Status: Accepted, 2026-10-01. Built: `packages/bff/src/eneo_module_bff/app.py`.

## Context

Import-time globals force a test to patch module state, and make two apps in one process share a session store and an HTTP client.

## Decision

`create_app(...)` builds the app from settings and owns its HTTP client through the app's lifespan. `app.state` holds `settings`, `http`, `module_auth` and the stream slots. There is no import-time application state in the package.

## Consequences

- A test builds an app per case: `create_app(settings, http_client=...)`. An injected client is never closed by the app; a client the app made is closed on shutdown.
- Route dependencies find the auth object on `request.app.state`, so a module declares `Depends(require_session)` before any app exists.
