# Architecture

Purpose: show how the kit's parts fit together and how a request moves through the BFF, in diagrams that are the source of truth.
Read this when: you are starting to work on `packages/bff`, writing a module on it, or reviewing a change to login, the proxy, uploads or file streaming.
Related: [README](../README.md), [docs index](README.md), [guides](guides/build-a-module.md), [decisions](decisions/README.md), [design (long form)](design.md), [BFF package](../packages/bff/README.md), [glossary](glossary.md).

Every claim about code names the file, never a line. If a diagram and the code disagree, the code wins: fix the diagram.

## What is built

| Part | Path | Status |
|---|---|---|
| BFF package `eneo-module-bff` | `packages/bff/` | Built and tested. Version 0.1.0, not released. |
| UI package `@eneo-ai/module-kit` | `packages/ui/` | Built and tested: theme, colour mode, providers, page shell, brand. Version 0.1.0, not released. Planned: the session client (sign-in screen, warning before the login ends, the cover while signed out) and the Astryx integration. |
| Template (the smallest working module) | `template/` | Built and tested: backend, stub Eneo, Vite app, Dockerfile, compose file, module CI, agent files. Its `RequireSession` is a minimal stand-in for the session client. |
| Module contract, design, decisions, guides | `docs/` | Current. |

The first release of both packages is planned. Until then neither is published, and a module installs them from a checkout of this repository ([new module](guides/new-module.md#before-the-first-release)).

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
  ui["packages/ui: providers, shell, brand, theme (built)"]
  tpl["template/ (built)"]
  module --> app
  module --> serve
  module --> deps
  module --> transport
  module -->|"web/ imports"| ui
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
  tpl -.->|"a module starts as a copy"| module
```

A module imports both packages and copies none of their code. The BFF holds the module contract with Eneo and no route of any module. The UI package holds no page of any module and imports no router. The dashed arrow is a copy, not an import.

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
  prx --> assets["/assets: files of the built UI"]
  assets --> page["Any other path: index.html. A missing file and /api/* are 404"]
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
  r["Browser: GET, POST or PATCH /api/eneo/path"] --> l{"Content-Length not a length, or above the cap?"}
  l -->|"yes"| e413["400 or 413"]
  l -->|"no"| s{"Valid session?"}
  s -->|"no"| e401["401, X-Auth-Required: session"]
  s -->|"yes"| o{"Origin is the module's? Only checked for writes"}
  o -->|"no"| e403a["403 Invalid request origin"]
  o -->|"yes"| a{"Path stays on its route, and a rule names this method and path?"}
  a -->|"no"| e403b["403 Eneo resource is not exposed"]
  a -->|"yes"| h["Headers: the allowlist from the browser, then service key and module-user token. A value that is not ASCII is a 400"]
  h --> b["Read the body, at most MAX_BODY_BYTES: 413 when the stream passes it"]
  b --> up["Call Eneo at ENEO_BACKEND_URL/api/v1/path, the path encoded as the one the rule matched, with the query string"]
  up -->|"a URL the client will not write"| e414["414"]
  up -->|"answer past MAX_RESPONSE_BYTES, or encoded"| e502c["502 upstream_too_large"]
  up -->|"no answer"| e502a["502 upstream_unreachable"]
  up -->|"301, 302, 303, 307, 308"| e502b["502 upstream_redirect"]
  up -->|"any other status"| resp["Same status and body. Set-Cookie and Location dropped. Cache-Control private, no-store if Eneo sent none"]
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
  F-->>B: same status, body and Content-Type. 504 on timeout, 502 if unreachable or redirected
```

Source: `transport.py` (`forward_upload`) and `limits.py`. The time budget is `UPLOAD_PROXY_TIMEOUT_SECONDS`, lowered (never below 60 s) by the request's `X-Upload-Timeout-Seconds` header.

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
  A-->>S: JSON of at most 1 MiB with url and expires_at, else 502 upstream_invalid
  S->>K: remember it, only while the session lives
  S->>A: GET the signed URL on ENEO_BACKEND_URL with Range, If-Range, Accept, no credentials
  A-->>S: 200 or 206 stream
  S-->>B: bytes streamed through, nosniff, private no-store, attachment unless the type may be shown inline
```

Source: `transport.py` (`stream_signed`) and `auth.py` (`ModuleSessionStore.signed_url`). The stream slot is released when the response ends, however it ends. At most `MAX_CONCURRENT_STREAMS` files stream at once. An entry in the session store ends with its session: logout, expiry, a refresh that ends it, or a new login.

## The UI app and its layers

Look at: the nesting of providers, top to bottom. The kit's UI package supplies the middle (colour mode, theme, words, links, branding, the shell); the module supplies the router and the pages.

```mermaid
flowchart TB
  main["main.tsx: five stylesheets in order, then render"] --> router["BrowserRouter: the module's"]
  router --> mp["ModuleProviders: colour mode, Eneo theme, Swedish words, links"]
  mp --> bp["BrandingProvider: asks /api/branding once"]
  bp --> app["App: the module's routes"]
  app --> rs["RequireSession: asks /api/auth/status"]
  rs --> frame["Frame: ModuleShell, Brand, Layout"]
  frame --> page["A page, built from Astryx components"]
```

| Layer | Where | Owned by |
|---|---|---|
| Stylesheets: `layers.css`, Astryx's `reset.css` and `astryx.css`, `theme.css`, `base.css` | imported in `template/web/src/main.tsx`, in this order | the module imports, the kit and Astryx supply |
| Providers, shell, brand, theme, colour mode | `packages/ui/src/` | the UI package |
| Router, pages, `Frame`, `RequireSession`, `AccountMenu`, `config.ts` | `template/web/src/` | the module |
| Components | `@astryxdesign/core`, pinned to an exact version | Astryx |
| Design-system fixes | `packages/ui/src/theme/eneo.theme.ts`, then `npm run theme:build` | the UI package, once, for every module |

The UI is a static app: the BFF serves its built files ([K4](decisions/k04-static-ui-served-by-the-bff.md)), so nothing is rendered on a server and the colour mode is read in the browser on the first render ([K9](decisions/k09-colour-mode-in-the-ui-package.md)). Detail: [UI package](guides/ui-package.md).

## Where the organisation's branding enters

Look at: the deployment sets the organisation once, in the BFF's environment; the page learns it from `/api/branding`; the module chooses its own product name and bundled logo.

```mermaid
flowchart LR
  env["Deployment: ORGANIZATION_NAME, ORGANIZATION_LOGO, ORGANIZATION_LOGO_DARK, SHOW_ORGANIZATION"] --> settings["BFF: Settings.organization, logo files read at start"]
  settings --> api["/api/branding and /api/branding/logo/light or dark, no session"]
  api --> prov["UI: BrandingProvider asks once, with a 2 s deadline"]
  prov --> brand["Brand: the mark and the product name in the top bar"]
  mod["Module: PRODUCT_NAME, and defaultLogo if it bundles one"] --> brand
```

Until the answer comes, or when it fails, the lockup is the product name alone. The kit ships no organisation's mark. See [K10](decisions/k10-branding-without-templating.md) and [UI package: branding](guides/ui-package.md#branding).

## The template and its image

Look at: two builds in one image. Node builds the UI to static files, Python installs the backend's packages, and only Python and the built files reach the runtime image.

```mermaid
flowchart LR
  subgraph build["Build"]
    web["Stage web: node 22, npm install, npm run build, giving web/dist"]
    pkgs["Stage python-packages: pip install into /install"]
  end
  kit["Build context kit: packed UI package and a copy of the BFF"] -.->|"until the release"| web
  kit -.-> pkgs
  web --> run["Runtime: python 3.12 slim, user uid 10001, no Node"]
  pkgs --> run
  run --> cmd["serve main:build_app on port 3001, HEALTHCHECK on /health"]
```

The dotted arrows are the pre-release route: without the `kit` build context the Dockerfile installs the pinned versions, which do not exist yet ([new module](guides/new-module.md#6-build-the-image)). Source: `template/Dockerfile`.

## Deployment of a module

Look at: one container, one process, one replica. This is what the template builds and what `serve()` fixes: one worker, no access log.

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
| Dockerfile: Node builds `web/dist`, a Python slim runtime image with no Node, non-root, `HEALTHCHECK` on `/health` | Built (`template/Dockerfile`) |
| One container on the module network, no outbound internet | Contract from [design.md](design.md) section 2 |
| Sessions are process-local: one replica. More needs sticky sessions or a shared store | Decided when a module needs it |

## What CI builds and proves

Look at: every job builds against the packages of the same commit, not published ones, so the packages are always proven to work together ([K1](decisions/k01-one-repository-three-parts.md)).

```mermaid
flowchart TB
  commit["A commit or pull request"] --> bff["bff: the suite at the lowest and the newest versions, pip-audit"]
  commit --> ui["ui: lint, tests, build, the committed theme is not stale"]
  commit --> tb["template-backend: the template's tests on this commit's BFF"]
  commit --> tw["template-web: build on this commit's UI, serve with this commit's BFF, three browsers and the gate"]
  commit --> ti["template-image: build the image from this commit's packages, run it, GET /health"]
```

Source: `.github/workflows/ci.yml`. What each job proves, and the module's own CI: [new module](guides/new-module.md#what-ci-proves).

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

The UI package, the template and the image:

| Topic | Path | Tests |
|---|---|---|
| Colour mode | `packages/ui/src/color-mode.tsx` | `packages/ui/tests/color-mode.test.ts` |
| Providers, shell | `packages/ui/src/ModuleProviders.tsx`, `ModuleShell.tsx` | `providers.test.ts`, `shell.test.ts` |
| Brand and branding | `packages/ui/src/branding.tsx` | `branding.test.ts` |
| Theme and stylesheets | `packages/ui/src/theme/eneo.theme.ts`, `layers.css`, `base.css` | `theme.test.ts`, `package.test.ts` |
| A module's backend | `template/backend/main.py`, `routes.py` | `template/backend/tests/` |
| Eneo's side, for development | `template/stub-eneo/server.py` | `template/stub-eneo/test_server.py` |
| A module's UI | `template/web/src/` | `template/web/tests/e2e/` |
| The image | `template/Dockerfile`, `docker-compose.yml` | the `template-image` job of `.github/workflows/ci.yml` |
