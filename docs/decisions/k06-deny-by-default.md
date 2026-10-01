# K6. Deny by default

Purpose: record the decision why the proxy exposes nothing until a module names a route, and forwards only a short list of headers.
Read this when: you add a proxy rule, a forwarded header, or a redirect or cookie behaviour to the proxy.
Related: [decisions](README.md), [build a module](../guides/build-a-module.md#5-name-the-eneo-routes-you-expose), [security checklist](../guides/security-checklist.md), [architecture](../architecture.md#a-proxied-request).

Status: Accepted, 2026-10-01. Built: `packages/bff/src/eneo_module_bff/proxy.py`.

## Context

Eneo serves every user of a module on one connection pool, and every call carries the module's service key. A proxy that forwards whatever the browser sends would let a browser reach any Eneo route and set any header (`Forwarded`, `Transfer-Encoding`) under that key.

## Decision

Deny by default, for paths and for headers.
- The kit ships the mechanism and no allowlist entries; each module names its routes with `rule(...)`.
- Of the browser's request headers only `Accept`, `Accept-Language`, `Content-Type`, `Idempotency-Key`, `If-Match` and `If-None-Match` reach Eneo. A module may add to the list, but never a credential or framing header. The credentials are set by the module from the session.
- Eneo's `Location` and `Set-Cookie` never reach the browser. A redirect from Eneo (301, 302, 303, 307, 308) is a 502 `upstream_redirect`: the module follows none and no route of a module is expected to redirect.

## Consequences

- A path that could reach another Eneo route (`.` or `..` segments, written or percent-encoded, `?`, `#`, a control character, a backslash) is a 403 before any rule is tried.
- The path Eneo receives is the path the rule matched, encoded as that one logical path: a `%2F` that the browser wrote as `%252F` is an id, and goes on as `%252F`, so Eneo does not decode it into a separator. This holds for the proxy, uploads and signed-URL requests.
- The client that calls Eneo stores and sends no cookie (`upstream.make_client`): its jar would be shared by every user.
- Every module has to write its allowlist, as narrow as it can be.
- A header a module needs and the list lacks is added with `create_app(forward_request_headers=[...])`.
