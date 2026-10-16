# Security checklist

Purpose: say what the BFF already enforces, what each module must still do, and what the kit does not protect against.
Read this when: you are adding a route, a proxy rule or a setting to a module, preparing a deployment, or reviewing a change in `packages/bff`.
Related: [build a module](build-a-module.md), [configuration](configuration.md), [architecture](../architecture.md), [design.md](../design.md) sections 2, 3 and 6, [decisions](../decisions/README.md).

The BFF is the security boundary between a browser and Eneo. Its properties are tested in `packages/bff/tests/`; a module's own routes are not covered by them.

## What the kit enforces

| Property | How | Source |
|---|---|---|
| The browser never holds a credential for Eneo | The session cookie is a random id; the module-user token stays in the module's memory; the service key is never sent to the browser | `auth.py` |
| A login belongs to the browser that started it | A signed state cookie (five minutes, path `/api/auth/callback`) must match the `state` on the callback, compared in constant time | `auth.py` |
| A ticket is checked, not trusted | Module key, expiry and identity are checked, then confirmed with a session call using both credentials | `auth.py` |
| One session per browser, ending when Eneo says | A new login ends the old session; the session ends at the earlier of `SESSION_MAX_AGE_MINUTES` and Eneo's ceiling; a renewal may only renew the same user in the same tenant | `auth.py` |
| A refresh is single-flight, and a logout stays a logout | One refresh per session; a session deleted during it is not brought back | `auth.py` |
| Writes come from the module's own origin | `require_same_origin` compares `Origin` with `MODULE_PUBLIC_URL` (write methods and WebSocket handshakes) | `auth.py`, `deps.py` |
| A page writes only as its own user | `require_expected_user`: a write names the session's user in `X-Expected-User`, else 409 `user_changed`. The proxy applies it; `fetchWithSession` sends the header and covers the page on the 409 | `auth.py`, `deps.py`, `proxy.py`, `packages/ui/src/session/request.ts` |
| Nothing is proxied until named | Rules match method and whole path; a path that could reach another Eneo route is a 403 first | `proxy.py` |
| The browser chooses no credential and no framing header | A short request-header allowlist; the credentials come from the session | `proxy.py` |
| Eneo's `Set-Cookie` and `Location` stay with the module; a redirect is an error | 502 `upstream_redirect` for the proxy, uploads and files | `proxy.py`, `transport.py` |
| Eneo sets no policy for the module's origin | The proxy drops Eneo's `Content-Security-Policy` (and its report-only form), `X-Frame-Options`, `Permissions-Policy`, `Referrer-Policy`, `Cache-Control`, `Strict-Transport-Security` and `Clear-Site-Data`; the module's own apply | `proxy.py` |
| No body is read before auth or past a limit | A body cap on every route; uploads read after the route's guards, counted as they arrive | `limits.py`, `transport.py` |
| Heavy operations leave connections for the API | Shared admission before upload parsing or file minting; module protocols use `heavy_io_slot`; a quick 503; the configured ceiling is at most 96 of 100 pool connections | `limits.py`, `transport.py`, `settings.py`, `app.py` |
| Partial uploads cannot hold temporary storage indefinitely | Concurrent-upload cap, total and inactivity receive deadlines, incomplete-body rejection, files closed before capacity is released | `transport.py`, `settings.py` |
| A signed URL never reaches the browser and ends with its session | Minted by the module, kept in the session store | `transport.py`, `auth.py` |
| A user's file cannot run script from the module's origin | Inline only for audio, video, PDF and PNG, JPEG, GIF, WebP; `nosniff` | `transport.py` |
| A deployment cannot start with development settings | Off this machine (`MODULE_PUBLIC_URL` not `localhost`, `127.0.0.1` or `[::1]`), `load_settings` refuses an http `MODULE_PUBLIC_URL` or `ENEO_PUBLIC_URL`, `COOKIE_SECURE=false`, and the `SESSION_SECRET` or `ENEO_API_KEY` that `template/.env.example` publishes | `settings.py` |
| Only the built UI's own files are served | A dotfile, a path with a control character, a backslash or a `.` or `..` segment, and `//api/x` are a 404, never a 500 or the page | `web.py` |
| Browser-side hardening | The headers below, on every answer, a 500 included, unless a route set its own | `web.py` |
| No user's answer is kept in a browser's cache | An answer under `/api` gets `Cache-Control: no-store` unless its route says how it may be kept (the branding stylesheet, a logo, a file stream) | `web.py` |
| An organisation logo cannot run script | Served with `Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox` and `nosniff` | `branding.py` |
| No API description and no redirect on the module's origin | No `/docs`, `/redoc` or `/openapi.json`; the slash twin of a route is a 404, not a 307 whose `Location` says http:// behind a proxy that ends TLS | `app.py` |
| One replica, no ticket in the logs | One worker, uvicorn's access log off, no `Server` banner | `serve.py` |
| No token in the kit's logs | Login and refresh log the kind of an error, never its text: a validation error quotes the answer it refused, and httpx2's error quotes a header it could not send. `httpx2` and `httpcore2` log at WARNING: their INFO lines hold full URLs, a signed URL among them | `auth.py`, `app.py` |

Headers on every answer (`web.py`), an unhandled error's 500 too; `create_app(security_headers={...})` replaces one by name, for example `Permissions-Policy: camera=(), geolocation=(), microphone=(self)`:

| Header | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'` |
| `Referrer-Policy` | `no-referrer` |
| `X-Content-Type-Options` | `nosniff` |
| `X-Frame-Options` | `DENY` |
| `Permissions-Policy` | `camera=(), geolocation=(), microphone=()` |

## What a module must do

Tick each before a module goes live.

- [ ] Every route of the module has `Depends(require_session)`. Every write (`POST`, `PUT`, `PATCH`, `DELETE`) and every WebSocket also has `Depends(require_same_origin)`.
- [ ] Every write of the module's own routes has `Depends(require_expected_user)` too, as the proxy has, so a page under someone else's session cannot write as them. `unguarded_routes` does not check it.
- [ ] A test fails when a guard is forgotten: `unguarded_routes` (copy from `packages/bff/tests/test_deps.py`) returns `[]` for the module's routers.
- [ ] A route that is public on purpose is rare and written down. It still gets the body cap and nothing else: it must never return session, token or Eneo data.
- [ ] A deployment accent is loaded through the kit's validated configuration and same-origin stylesheet. Do not interpolate unchecked colour input into CSS. See [K10](../decisions/k10-branding-without-templating.md).
- [ ] An upload route has no `File(...)` parameter and calls `forward_upload`.
- [ ] Each proxy rule is as narrow as it can be: the fewest methods, a pattern that ends at the route (`$`), the trailing slash of Eneo's route, `RESOURCE_ID` only where one id belongs, no `.*`.
- [ ] `forward_request_headers` is empty unless a header is needed, and never names a credential (the app refuses those).
- [ ] `inline_types` holds nothing that can run script: not `text/html`, not `image/svg+xml`.
- [ ] In production: `COOKIE_SECURE` is `true` (the default), `ENEO_PUBLIC_URL` and `MODULE_PUBLIC_URL` are https, `SESSION_SECRET` is random and at least 32 characters, and `ENEO_API_KEY` and `SESSION_SECRET` come from a secret store, not from the repository or the image.
- [ ] One replica of the module runs: sessions are in memory. `serve()` fixes one worker.
- [ ] The module's own logging never records `/api/auth/callback` with its query (it carries the ticket), `Cookie` or `Authorization` headers, or signed URLs, and logs the kind of an error from a call to Eneo, not its text (`logger.exception` prints a text that can quote a token). The package sets only `httpx2` and `httpcore2` to WARNING.
- [ ] A module that calls Eneo over HTTPS with a private CA installs that CA in its image: `httpx2` uses the operating system's trust store, not `certifi`.
- [ ] The module's dependencies are pinned and locked, and `pip-audit` finds nothing in the installed set (the package declares ranges with security floors).

## The cover for an ended login

While the login has ended the page is covered, not removed: it stays mounted, hidden and out of reach, under the sign-in dialog ([K15](../decisions/k15-cover-for-an-ended-login.md)). A native dialog of the page escapes that, so a module checks:

- [ ] Every native dialog of the page closes while `useSignedOut()` is true (`isOpen={open && !signedOut}`, its state held above the dialog).
- [ ] No dialog is portalled out of `RequireSession`'s children: one outside the cover stays in the accessibility tree.
- [ ] A dialog left open is hidden by the sign-in dialog's opaque backdrop in every engine, but in WebKit it is still reachable by Tab, so the check above is the module's own.

Proof, for the template: `template/web/tests/e2e/session-cover.spec.ts` (Chromium, WebKit and Firefox) and `packages/ui/tests/session-gate.test.ts`.

## What the kit does not protect against

Recorded in [design.md](../design.md) section 6.

| Limit | What it means |
|---|---|
| An unauthenticated request can make the BFF buffer up to `MAX_BODY_BYTES` of a body, once per request | On a module route that declares a body parameter, FastAPI reads the body before the route's dependencies run. Measured on a 10 MiB body: one request raises the process's peak by about 21 MiB (`request.body()`) or 42 MiB (a JSON model), and 50 at once raise it by 13 to 16 MiB or 17 to 26 MiB each. A module that is public to the internet sets `MAX_BODY_BYTES` for its own largest JSON body, not for the default. |
| No cap on the number of sessions | Each needs an Eneo login, which Eneo rate-limits, and a second login ends the browser's old session. |
| No single-flight for signed URLs | 20 concurrent cold Range requests for one file mint 20 URLs. |
| The session store is process-local | One replica. Scaling out needs sticky sessions or a shared store, decided when a module needs it. |
| No total deadline per request | Timeouts are per phase: 60 s a read or write, 5 s for a free connection, 10 s to connect, and an upload's own budget. |
| The Starlette floor is 1.7.0 | From 1.3.1 to 1.6 a multipart body the parser cannot read is a 500, and a cut-off upload's temporary file is closed late (13 open files at rest, 27 after 175 cut-off uploads). From 1.7.0 the first is a 400 and the file is closed at once. |
| One module so far | The kit is carved from one module. Versions stay 0.x until a second module has used it. |
