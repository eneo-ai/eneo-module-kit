# eneo-module-bff

Purpose: the Eneo module contract for a FastAPI BFF, packaged: login handoff, a server-side session with token refresh, a deny-by-default proxy to Eneo, upload forwarding, signed-file streaming, security headers and the built UI.
Read this when: you build a module's backend on it, change the package, or need its HTTP surface, public names or limits.
Related: [guide: build a module](../../docs/guides/build-a-module.md), [configuration](../../docs/guides/configuration.md), [architecture](../../docs/architecture.md), [security checklist](../../docs/guides/security-checklist.md), [decisions](../../docs/decisions/README.md), [repository README](../../README.md).

It is the security boundary between a browser and Eneo, so it holds no module-specific route.

## Example

```python
# main.py
from pathlib import Path

from fastapi import APIRouter, Depends

from eneo_module_bff import RESOURCE_ID, create_app, require_session, rule

router = APIRouter()  # the module's own routes, declared before an app exists


@router.get("/api/ping", dependencies=[Depends(require_session)])
async def ping() -> dict[str, bool]:
    return {"ok": True}


app = create_app(
    title="My module",
    routers=[router],
    proxy_rules=[
        rule("GET", r"flows/$"),
        rule({"GET", "POST"}, rf"flows/{RESOURCE_ID}/runs/$"),
    ],
    static_dir=Path(__file__).parent / "web" / "dist",
)

# Run it: python -c "from eneo_module_bff import serve; serve('main:app')"
```

Run from the module's directory, with the environment of [configuration](../../docs/guides/configuration.md) set. A walk-through, with a stub Eneo to sign in against, is in [build a module](../../docs/guides/build-a-module.md) and [local development](../../docs/guides/local-development.md).

## Public names

`eneo_module_bff.__all__` is exactly this list (`src/eneo_module_bff/__init__.py`, pinned by `tests/test_serve.py`).

| Name | What it is |
|---|---|
| `create_app(settings=None, *, title, routers, proxy_rules, forward_request_headers, static_dir, security_headers, http_client)` | Builds the app. `settings=None` loads the environment. |
| `serve(app, *, host="0.0.0.0", port=3001, **overrides)` | Runs it: one worker, no access log, bounded WebSocket buffers, stops within 8 s of SIGTERM. Refuses `workers=` and `access_log=`. |
| `Settings`, `Organization`, `load_settings(*, default_organization=None, home_path="/")` | Configuration and its start-up validation. |
| `require_session` | Route dependency: the caller's live session, else 401 with `X-Auth-Required: session` (a WebSocket handshake is refused). |
| `require_same_origin` | Route dependency: writes and WebSocket handshakes only from the module's own origin, else 403. |
| `upstream_auth_headers(request)` | The service key and `Authorization: Bearer <module-user token>`, for a call to Eneo from a module's route. |
| `rule(methods, pattern)`, `ProxyRule`, `RESOURCE_ID` | One allowed proxy route, its type, and `[^/]+`. |
| `forward_upload(request, upstream_path)` | Re-posts the one file of an upload to Eneo. |
| `stream_signed(request, *resource, mint_path, unavailable, inline_types=())` | Streams a file through Eneo's signed URL, with Range. |
| `ModuleSession`, `ModuleUser` | The session and user types. |
| `__version__` | `0.1.0`. |

## The proxy

The proxy exposes nothing until a module names a route with `rule(...)`. A path is matched as written, against the path after `/api/eneo/`. Of the browser's request headers only `eneo_module_bff.proxy.FORWARDED_REQUEST_HEADERS` (`Accept`, `Accept-Language`, `Content-Type`, `Idempotency-Key`, `If-Match`, `If-None-Match`) reach Eneo; `create_app(forward_request_headers=[...])` adds more, never a credential or framing header. `forward_upload` and `stream_signed` are functions for a module's own routes, behind `Depends(require_session)` (and `require_same_origin` for a write). `stream_signed` shows a file inline only if it is audio, video, a PDF or a common image (`png`, `jpeg`, `gif`, `webp`), and sends anything else as an attachment; `inline_types=[...]` widens that. At most `MAX_CONCURRENT_STREAMS` files stream at once (64): the next is a 503 with `Retry-After`, at once, so the connections a stream holds do not crowd out the API.

## Uploads

An upload route has no `File(...)` parameter, because FastAPI reads a route's body before it runs the route's dependencies, and a big body would be taken before the session is checked. `forward_upload` reads it itself, after them:

```python
@router.post("/api/upload/{flow_id}", dependencies=[Depends(require_session), Depends(require_same_origin)])
async def upload(flow_id: str, request: Request):
    return await forward_upload(request, f"flows/{flow_id}/files/")
```

The request must declare its `Content-Length` (else 411; one that is not a length is a 400), at most `MAX_UPLOAD_BYTES` (else 413), and hold one file part named `upload_file` and no other field (else 400), with no control character (C0, DEL, C1) or line or paragraph separator in the file name or content type (else 400). The name is forwarded as it came, a path included: Eneo owns where a file lands. Every request body is capped at `MAX_BODY_BYTES` (413) before a route sees it, whatever its content type, for all routes, a module's deliberately public ones too: the cap looks at no session. Only `forward_upload` lifts it, for its own request, to `MAX_UPLOAD_BYTES`; the bytes that arrive are counted, so a Content-Length that lies gets no further.

## A module's own routes

A module's own routes go in `routers=`. They are registered after the kit's own routes (`/health`, `/api/auth/*`, `/api/branding*`) and before the proxy and the built UI, so they win over both, including under `/api/eneo/`, and cannot replace a kit route. The kit does not add `require_session` to them: each route declares its own. Routes added to the app after `create_app` returns come after the proxy and the page and are not reached; use `routers=`.

## HTTP surface

Stable for the UI package and for any other frontend.

| Route | Purpose |
|---|---|
| `GET /health`, `GET /api/healthz` | `{"ok": true}` |
| `GET /api/auth/login?next=&renew=` | Starts the handoff: 303 to Eneo's `/module-login`, with a state cookie |
| `GET /api/auth/callback?ticket=&state=` | Finishes it: 303 to `next` with the session cookie set, or to `/?auth_error=<code>` |
| `POST /api/auth/logout` | Ends the session (same origin required) |
| `GET /api/auth/status` | `{"authenticated": false, "user": null}`, or `{authenticated, user, session_ends_in, refresh_in}` (`refresh_in` only while a refresh is still possible) |
| `GET /api/branding`, `GET /api/branding/logo/{light\|dark}` | The deployment's organisation, and its logos (404 when none is configured). No session needed. `logo` is `"custom"` (served here), `"default"` (the logo the module bundles in its own frontend: the kit serves no file for it) or null (the name as text). |
| the module's own routes (`routers=`) | Whatever the module declares; they win over the two rows below |
| `GET\|POST\|PATCH /api/eneo/{path}` | The allowlisted proxy |
| anything else | The built UI, if `static_dir` is given. `/api/*` and a missing file are 404 |

## Answers the package gives

| Status | When | Body |
|---|---|---|
| 400 | An upload is not exactly one file named `upload_file`, or has a control character or line separator in its file name or content type | `{"detail": ...}` |
| 400 | A `Content-Length` that is not a length (not digits, longer than 19 characters, or 2**63 or more). Header `Connection: close` | `{"detail": "Invalid Content-Length"}` |
| 401 | No live session. Header `X-Auth-Required: session` | `{"detail": "Not authenticated"}` |
| 403 | A write from another origin | `{"detail": "Invalid request origin"}` |
| 403 | The path is not named by a rule, or leaves its route | `{"detail": "Eneo resource is not exposed"}` |
| 400 | A forwarded request header (the proxy's, or `Range`, `If-Range`, `Accept` of a file stream) whose value is not ASCII | `{"detail": ...}` |
| 411 | An upload without `Content-Length` | `{"detail": ...}` |
| 414 | A path and query that, as sent to Eneo, are longer than the HTTP client writes (65,536 characters) | `{"detail": "Request URI too long"}` |
| 413 | A body over its limit. Header `Connection: close` | `{"detail": "Request body too large"}`, or `"Upload too large"` |
| 502 | Eneo cannot be reached | `{"error": "upstream_unreachable", ...}` |
| 502 | Eneo's answer is longer than `MAX_RESPONSE_BYTES`, or is content-encoded (the module asks for no encoding) | `{"error": "upstream_too_large", ...}` |
| 502 | Eneo answered with 301, 302, 303, 307 or 308 | `{"error": "upstream_redirect", ...}` |
| 502 | The answer to the signed-URL request cannot be used | `{"error": "upstream_invalid", ...}` |
| 503 | No free stream slot. Header `Retry-After: 2` | `{"error": "streams_busy", ...}` |
| 504 | A read or write of the upload to Eneo took longer than its timeout (per phase, not a total) | `{"error": "upstream_upload_timeout", ...}` |
| other | The proxy and an upload pass Eneo's own status and body through | as Eneo sent |

A callback that fails redirects to `/?auth_error=<code>`, with one of `invalid_state`, `exchange_unavailable`, `exchange_failed`, `exchange_invalid`, `validation_unavailable`, `validation_failed`, `validation_invalid`. Two Swedish query values are read by the UI package: `fel=utgangen` and `fel=annan-anvandare`.

## Configuration

`create_app()` reads the environment when it is not given a `Settings`. Every variable, its default and its check are in [configuration](../../docs/guides/configuration.md). The six required ones: `ENEO_BACKEND_URL`, `ENEO_PUBLIC_URL`, `MODULE_PUBLIC_URL`, `MODULE_KEY`, `ENEO_API_KEY`, `SESSION_SECRET`.

## Limits

- The dependencies are ranges with security floors (see `pyproject.toml`), not exact pins: pin and lock them in the module's own requirements.
- `serve()` stops within 8 s of SIGTERM even with files still streaming (Docker kills at 10 s). There is no total
  deadline per request: the timeouts are per phase (60 s a read or write, 5 s for a free connection, 10 s to connect, and
  an upload's own budget), and a total is added when a module needs one.
- One process, one replica: sessions live in memory. `serve()` fixes one worker and turns the access log off,
  because the callback URL carries a login ticket.
- Nothing in the package configures logging: a module sets up its own.

More in [design.md](../../docs/design.md) section 6 and the [security checklist](../../docs/guides/security-checklist.md).

## Layout

```
src/eneo_module_bff/   the package: one file per concern (see docs/architecture.md, "Where each fact lives")
tests/                 unittest, one file per module of the package
pyproject.toml         name, version, dependency ranges with security floors
```

## Develop

From the repository root:

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e "packages/bff[test]"
.venv/bin/python -m unittest discover -s packages/bff/tests -t packages/bff
```

CI (`.github/workflows/ci.yml`) runs the suite twice, at the lowest versions the ranges allow and at the newest, with `pip-audit` on each installed set.

The contract with Eneo and the HTTP surface in full are in [design.md](../../docs/design.md), sections 2 and 5.
