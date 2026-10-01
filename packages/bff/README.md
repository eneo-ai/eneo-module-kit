# eneo-module-bff

The Eneo module contract for a FastAPI BFF: the login handoff, a server-side session with token refresh, a
deny-by-default proxy to Eneo, upload forwarding and signed-file streaming, security headers and the built UI.
It is the security boundary between a browser and Eneo, so it holds no module-specific route.

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

The proxy exposes nothing until a module names a route with `rule(...)`. A path is matched as written, against the
path after `/api/eneo/`. Of the browser's request headers only `eneo_module_bff.proxy.FORWARDED_REQUEST_HEADERS`
(`Accept`, `Accept-Language`, `Content-Type`, `Idempotency-Key`, `If-Match`, `If-None-Match`) reach Eneo;
`create_app(forward_request_headers=[...])` adds more, never a credential or framing header. `forward_upload` and
`stream_signed` are functions for a module's own routes, behind `Depends(require_session)` (and `require_same_origin`
for a write). `stream_signed` shows a file inline only if it is
audio, video, a PDF or a common image (`png`, `jpeg`, `gif`, `webp`), and sends anything else as an attachment;
`inline_types=[...]` widens that. At most `MAX_CONCURRENT_STREAMS` files stream at once (64): the next is a 503 with
`Retry-After`, at once, so the connections a stream holds do not crowd out the API.

An upload route has no `File(...)` parameter, because FastAPI reads a route's body before it runs the route's
dependencies, and a big body would be taken before the session is checked. `forward_upload` reads it itself, after
them:

```python
@router.post("/api/upload/{flow_id}", dependencies=[Depends(require_session), Depends(require_same_origin)])
async def upload(flow_id: str, request: Request):
    return await forward_upload(request, f"flows/{flow_id}/files/")
```

The request must declare its `Content-Length` (else 411), at most `MAX_UPLOAD_BYTES` (else 413), and hold one file part
named `upload_file` and no other field (else 400), with no control character or line separator in the file name or content type
(else 400). Every request body is capped at `MAX_BODY_BYTES` (413) before a route sees it, whatever its content type,
for all routes, a module's deliberately public ones too: the cap looks at no session. Only `forward_upload` lifts it,
for its own request, to `MAX_UPLOAD_BYTES`; the bytes that arrive are counted, so a Content-Length that lies gets no
further.

A module's own routes go in `routers=`. They are registered after the kit's own routes (`/health`, `/api/auth/*`,
`/api/branding*`) and before the proxy and the built UI, so they win over both, including under `/api/eneo/`, and
cannot replace a kit route. The kit does not add `require_session` to them: each route declares its own. Routes added
to the app after `create_app` returns come after the proxy and the page and are not reached; use `routers=`.

## Configuration

`create_app()` reads the environment when it is not given a `Settings`.

| Variable | Default | |
|---|---|---|
| `ENEO_BACKEND_URL` | | Eneo's address from the module's network |
| `ENEO_PUBLIC_URL` | | Eneo's address from the browser |
| `MODULE_PUBLIC_URL` | | This module's address from the browser |
| `MODULE_KEY` | | Lowercase kebab-case, as registered in Eneo |
| `ENEO_API_KEY` | | The module's service key |
| `SESSION_SECRET` | | At least 32 characters |
| `ENEO_API_KEY_HEADER_NAME` | `X-API-Key` | |
| `COOKIE_SECURE` | `true` | `false` only for local development over http |
| `SESSION_MAX_AGE_MINUTES` | `480` | The session also ends at Eneo's own ceiling |
| `UPLOAD_PROXY_TIMEOUT_SECONDS` | `1800` | |
| `MAX_BODY_BYTES` | `10485760` (10 MiB) | The most of any request body, but an upload that `forward_upload` reads |
| `MAX_CONCURRENT_STREAMS` | `64` | How many files may stream at once through `stream_signed` |
| `MAX_UPLOAD_BYTES` | `1073741824` (1 GiB) | The most one upload may declare |
| `SHOW_ORGANIZATION`, `ORGANIZATION_NAME`, `ORGANIZATION_LOGO`, `ORGANIZATION_LOGO_DARK` | | The organisation shown beside the product name |

## Limits

- The dependencies are ranges with security floors (see `pyproject.toml`), not exact pins: pin and lock them in the module's own requirements.
- `serve()` stops within 8 s of SIGTERM even with files still streaming (Docker kills at 10 s). There is no total
  deadline per request: the timeouts are per phase (60 s a read or write, 5 s for a free connection, 10 s to connect, and
  an upload's own budget), and a total is added when a module needs one.
- One process, one replica: sessions live in memory. `serve()` fixes one worker and turns the access log off,
  because the callback URL carries a login ticket.
- Nothing in the package configures logging: a module sets up its own.

The contract with Eneo and the HTTP surface are in `docs/design.md`, sections 2 and 5, of the repository.
