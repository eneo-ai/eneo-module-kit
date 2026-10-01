# Build a module on the BFF

Purpose: take a backend from nothing to a module that signs in through Eneo, serves its own routes and proxies a named set of Eneo routes.
Read this when: you are writing a module's `main.py`, adding a route, an upload, a file download or a proxy rule.
Related: [configuration](configuration.md), [local development](local-development.md), [security checklist](security-checklist.md), [BFF package README](../../packages/bff/README.md), [architecture](../architecture.md).

`template/` holds the result of steps 1 to 4 ready-made, with a UI and a stub Eneo: [new module](new-module.md) starts from it. This guide is the backend in detail. The module's own code stays in the module: its routes, its allowlist, its protocols.

## 1. Install the package

`eneo-module-bff` is not on a package index yet (version 0.1.0 is unreleased). From a checkout of this repository:

```bash
pip install -e /path/to/eneo-module-kit/packages/bff
```

Python 3.12 or newer. Its dependencies are ranges with security floors, not pins (`packages/bff/pyproject.toml`): pin and lock them in your module's own requirements. Until the first release a module is expected to pin the package to a commit of this repository (see [design.md](../design.md) section 7).

## 2. Write `main.py`

```python
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
    static_dir=Path(__file__).parent / "web" / "dist",  # leave it out until there is a built UI
)
```

The template builds its app in a function instead, `build_app(settings=None, *, static_dir=..., http_client=None)`, so a test can pass its own settings and client, and runs it with `serve('main:build_app', factory=True)`. Prefer that shape for a module with tests. Run `main:app` as above, with the environment of [configuration](configuration.md) set:

```bash
python -c "from eneo_module_bff import serve; serve('main:app')"
```

`serve()` listens on port 3001, runs one worker and keeps the access log off. It refuses `workers=` and `access_log=`. Other uvicorn options pass through (`serve('main:app', port=3464)`).

`static_dir` must hold an `assets/` directory, or the app refuses to start. A request for a path under `/api`, or for a file that is not there, is a 404, never the page.

## 3. What `create_app` gives you

| Route | Source |
|---|---|
| `GET /health`, `GET /api/healthz` | `{"ok": true}` |
| `GET /api/auth/login`, `GET /api/auth/callback`, `POST /api/auth/logout`, `GET /api/auth/status` | the login handoff and the session |
| `GET /api/branding`, `GET /api/branding/logo/{light\|dark}` | the organisation of the deployment |
| your `routers=` | whatever you declare |
| `GET\|POST\|PATCH /api/eneo/{path}` | the proxy, for your `proxy_rules=` only |
| anything else | the built UI, if `static_dir` is given |

Your routes are matched after the kit's own and before the proxy and the page. They win over the proxy (also under `/api/eneo/`) and cannot replace a kit route. Add routes with `routers=`: a route added to the app after `create_app` returns is never reached. Details: [architecture](../architecture.md#how-the-app-is-assembled).

## 4. Guard every route you write

The kit adds no guard to your routes. Declare them yourself:

| Route | Dependencies |
|---|---|
| Reads | `Depends(require_session)` |
| Writes (`POST`, `PUT`, `PATCH`, `DELETE`) | `Depends(require_session)` and `Depends(require_same_origin)` |
| WebSocket | both, in `dependencies=` or as parameters. A handshake acts for the user, so it is checked like a write. |

```python
from eneo_module_bff import require_same_origin, require_session

@router.post("/api/notes", dependencies=[Depends(require_session), Depends(require_same_origin)])
async def add_note() -> dict[str, bool]:
    return {"ok": True}
```

`require_session` answers 401 with `X-Auth-Required: session`; `require_same_origin` answers 403. A route you leave public on purpose still gets the request body cap, because the cap looks at no session.

To call Eneo from your own route, use `upstream_auth_headers(request)`: it returns the service key header and `Authorization: Bearer <module-user token>` for the signed-in user, and works only after `require_session` has run.

Add a test that fails when someone forgets a guard: copy `unguarded_routes` from `packages/bff/tests/test_deps.py` (the template already has it: `backend/tests/guards.py` and `test_routes.py`), call it with your router(s) and assert it returns `[]`. It walks `router.routes`, finds a guard however deep it sits (route `dependencies=`, a parameter, or a dependency of your own that depends on `require_session`), and reports a route it cannot check (a mount, a nested include) instead of passing it.

## 5. Name the Eneo routes you expose

The proxy denies everything until you name a route. A rule is a method set and a regular expression, matched against the whole path after `/api/eneo/`, as written:

```python
from eneo_module_bff import RESOURCE_ID, rule

proxy_rules = [
    rule("GET", r"flows/$"),                                   # GET  /api/eneo/flows/
    rule({"GET", "POST"}, rf"flows/{RESOURCE_ID}/runs/$"),     # one id, then runs/
]
```

- `RESOURCE_ID` is `[^/]+`: one path segment.
- The pattern is matched with `fullmatch`, and a trailing slash counts: `flows/` and `flows` are different paths.
- A path with a `.` or `..` segment (written or percent-encoded), `?`, `#`, a control character or a backslash is refused before any rule is tried. What a rule matched is sent to Eneo encoded as that one path (a literal `%` in an id is sent as `%25`), so an id can never become a separator upstream.
- A forwarded header whose value is not ASCII is a 400, and a URL longer than the HTTP client writes (65,536 characters once the path is encoded for Eneo) is a 414, on the proxy, uploads and file streams: Eneo hears nothing of either.
- The proxy forwards `GET`, `POST` and `PATCH`, the query string, and a body of at most `MAX_BODY_BYTES`. A different method is not routed.
- Of the browser's request headers only `Accept`, `Accept-Language`, `Content-Type`, `Idempotency-Key`, `If-Match` and `If-None-Match` reach Eneo. Add more with `create_app(forward_request_headers=["X-Thing"])`. A credential or framing header (`Authorization`, `Cookie`, `Origin`, `Referer`, `X-API-Key`, `Proxy-Authorization`, `Host`, `Content-Length`, `Transfer-Encoding`, `Connection`, `Keep-Alive`, `TE`, `Trailer`, `Upgrade`) is a `ValueError` when the app is built. The service key and the module-user token are always set by the module, whatever the browser sent.
- Eneo's `Set-Cookie` and `Location` never reach the browser. An answer from Eneo with 301, 302, 303, 307 or 308 is a 502 `upstream_redirect`: the module follows none.

## 6. Forward an upload

An upload route has no `File(...)` parameter: FastAPI reads a route's body before it runs the route's dependencies, so a big body would be taken before the session is checked. `forward_upload` reads it itself, after them:

```python
from fastapi import Request
from eneo_module_bff import forward_upload

@router.post("/api/upload/{flow_id}", dependencies=[Depends(require_session), Depends(require_same_origin)])
async def upload(flow_id: str, request: Request):
    return await forward_upload(request, f"flows/{flow_id}/files/")
```

The path is relative to `{ENEO_BACKEND_URL}/api/v1/`. The browser sends a `multipart/form-data` body with one file part named `upload_file` and no other field. The file name is forwarded as it came, a path included: Eneo owns where a file lands.

| Request | Answer |
|---|---|
| No `Content-Length` | 411 |
| A `Content-Length` that is not a length (not digits, longer than 19 characters, or 2**63 or more) | 400 |
| Above `MAX_UPLOAD_BYTES` | 413 |
| Not exactly one file named `upload_file`, or a control character (C0, DEL, C1) or a line or paragraph separator in its file name or content type | 400 |
| The path leaves its route | 403 |
| Eneo does not answer in time (`UPLOAD_PROXY_TIMEOUT_SECONDS`, or the lower `X-Upload-Timeout-Seconds`, never below 60 s) | 504 |
| Eneo cannot be reached, or answers with a redirect | 502 |
| Otherwise | Eneo's status, body and `Content-Type` |

## 7. Stream a signed file

Eneo hands out a short-lived signed URL per file. The browser must not use it (the page's CSP allows only same-origin media, and the URL is a bearer credential). `stream_signed` mints it with your credentials, keeps it for the session, and streams the bytes through with Range support:

```python
from eneo_module_bff import stream_signed

@router.get("/api/runs/{run_id}/audio", dependencies=[Depends(require_session)])
async def audio(run_id: str, request: Request):
    return await stream_signed(
        request,
        run_id,                                       # every id that went into mint_path
        mint_path=f"runs/{run_id}/audio/signed-url/",  # example: the Eneo route (POST) that returns the signed URL
        unavailable="The recording is not available",   # the message when Eneo gives none
    )
```

The mint route must answer JSON with `url`, and may give `expires_at`; anything else is a 502 `upstream_invalid`. The file is shown inline only if it is audio, video, a PDF or a PNG, JPEG, GIF or WebP image, and is an attachment otherwise, always with `X-Content-Type-Options: nosniff` and `Cache-Control: private, no-store`. Widen it with `inline_types=["text/plain", "image/bmp"]` (a media type or `type/*`); never add one that can run script (`text/html`, `image/svg+xml`). At most `MAX_CONCURRENT_STREAMS` files stream at once: the next gets 503 with `Retry-After` at once.

## 8. Settings of your own module

The kit's settings are in [configuration](configuration.md). Build the settings yourself when you change `home_path` or `default_organization`:

```python
app = create_app(load_settings(home_path="/flows"), routers=[router])
```

## 9. Test it

`create_app(settings, http_client=...)` takes a `Settings` built in the test and an HTTP client of your own, so a test builds an app per case and no Eneo is needed. The template's `backend/tests/test_app.py` is a module's example: it builds the app with a temporary `static_dir`, a mock transport for Eneo and a session made in the store. The kit's own tests do this too: see `packages/bff/tests/test_app.py` for the app, `test_proxy.py` (`FakeProxyClient`) for a fake client that records its calls, and `test_auth.py` for fake token answers. An injected client is never closed by the app.

```bash
python -m unittest discover -s tests
```

## What stays in your module

Its route allowlist, its domain routes and protocols (a WebSocket relay, for example: the kit has no relay helper), its own copy and recovery messages, and its draft handling. Anything that would be the same in every module belongs in the kit instead: raise it in this repository.
