# K14. Body limits and a cap on streaming files

Purpose: record the decision why no request body is read before auth or past a limit, and why at most 64 files stream at once.
Read this when: you change `MAX_BODY_BYTES`, `MAX_UPLOAD_BYTES` or `MAX_CONCURRENT_STREAMS`, add a route that takes a body, or touch the middleware order.
Related: [decisions](README.md), [K7](k07-primitives-for-uploads-and-files.md), [configuration](../guides/configuration.md), [architecture](../architecture.md#uploads), [design.md](../design.md) section 3 (K7).

Status: Accepted, 2026-10-01. Built: `packages/bff/src/eneo_module_bff/limits.py`, `transport.py`, `app.py`.

## Context

FastAPI reads a body before it runs a route's dependencies and whatever the content type says, so an unauthenticated client could make the BFF read an unbounded body by claiming `multipart/form-data`. A file that streams holds one of the shared client's 100 connections for as long as it runs; with a 60 s wait for a free connection a busy pool made every API call a 502 after a minute.

## Decision

- A pure-ASGI middleware caps every request body of every route at `MAX_BODY_BYTES` (default 10 MiB): 413 at once when the declared length is above it, otherwise as soon as the stream passes it. It looks at no session, so it holds for a module's deliberately public routes too. No content type is exempt.
- A `Content-Length` that is not a length (not ASCII digits, longer than 19 characters, or 2**63 or more) is a 400 `Invalid Content-Length` on every route, before anything is read.
- Only `forward_upload` lifts the limit, to `MAX_UPLOAD_BYTES` (default 1 GiB), for its own request, after the route's dependencies and its own checks. The bytes that arrive are counted, so a `Content-Length` that lies, or a chunked body, gets no further.
- At most `MAX_CONCURRENT_STREAMS` (default 64) files stream at once; the next is a 503 with `Retry-After` at once, so the API keeps its connections.
- The shared client waits at most 5 s for a free connection (`pool=5`), so a busy pool is a quick 502.
- What Eneo answers is bounded too: the shared client stops at `MAX_RESPONSE_BYTES` (default 32 MiB, decoded) for the proxy and uploads, at 1 MiB for the answers that carry a token or a URL, and refuses an encoded answer (502 `upstream_too_large`). A file that streams is the one unbounded answer.
- The security-headers middleware is added after the body limit, so the 413 carries the headers.

## Consequences

- An unauthenticated request can still make the BFF buffer up to `MAX_BODY_BYTES` of a body, once per request, before a route's dependencies run (on a route that declares a body parameter).
- A module may not read a body past the cap except through `forward_upload`.
- A body that passes the limit while a response is already streaming ends the response, as if the client had gone: a 413 can no longer be sent.
- Measured on a 10 MiB body: one request raises the process's peak by about 21 MiB (`request.body()`) or 42 MiB (a JSON model), and 50 at once raise it by 13 to 16 MiB or 17 to 26 MiB each. A module that is public to the internet sets `MAX_BODY_BYTES` for its own largest JSON body.
- `serve()` stops within 8 s of SIGTERM with files still streaming, because Docker kills the container after 10 s.
