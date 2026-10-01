# K7. Primitives, not routes, for uploads and files

Purpose: record the decision why `forward_upload` and `stream_signed` are functions a module calls from its own routes, and in which order routes match.
Read this when: you add or change a module route, an upload, a file stream, or the order in which routes are registered.
Related: [decisions](README.md), [K14](k14-body-limits-and-stream-cap.md), [build a module](../guides/build-a-module.md), [architecture](../architecture.md#uploads), [design.md](../design.md) section 3 (K7).

Status: Accepted, 2026-10-01. Built: `packages/bff/src/eneo_module_bff/transport.py` and `app.py`.

## Context

Forwarding a multipart upload and streaming a signed file with Range are the same in every module, but which Eneo routes they point at is not. FastAPI reads a route's body before it runs the route's dependencies, so a route with a `File(...)` parameter takes a big body before the session is checked.

## Decision

The kit ships functions, not routes.
- A module declares its routes on an `APIRouter` and passes it to `create_app(routers=[...])`. Routes match in registration order: the kit's own, then the module's, then the proxy, then the static app. A module's route wins over the proxy and the page (also under `/api/eneo/`) and cannot replace a kit route. The module declares its own `Depends(require_session)` and `require_same_origin` on each route.
- An upload route has no `File(...)` parameter: `forward_upload(request, path)` reads the multipart itself, after the dependencies.
- `stream_signed` mints Eneo's signed URL with the module's credentials, keeps it with the session, and streams the file with Range. An answer to the mint request that the module cannot use (not JSON, no `url`, a URL that is not http(s) or that the client refuses (a NUL, over 65,536 characters), an `expires_at` that was given but is not a finite number above zero (`false`, `0`, `""`, `[]`, `{}`, a negative one or one too big for a float; only a missing or null one means the default of 15 minutes)) is a 502 `upstream_invalid`, is never kept, and gives its stream slot back; the log names the mint path, never the body.
- A signed URL is a bearer URL to a file, so the session store keeps it and it ends with its session, however the session ends.
- A file is shown inline only if its media type cannot run script (audio, video, PDF, PNG, JPEG, GIF, WebP, or a module's `inline_types`); anything else is an attachment.

## Consequences

- A module author can forget a guard: the kit cannot add one to a route it does not own. The guide asks for a test that walks the module's routers (`unguarded_routes`).
- A route added to the app after `create_app` returns is never reached.
- A WebSocket relay is not in the kit until a second module needs one.
