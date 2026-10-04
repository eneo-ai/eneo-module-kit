# Architecture

Purpose: show how the kit's parts fit together and how a request moves through the BFF, in diagrams that are the source of truth.
Read this when: you are starting to work on `packages/bff`, writing a module on it, or reviewing a change to login, the proxy, uploads or file streaming.
Related: [README](../README.md), [docs index](README.md), [guides](guides/build-a-module.md), [decisions](decisions/README.md), [design (long form)](design.md), [BFF package](../packages/bff/README.md), [glossary](glossary.md).

Every claim about code names the file, never a line. If a diagram and the code disagree, the code wins: fix the diagram.

## What is built

| Part | Path | Status |
|---|---|---|
| BFF package `eneo-module-bff` | `packages/bff/` | Built and tested. Version 0.1.0, not released. |
| UI package `@eneo-ai/module-kit` | `packages/ui/` | Planned. Not in the repository yet. |
| Template (the smallest working module) | `template/` | Planned. Not in the repository yet. |
| Module contract, design, decisions, guides | `docs/` | Current. |

The diagrams below describe the BFF as built, except the last one, which is the target deployment of a module made from the planned template.

## Parts and package structure

Look at: which files import which, and what a module imports from the package.

```mermaid
flowchart TB
  module["A module: main.py and its UI"]
  subgraph bff["packages/bff/src/eneo_module_bff (built)"]
    app["app.py: create_app"]
    serve["serve.py: serve"]
    deps["deps.py: require_session, require_same_origin"]
    transport["transport.py: forward_upload, stream_signed"]
    proxy["proxy.py: rule, proxy_router"]
    limits["limits.py: body limit"]
    upstream["upstream.py: make_client"]
    auth["auth.py: login, session store, refresh"]
    web["web.py: security headers, built UI"]
    branding["branding.py: /api/branding"]
    settings["settings.py: Settings, load_settings"]
  end
  ui["packages/ui (planned)"]
  tpl["template/ (planned)"]
  module --> app
  module --> serve
  module --> deps
  module --> transport
  app --> auth
  app --> proxy
  app --> limits
  app --> web
  app --> branding
  app --> settings
  app --> upstream
  upstream --> settings
  proxy --> deps
  transport --> deps
  transport --> proxy
  transport --> limits
  transport --> auth
  deps --> auth
  auth --> settings
  ui -.-> module
  tpl -.-> module
```

The dashed arrows are planned: a module will import the UI package and start as a copy of the template. The BFF holds the module contract with Eneo and no route of any module.

## System context

Look at: the two addresses of Eneo. The browser reaches Eneo at `ENEO_PUBLIC_URL`; the module reaches it at `ENEO_BACKEND_URL`, on the module network.

```mermaid
flowchart LR
  user["Browser"]
  subgraph net["Module network"]
    mod["Module: BFF and UI, port 3001"]
  end
  login["Eneo, public address: /module-login"]
  api["Eneo, backend address: /api/v1"]
  user -->|"HTTPS, opaque session cookie"| mod
  user -->|"login redirect"| login
  mod -->|"service key and module-user token"| api
```

The browser never holds a credential for Eneo. See [auth](#login-handoff) below and the contract in [design.md](design.md) section 2.

## How the app is assembled

Look at: the order a request meets things. Routes match in registration order, so a module's route wins over the proxy and the page, and cannot replace a kit route. An arrow means "no earlier route matched".

```mermaid
flowchart TB
  req["Request"] --> sec["Security headers on every response"]
  sec --> lim["Body limit: 413 over the cap"]
  lim --> kit["Kit routes: /health, /api/healthz, /api/auth/*, /api/branding*"]
  kit --> own["The module's routers, in the order given"]
  own --> prx["Proxy: /api/eneo/*"]
  prx --> assets["Files of the built UI, from the index made at start"]
  assets --> page["Any other path without a file name: index.html. A missing file, an unsafe name and /api/* are 404"]
```

Source: `packages/bff/src/eneo_module_bff/app.py` (`create_app`). Routes added to the app after `create_app` returns come after the page and are never reached: use `routers=`. The security-headers middleware is the outermost, so even the body limit's 413 carries the headers.

## Login handoff

Look at: the two cookies. The state cookie binds the login to this browser for five minutes; the session cookie is an opaque id, and the token it stands for stays in the module's memory.

```mermaid
sequenceDiagram
  participant B as Browser
  participant M as Module
  participant L as Eneo login
  participant A as Eneo API
  B->>M: GET /api/auth/login?next=/page
  M-->>B: 303 to Eneo /module-login, signed state cookie
  B->>L: GET /module-login with module_key, redirect_uri, state
  L-->>B: redirect to the callback with ticket and state
  B->>M: GET /api/auth/callback?ticket=...&state=... with the state cookie
  M->>M: state must equal the one in the cookie
  M->>A: POST /api/v1/module-auth/token/ with the service key and the ticket
  A-->>M: module-user token, expiry, user
  M->>A: GET /api/v1/module-auth/MODULE_KEY/session/ with both credentials
  A-->>M: module key, tenant, user
  M->>M: store the session in memory
  M-->>B: 303 to next, session cookie set, state cookie deleted
```

| Fact | Value | Where |
|---|---|---|
| Session cookie | `eneo_module_session`, random id, HttpOnly, SameSite=Lax, `Secure` unless `COOKIE_SECURE=false`, path `/`, ends with the session | `auth.py` |
| State cookie | `eneo_module_login_state`, signed with `SESSION_SECRET`, five minutes, path `/api/auth/callback`, deleted by the callback | `auth.py` |
| Where login returns | `next` if it is a path of this module of at most 512 characters with no backslash and no control character (a tab, CR or LF would make `/<tab>/host` read as `//host`), else `Settings.home_path` (default `/`) | `auth.py` (`module_path`) |
| Callback failure | 303 to `/?auth_error=<code>`: `invalid_state`, `exchange_unavailable`, `exchange_failed`, `exchange_invalid`, `validation_unavailable`, `validation_failed`, `validation_invalid` | `auth.py` |
| Session end | `min(SESSION_MAX_AGE_MINUTES, Eneo's session_expires_at)` | `auth.py` |
| A new login | Ends the session the browser held | `auth.py` (`callback`) |
| Renewal (`?renew=true`) | Binds the login to the user signed in now. No session left: 303 to `next` with `fel=utgangen`. Another user signs in: the old session is kept and the page gets `fel=annan-anvandare` | `auth.py` |

## Session lifecycle and refresh

Look at: the three outcomes of a refresh. Only a refusal from Eneo ends the session; an Eneo that cannot answer does not.

```mermaid
flowchart TB
  r["Request with the session cookie"] --> f{"Session in the store and not expired?"}
  f -->|"no"| u["401, X-Auth-Required: session"]
  f -->|"yes"| d{"Refresh due?"}
  d -->|"no"| ok["Request continues"]
  d -->|"yes"| s["One refresh per session, other requests wait for it"]
  s --> e["POST /api/v1/module-auth/MODULE_KEY/token/refresh/ with both credentials"]
  e -->|"200, same user and tenant"| n["New token kept, next refresh at half its life"]
  e -->|"408, 429, 5xx, no answer, or an unexpected error here"| k["Keep the valid token, ask again in 10 s"]
  e -->|"any other refusal, an unusable answer, another identity"| g["Session deleted"]
  n --> ok
  k --> ok
  g --> u
```

A refresh is due at half the token's lifetime, and only while a new token could outlive the current one (the current one does not already reach the session end). `GET /api/auth/status` reports `refresh_in` and `session_ends_in`, so a page that sends no other request can ask again in time. A logout during a refresh stays a logout. Source: `auth.py` (`ModuleAuth._live_session`, `_refresh`, `_refresh_token`).

## A proxied request

Look at: the order of the checks. Nothing reaches Eneo until the session, the origin and the allowlist have each said yes.

```mermaid
flowchart TB
  r["Browser: GET, POST or PATCH /api/eneo/path"] --> l{"Content-Length above the cap?"}
  l -->|"yes"| e413["413"]
  l -->|"no"| s{"Valid session?"}
  s -->|"no"| e401["401, X-Auth-Required: session"]
  s -->|"yes"| o{"Origin is the module's? Only checked for writes"}
  o -->|"no"| e403a["403 Invalid request origin"]
  o -->|"yes"| a{"Path stays on its route, and a rule names this method and path?"}
  a -->|"no"| e403b["403 Eneo resource is not exposed"]
  a -->|"yes"| h["Headers: the allowlist from the browser, then service key and module-user token"]
  h --> b["Read the body, at most MAX_BODY_BYTES: 413 when the stream passes it"]
  b --> up["Call Eneo at ENEO_BACKEND_URL/api/v1/path with the query string"]
  up -->|"no answer"| e502a["502 upstream_unreachable"]
  up -->|"301, 302, 303, 307, 308"| e502b["502 upstream_redirect"]
  up -->|"any other status"| resp["Same status and body. Set-Cookie, Location, Cache-Control and Eneo's policy headers dropped. Cache-Control private, no-store. JSON of 1 KiB or more gzipped for a browser that accepts it"]
```

Source: `proxy.py` (`proxy_router`, `leaves_route`, `FORWARDED_REQUEST_HEADERS`) and `limits.py`. A path that could reach another Eneo route (a `.` or `..` segment written or percent-encoded, `?`, `#`, a control character, a backslash) is a 403 before any rule is tried.

## Uploads

Look at: where the body is first read. An upload route has no `File(...)` parameter, so `Depends(require_session)` has run before one byte of the body is read.

```mermaid
sequenceDiagram
  participant B as Browser
  participant R as Module route
  participant F as forward_upload
  participant A as Eneo API
  B->>R: POST multipart, Content-Length declared
  R->>R: body limit: 413 if the declared length is above the ceiling
  R->>R: dependencies: require_session 401, require_same_origin 403
  R->>F: forward_upload(request, upstream_path)
  F->>F: path leaves its route 403, no Content-Length 411, above MAX_UPLOAD_BYTES 413
  F->>F: raise this request's limit to MAX_UPLOAD_BYTES, then parse the multipart
  F->>F: not exactly one file named upload_file, or a control or line-separator character in its name or type 400
  F->>A: POST /api/v1/upstream_path with one file and both credentials
  A-->>F: status and body
  F-->>B: same status, body and Content-Type. 504 when a read or write timeout runs out, 502 if unreachable or redirected
```

Source: `transport.py` (`forward_upload`) and `limits.py`. The read timeout and the write timeout of the call to Eneo are each `UPLOAD_PROXY_TIMEOUT_SECONDS`, lowered (never below 60 s) by the request's `X-Upload-Timeout-Seconds` header. They are per phase, as for every call: no total deadline bounds an upload.

## Signed files

Look at: what the browser never sees. Eneo's signed URL is a bearer URL to the file; the module mints it, keeps it with the session, and streams the bytes through.

```mermaid
sequenceDiagram
  participant B as Browser
  participant S as stream_signed
  participant K as Session store
  participant A as Eneo API
  B->>S: GET the module's file route, optional Range
  S->>S: ids leave their route 403, no free stream slot 503 with Retry-After
  S->>K: signed URL for this session and mint path?
  K-->>S: the URL, or none
  S->>A: POST mint path with both credentials, if none or within 60 s of its end
  A-->>S: JSON with url and expires_at, else 502 upstream_invalid
  S->>K: remember it, only while the session lives
  S->>A: GET the signed URL on ENEO_BACKEND_URL with Range, If-Range, Accept, no credentials
  A-->>S: 200 or 206 stream
  S-->>B: bytes streamed through, nosniff, private no-store, attachment unless the type may be shown inline
```

Source: `transport.py` (`stream_signed`) and `auth.py` (`ModuleSessionStore.signed_url`). Eneo's answer is closed when the response ends, however it ends (the file finished, an error in the body, the browser left, a cancellation): in a `finally` around the whole response, shielded from the cancellation and bounded at 2 s, and a failing close is logged and changes nothing. The stream slot is returned after the close. At most `MAX_CONCURRENT_STREAMS` files stream at once. An entry in the session store ends with its session: logout, expiry, a refresh that ends it, or a new login.

## Target deployment

Look at: one container, one process, one replica. This is the deployment the planned template builds. The BFF half is built: `serve()` fixes one worker and turns the access log off.

```mermaid
flowchart LR
  user["Browser"]
  subgraph inst["Eneo installation"]
    subgraph box["Module container"]
      uv["uvicorn: one worker, port 3001, no access log"]
      app["create_app: BFF routes, proxy, session store in memory"]
      dist["web/dist: the built UI, served as files"]
    end
    eneo["Eneo backend"]
  end
  user -->|"HTTPS, MODULE_PUBLIC_URL"| uv
  user -->|"login redirect, ENEO_PUBLIC_URL"| eneo
  uv --> app
  app --> dist
  app -->|"ENEO_BACKEND_URL, both credentials"| eneo
```

| Fact | Status |
|---|---|
| `serve()` runs one uvicorn worker, no access log (the callback URL carries a ticket), WebSocket buffers bounded, stops within 8 s of SIGTERM | Built (`serve.py`) |
| Port 3001, `GET /health` answers `{"ok": true}` | Built (`serve.py`, `app.py`) |
| One container on the module network, no outbound internet | Contract from [design.md](design.md) section 2 |
| Dockerfile: Node builds `web/dist`, a Python slim runtime image with no Node, non-root, `HEALTHCHECK` on `/health` | Planned (template) |
| Sessions are process-local: one replica. More needs sticky sessions or a shared store | Decided when a module needs it |

## Where each fact lives

| Topic | File in `packages/bff/src/eneo_module_bff/` | Tests in `packages/bff/tests/` |
|---|---|---|
| Settings and start-up validation | `settings.py` | `test_settings.py` |
| Login, session store, refresh, same-origin | `auth.py` | `test_auth.py` |
| Route dependencies | `deps.py` | `test_deps.py` |
| Proxy, allowlist, `leaves_route` | `proxy.py` | `test_proxy.py` |
| Uploads and signed files | `transport.py` | `test_transport.py` |
| Body limit | `limits.py` | `test_limits.py` |
| The client to Eneo (no cookies, bounded answers), the paths and headers sent to it | `upstream.py`, `proxy.py` | `test_upstream_client.py`, `test_upstream_answers.py`, `test_upstream_paths.py`, `test_mint_answers.py` |
| Where login returns | `auth.py` | `test_login_redirect.py` |
| Security headers, built UI | `web.py` | `test_web.py` |
| Branding routes | `branding.py` | `test_branding.py` |
| App factory | `app.py` | `test_app.py` |
| Running the server | `serve.py` | `test_serve.py`, `test_shutdown.py` |
| Public names and version | `__init__.py` | `test_serve.py` (the names), `test_package.py` (the version) |
