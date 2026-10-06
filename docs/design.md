# eneo-module-kit: design

Purpose: the long-form design record: the module contract with Eneo, the decisions K1 to K12, the BFF's HTTP surface, its limits and the open questions.
Read this when: you need the full reasoning or the contract text. For one decision, start from [decisions](decisions/README.md).
Related: [decisions](decisions/README.md) (one short page each, K1 to K14), [architecture](architecture.md), [docs index](README.md), [README](../README.md).

Design record, 2026-10-01. Status: the BFF described here is built (`packages/bff`); the UI package and the template are planned. Where this page and the code disagree, the code wins.

The kit is extracted from the first module, `eneo-ai/eneo-mod-speech-to-text` ("speech-to-text" below). The wider
design, including why speech-to-text moves to Astryx and to a one-process runtime, is in that repository under
`docs/plans/2026-10-01-module-platform-design.md` (a file that repository removes when its port ends).

## 1. Goal

A new Eneo module should start connected to Eneo, themed, accessible and deployable, by copying one small template
and importing two packages. Shared code is fixed in one place and arrives in modules as a version bump.

## 2. The module contract with Eneo

Eneo is the installation's only login. Its side of the contract is in `eneo-ai/eneo`:
`docs/deployment/MODULES.md` (operators) and the "Module Authentication" page of the docs site (engineers).

What a module must do:

| Step | Module side |
|---|---|
| Start login | Create an unpredictable one-time `state`, bind it to the browser in an HttpOnly, SameSite=Lax cookie scoped to the callback path, redirect to `{ENEO_PUBLIC_URL}/module-login?module_key&redirect_uri&state`. |
| Callback | Reject a missing or mismatched `state` before anything else. The state is bound to the browser by a signed cookie that lives five minutes and that the callback deletes; the module keeps no list of used states, because a ticket works once and Eneo enforces that. Exchange the ticket server-side: `POST {ENEO_BACKEND_URL}/api/v1/module-auth/token/` with the service key. Check the returned `module_key`, expiry and identity, then confirm them with `GET /api/v1/module-auth/{module_key}/session/` using both credentials. Redirect to a clean URL with `Referrer-Policy: no-referrer`. |
| Session | Keep the module-user token in a server-side session. The browser holds only an opaque HttpOnly cookie. The session ends at `min(module maximum, Eneo's session_expires_at)`. A new login ends the session the browser held. |
| Refresh | At half the token's lifetime: `POST /api/v1/module-auth/{module_key}/token/refresh/` with both credentials, one refresh in flight per session. On any refusal other than 408, 429 or 5xx, end the session. When Eneo cannot answer (408, 429, 5xx, network, or an unexpected error here), keep the valid token and ask again shortly. |
| Resource calls | Send both the service key (header name configurable, default `X-API-Key`) and `Authorization: Bearer <module-user token>` on every call. Of the browser's request headers only a short allowlist reaches Eneo, never its `Cookie`, `Authorization`, `Origin` or `Referer`. |
| Renewal | A login renewed before the end may only renew the same user in the same tenant. |
| Deployment | One container on `module_net`, port 3001, `/health`, no outbound internet. |

## 3. Decisions

**K1. One repository, three parts.** `packages/ui` (npm), `packages/bff` (Python), `template/` (copied by new
modules). One CI builds the template against both packages on every commit, so the template is always proven to
work with the current packages.

**K2. One stack.** Vite + React + Astryx for the UI, FastAPI for the BFF, one process and one container. The kit is
not framework-agnostic. It does not force its stack on the other half either: the UI package imports nothing from a
router, and the BFF's HTTP surface is documented (section 5).

**K3. FastAPI, not Hono.** The login and proxy code exists in speech-to-text with about 2,800 lines of tests, and it
is the security boundary. Hono could do the job and would give one language; that is a reason to revisit, not to
rewrite now.

**K4. The UI is a static app served by the BFF.** No server rendering, no proxy hop in front of uploads and
WebSockets. Verified in a trial on 2026-10-01: a Vite 8 build with Astryx 0.6.3 and the built Eneo theme, served by
FastAPI, ran in Chromium and WebKit with no console or CSP errors under
`script-src 'self'; style-src 'self'` (no `unsafe-inline` at all). A deep link returned the page; a missing asset
and an unknown `/api/*` path returned 404, not HTML.

**K5. SSO only.** Speech-to-text's temporary access-code login is not part of the kit. Local development uses a
stub Eneo that implements the handoff.

**K6. Deny by default.** The proxy exposes nothing until the module names a route. The kit ships the mechanism;
each module ships its own allowlist. Deny by default holds for paths and for headers: of the browser's request
headers only a short allowlist reaches Eneo (a module may add to it), and the credentials are the module's. Eneo's
`Location` never reaches the browser, and a redirect from Eneo (301, 302, 303, 307, 308) is a 502 `upstream_redirect`:
the module follows none and no route of a module is expected to redirect.

**K7. Primitives, not routes, for uploads and files.** Forwarding a multipart upload and streaming a signed file
with Range are functions the module calls from its own routes. Which Eneo paths they point at is the module's.
The module declares those routes on an `APIRouter` and hands it to `create_app(routers=[...])`. Routes match in
registration order: the kit's own routes, then the module's, then the proxy, then the static app. A module's route
therefore wins over the proxy and the page (including under `/api/eneo/`), and cannot replace a route of the kit.
The module declares its own `Depends(require_session)` and `require_same_origin` on each route.
An upload route has no `File(...)` parameter: FastAPI reads a route's body before it runs the route's dependencies,
so `forward_upload(request, path)` reads the multipart itself, after them. It requires the Content-Length (411),
at most `max_upload_bytes` (413, default 1 GiB), one file part named `upload_file` and no other field (400), and no
control character (C0, DEL, C1) or line or paragraph separator in the file name or content type (400). The name is
forwarded as it came, a path included: Eneo owns where a file lands.
No body is read before auth or past a limit. A pure-ASGI cap, `max_body_bytes` (default 10 MiB), covers every
request body of every route, including a module's deliberately public ones, because it looks at no session (a 401
gate would break them): 413 at once when the declared length is above it, else as soon as the stream passes it.
No content type is exempt: FastAPI reads a body whatever the content type says, so a client that claims multipart
would otherwise buy an unbounded read. Only `forward_upload` lifts the limit, to `max_upload_bytes`, for its own
request, after the route's dependencies and its own checks; the bytes that arrive are counted, so a Content-Length
that lies, or a chunked body, gets no further. What this does not do: an unauthenticated request can still make the
BFF buffer up to `max_body_bytes` of a body, once per request, before a route's dependencies run. What that costs in memory is in section 6, so a module that is public to the
internet sets `MAX_BODY_BYTES` for its own largest JSON body, not for the default.
A Content-Length that is not a length (not ASCII digits, longer than 19 characters, or 2**63 or more) is a 400
`Invalid Content-Length`, whatever the route: uvicorn's httptools parser lets a zero-padded one of any length through,
and `int()` refuses more than 4300 digits, so it would otherwise be a 500.
A body that passes the limit while a response is already streaming ends the response, as if the client had gone.
An answer from Eneo to the signed-URL request that the module cannot use (not JSON, no `url`, a URL that is not
http(s) or that the client refuses (a NUL, over 65,536 characters), an `expires_at` that was given but is not a finite number above zero (`false`, `0`, `""`, `[]`, `{}`, a negative one or one too big for a float; only a missing or null one means the default of 15 minutes)) is a 502 `upstream_invalid`, and the log names the mint path,
never the body.
Uploads and files share admission through `limits.py` (`heavy_io_slot`); module-owned protocols use the same public guard.
Admission precedes upload parsing or file minting, returns 503 with `Retry-After` when occupied, and stays held
through upstream and temporary-file cleanup. Upload reception has total and inactivity deadlines (408), and
an incomplete multipart body is a 400. [K15](decisions/k15-heavy-io-admission.md) explains the bounds; the
[configuration table](guides/configuration.md) owns their defaults and storage sizing.
The client waits at most 5 s for a free connection (`pool=5`).
A signed URL is a bearer URL to a file, so the session store keeps it and it ends with its session, however the
session ends (logout, expiry, a refresh that ends it, a new login replacing it).

**K8. An application factory.** `create_app(...)` builds the app from settings and owns its HTTP client through
the app's lifespan. No import-time globals, so tests build an app per case instead of patching module state.

**K9. Colour mode is the UI package's own.** A static app has no server render, so the stored choice is read
before React renders and passed to Astryx's `<Theme mode>` directly. The storage key is `theme` with values
`light`, `dark`, `system`, the same key and values next-themes uses, so speech-to-text's saved preferences carry
over. An inline script is not needed, which keeps the strict CSP.

**K10. Branding without templating.** The page asks `/api/branding` before its first render and shows no
organisation mark until it has the answer. Nothing is injected into `index.html`.

**K11. Astryx is pinned to an exact version** in the UI package and the template. The house bar above its defaults
(44 px touch targets, a measured focus ring, a readable dark-mode error label) is met once, in the theme.

**K12. For agents: `AGENTS.md`, the pinned Astryx CLI, and the UI package as an Astryx integration.** No custom MCP
server and no skill.

## 4. What stays out

- Each module's proxy allowlist and its own routes.
- Speech-to-text's live transcription relay, recording identifiers, transcript routes.
- Draft retention, recovery copy, flow configuration.
- The access-code login.
- A WebSocket relay helper, until a second module needs one.
- Upgrade codemods, and public `testing` and `a11y` exports, until a second module needs them.

## 5. The BFF's HTTP surface

Stable for the UI package and for any other frontend:

| Route | Purpose |
|---|---|
| `GET /health`, `GET /api/healthz` | `{"ok": true}` |
| `GET /api/auth/login?next=&renew=` | Start the handoff |
| `GET /api/auth/callback?ticket=&state=` | Finish it |
| `POST /api/auth/logout` | End the session (same-origin) |
| `GET /api/auth/status` | `{authenticated, user, session_ends_in, refresh_in}` |
| `GET /api/branding`, `GET /api/branding/logo/{light\|dark}` | The deployment's organisation |
| the module's own routes (`routers=`) | Whatever the module declares; they win over the two rows below |
| `GET\|POST\|PATCH /api/eneo/{path}` | The allowlisted proxy |
| anything else | The static app; unknown assets, `/api` and unknown `/api/*` are 404 |

A request without a session gets 401 with `X-Auth-Required: session`. A write from another origin gets 403.

## 6. Limits to be honest about

- The kit is carved from one module. The template is a working fixture, not proof that the abstraction fits a
  different module. Versions stay 0.x until speech-to-text runs on the kit and a second module has used it.
- The BFF package declares dependency ranges with security floors, not exact pins (a library; the pins copied from speech-to-text carried 14 known advisories). CI runs the suite at the floors and at the newest versions, with `pip-audit` on both; a module pins and locks its own.
- The HTTP client is `httpx2`, not `httpx` (decided 2026-10-01, with measurements). `httpx` has had no release since
  0.28.1 (2024-12), still builds a request with both `Content-Length` and `Transfer-Encoding`, still lets a line break
  in a file's content type inject a multipart part header (both reproduced; `httpx2` fixed them in 2.11.0), and
  Starlette's test client deprecates it. `httpx2` (`pydantic/httpx2`, 16 releases since May 2026) passes the same
  suite and the same adversary scripts with identical output. Against a slow fake Eneo, peak memory stays flat at
  64-65 MB through a 1 GB upload on both clients, and event-loop latency and 20 concurrent Range streams are the same
  within noise (11 runs each). The floor `>=2.12.0` is where its five advisories are all fixed. It pins `httpcore2`
  to its own version, and it uses the operating system's trust store (`truststore`) instead of `certifi`: a module that
  calls Eneo over HTTPS with a private CA installs that CA in its image.
- Forwarding timeouts remain per phase (60 s a read or write, 5 s for a free connection, 10 s to connect,
  an upload's own forwarding budget). Receiving an upload has total and inactivity deadlines; those do not bound forwarding to Eneo.
- `serve()` stops within 8 s of SIGTERM, with files still streaming (`timeout_graceful_shutdown`), because Docker
  kills the container after 10 s.
- The Starlette floor is 1.7.0 (FastAPI's own floor stays 0.142.2: every FastAPI release from 0.138 to 0.142.2 declares
  only `starlette>=0.46.0`, and the suite passes on 1.7.0). The first release with no known advisory (1.3.1) was not enough. From 1.3.1 to 1.6 a
  multipart body the parser cannot read (a bare CR in a file name, a part header of 20 KB, garbage before the first
  boundary, no boundary at all) is a 500, because the parser's own error is not turned into a response, and the
  temporary file of an upload that is cut off is closed when garbage is collected, not at once (13 open files at rest,
  27 after 175 cut-off uploads, then steady). From 1.7.0 those are a 400 and the file is closed at once.
  The "a malformed body is a 400, never a 500" claim therefore holds at the floor, and a library that is used with
  the newest stack gains nothing from a lower one.
- The memory bound is per request, not total. Measured on a 10 MiB body: one request raises the process's peak by
  about 21 MiB (`request.body()`) or 42 MiB (a JSON model), and 50 at once raise it by 13 to 16 MiB or 17 to 26 MiB
  each. A module multiplies that by the requests it expects in flight; the cap bounds a request, not their sum, and
  no global byte budget is built.
- The client the kit builds (`upstream.make_client`) keeps no cookies: one client serves every user, so a cookie Eneo
  sets on one user's call would otherwise be sent with the next user's. Every call to Eneo is authorised by its
  headers alone. A module that passes its own `http_client` to `create_app` owns that policy.
- What Eneo answers is bounded as it arrives, like what the browser sends. The kit's client (`upstream.make_client`) asks
  for no encoding, refuses an encoded answer (a few KB of gzip decode to gigabytes, and the decoded size is what is
  held), and stops at `max_response_bytes` (32 MiB; 502 `upstream_too_large`, the answer closed): the proxy and
  uploads. The answers that carry a token or a URL (ticket exchange, session check, refresh, signed URL) stop at 1 MiB
  and the body of a failed file answer is read to 1 MiB and dropped past it. Only a file that streams is unbounded, and an answer that cannot carry content (to a HEAD, a 204, a 304, which may declare the length of the representation it did not send) is not checked. A
  proxied answer is still held whole until it is sent, so `MAX_RESPONSE_BYTES` is the most payload one answer retains,
  not the memory it costs: httpx2 joins the chunks it read into one `bytes`, and holds both while it does, and the
  transport adds its own buffers. Measured against a real server, one 24 MiB answer raised the module's peak by 55 to
  59 MiB (2.3 to 2.5 times the payload), and six 8 MiB answers at once by 73 to 89 MiB (1.5 to 1.9 times each, as
  the joins do not all coincide). A module plans for about 2.5 times `MAX_RESPONSE_BYTES` per answer in flight, times
  the answers it expects at once, and sets `MAX_RESPONSE_BYTES` for its largest real answer; one that serves large
  downloads uses `stream_signed`, not the proxy.
- A session lookup does not scan the store, and expired sessions are swept at most every 30 s (a lookup refuses an
  expired id by itself, so nothing depends on the sweep).
- Recorded, not built: no cap on the number of sessions (each one needs an Eneo login, which Eneo rate-limits, and a
  second login already ends the browser's old session), and no single-flight for signed URLs (20 concurrent cold Range
  requests for one file mint 20 URLs: low value).
- The session store is process-local: one replica. Scaling out needs sticky sessions or a shared store, decided
  when a module needs it.
- Astryx is pre-1.0. Menus and pickers are not anchored to their trigger on Safari before 26 and Firefox before 147.
- Speech-to-text can only adopt the UI package once it is a static app too (its Plan B), because the package's
  colour mode and providers assume no server render.

## 7. Open decisions for the owner

| Question | Default |
|---|---|
| Packages public (npm `@eneo-ai/module-kit`, PyPI `eneo-module-bff`) or private? | Public. Until the first release the template pins the BFF to a commit. |
| Does `eneo-ai` own the `@eneo-ai` scope on npm? | To be checked before the first release. |
| Licence for this repository? | None yet; the module repositories have none either. |
| Router for the template? | `react-router`, library mode. The UI package does not depend on it. |

## Build scaffolding (temporary)

The plan that carries this design out is `docs/plans/2026-10-01-module-kit-plan.md`. It and the Beads board exist only while the kit is built.
