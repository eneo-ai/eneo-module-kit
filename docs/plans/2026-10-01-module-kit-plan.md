# Eneo Module Kit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the starter for Eneo modules: a FastAPI BFF package that implements the module contract with Eneo, a React + Astryx UI package, and a template app that new modules copy.

**Architecture:** One repository. `packages/bff` and `packages/ui` are imported by modules; `template/` is copied. The UI is a static Vite app served by the BFF in one process. The BFF is extracted from `eneo-ai/eneo-mod-speech-to-text` with its tests; behaviour is carried over, not redesigned.

**Tech stack:** Python 3.12, FastAPI 0.142, Starlette 1.3, uvicorn 0.54, httpx 0.28, itsdangerous 2.2, python-multipart 0.0.31, unittest. Node >= 22.13, Vite 8, React 19.2, TypeScript, `@astryxdesign/core` 0.6.3, `@astryxdesign/cli` 0.6.3, `@stylexjs/stylex` 0.19.1, Playwright.

**Spec:** `docs/design.md`. Read it in full before starting.

**Work order and status:** Beads in this repository (`.beads/`, prefix `kit`). Run `br ready --json` for the next bead, claim it, close it with evidence. Each bead names the part of this plan it covers, the files it may touch and what is out of scope. The checkboxes below are a working aid inside a task; they are not the board.

## Global Constraints

- **Source of truth for extracted code:** `eneo-ai/eneo-mod-speech-to-text` at commit `f81a7dd` (its `main` on 2026-10-01). Clone it beside this repository: `git clone https://github.com/eneo-ai/eneo-mod-speech-to-text ../eneo-mod-speech-to-text && git -C ../eneo-mod-speech-to-text checkout f81a7dd`. Below, `STT` means that directory. Copy code from it; do not rewrite it from memory and do not "improve" it while moving it.
- Never change anything in `STT`. Nothing is moved out of it; this repository copies.
- Carry tests over with the code they test. A behaviour without its test is not extracted.
- The BFF is SSO-only. Drop `AUTH_MODE`, `APP_ACCESS_CODE`, `AccessCodeSession`, `login_with_access_code` and `DEMO_SPACE_ID` and their tests. Drop nothing else.
- The proxy denies by default. The kit ships no allowlist entries. Routes for uploads and files are the module's; the kit ships the functions they call.
- Out of the kit entirely: the live transcription relay (`STT/backend/app/main.py` from "Live transcription preview" down), `tests/test_live_relay.py`, artifact download naming (`_eneo_filename`, `_content_disposition`, `eneo_run_artifact_content`), `/api/config` and `FlowListScope`.
- No import-time application state in `packages/bff`: no module-level `settings`, `app`, `http_client` or caches. Everything hangs off the app the factory returns.
- Python: the package is a library, so it declares ranges with security floors, not exact pins: `fastapi>=0.142.2,<1`, `starlette>=1.3.1,<2`, `uvicorn[standard]>=0.54,<1`, `httpx>=0.28,<1`, `itsdangerous>=2.2,<3`, `python-multipart>=0.0.31,<1`. Speech-to-text's pins (`fastapi==0.115.0`, `python-multipart==0.0.12`, Starlette 0.38.6) carry 14 known advisories (`pip-audit`, 2026-10-01: multipart parser denial of service, unbounded multipart buffering, form limits ignored), and an exact-pinned library forces every module onto one stack. The floors are the fixed versions. Exact pins and a lock belong to the application (the template, Phase 3). The suite must pass at the floors and at the newest versions, and `pip-audit` must report nothing on both. No new runtime dependency without a line in `docs/design.md`.
- JavaScript: `@astryxdesign/core` `0.6.3`, `@astryxdesign/cli` `0.6.3`, `@stylexjs/stylex` `0.19.1`, exact. Run the Astryx CLI only as `npm run astryx -- <command>`. Read `npm run astryx -- component <Name>` before using a component; never guess a prop.
- No Next.js, no Tailwind, no second UI library, no Hono. No ejected Astryx component, no authored StyleX.
- The UI package imports nothing from a router or a meta-framework, and nothing from the template.
- CSP for the served app: `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; font-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'`. No inline script, ever. If a component later needs inline style attributes, widen `style-src` only, with a note in `docs/design.md`.
- User-facing text in the template is Swedish; `lang="sv"`. No font, script or request to another origin.
- Accessibility: WCAG 2.2 AA, 44 px targets under `pointer: coarse`, 24 px otherwise, a focus change of 3:1 or more. Thresholds are never lowered.
- Port 3001, `/health`, one uvicorn worker, access log off (the callback URL carries a ticket).
- Versions are `0.x`. One phase is one pull request to `main`. Commit after every task. Push or open a pull request only when the owner asks.

## Review Focus

Conditions no task's tests fully exercise and that are most likely to hurt:

1. **A proxied path that escapes its rule** (`flows/%2E%2E/runs/`, a decoded `?` or `#`). Expected: 403 before any upstream call. Pinned by the proxy tests carried over in Task 1.5; add any new encoding you think of as a test there.
2. **Two requests arriving while a token refresh is in flight, and a logout during it.** Expected: one refresh, both requests use its result, and a logout stays a logout. Pinned by the refresh tests carried over in Task 1.3.
3. **Eneo answering slowly or not at all during callback, refresh and upload.** Expected: the documented error codes and no session created from a half-finished exchange. Carried over in Tasks 1.3 and 1.6.
4. **A deep link, a missing asset and an unknown `/api/*` path.** Expected: the page, 404, 404 with JSON. Pinned in Task 1.7.
5. **A module author forgetting `require_session` on a route.** Expected: the template's own backend test fails. Pinned in Task 3.2 by a test that walks the app's routes.

---

## How to work

- Python: `python3.12 -m venv .venv && .venv/bin/pip install -e "packages/bff[test]"`; tests with `.venv/bin/python -m unittest discover -s packages/bff/tests -t packages/bff`.
- JavaScript: `npm install` at the repository root (npm workspaces); `npm run -w packages/ui build`, `npm run -w template/web build`.
- When a step says "carry over", copy the file from `STT`, then change only imports, names listed in the task, and how the app under test is built. Run the tests before and after each change so a failure has one cause.
- Stop and comment on the bead, instead of working around it, when: a carried-over test fails for a reason that is not a renamed import or a removed access-code case; a task seems to need a file outside its Scope; or a Global Constraint would have to be broken.

## File structure

```
package.json                     npm workspaces: packages/ui, template/web
packages/bff/
  pyproject.toml                 name eneo-module-bff, src layout, extra "test"
  src/eneo_module_bff/
    __init__.py                  the public names, nothing else
    settings.py                  Settings, Organization, LogoFile, load_settings
    auth.py                      ModuleAuth, ModuleSessionStore, ModuleSession, ModuleUser, cookies and paths
    deps.py                      require_session, require_same_origin, upstream_auth_headers (read app state)
    proxy.py                     ProxyRule, rule(), leaves_route, the /api/eneo proxy router
    transport.py                 forward_upload, stream_signed and its per-app signed-URL cache
    branding.py                  /api/branding and the logo routes
    web.py                       security headers, static app, fallback
    app.py                       create_app, lifespan
    serve.py                     serve(): uvicorn with the kit's limits
  tests/                         unittest, one file per module above
packages/ui/
  package.json                   name @eneo-ai/module-kit, exports, peer dependencies
  src/theme/eneo.theme.ts        theme source; built/ is generated and committed
  src/color-mode.tsx             ColorModeProvider, useColorMode
  src/ModuleProviders.tsx        colour mode + Theme + Swedish catalog (+ link component)
  src/ModuleShell.tsx            presentational frame
  src/branding.tsx               BrandingProvider, Brand
  src/session/                   Phase 4
  astryx.integration.mjs         Phase 5
template/
  backend/main.py                create_app(...) + this module's allowlist and routes
  backend/tests/
  web/                           Vite app
  stub-eneo/server.py            Eneo's side of the contract, for development and tests
  Dockerfile  docker-compose.yml  .env.example  .devcontainer/  .github/workflows/ci.yml
  AGENTS.md  CLAUDE.md
docs/
  design.md  module-contract.md  new-module.md  plans/
```

---

## Phase 0 — Repository foundation

### Task 0.1: Workspaces, tooling and CI

**Files:**
- Create: `package.json`, `.gitignore`, `.nvmrc`, `.github/workflows/ci.yml`, `packages/bff/pyproject.toml`, `packages/bff/src/eneo_module_bff/__init__.py`, `packages/bff/tests/__init__.py`, `packages/bff/tests/test_package.py`

- [ ] **Step 1: Write the failing test** — `packages/bff/tests/test_package.py`:

```python
import unittest


class PackageTests(unittest.TestCase):
    def test_the_package_imports_and_names_its_version(self) -> None:
        import eneo_module_bff

        self.assertRegex(eneo_module_bff.__version__, r"^0\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it and see it fail**

Run: `python3.12 -m venv .venv && .venv/bin/python -m unittest discover -s packages/bff/tests -t packages/bff`
Expected: `ModuleNotFoundError: No module named 'eneo_module_bff'`.

- [ ] **Step 3: Create the package**

`packages/bff/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "eneo-module-bff"
version = "0.1.0"
description = "The Eneo module contract for a FastAPI BFF: login handoff, session, deny-by-default proxy"
requires-python = ">=3.12"
# Ranges with security floors, not exact pins: this is a library. A module's own requirements pin and lock them.
dependencies = [
  "fastapi>=0.142.2,<1",
  "starlette>=1.3.1,<2",
  "uvicorn[standard]>=0.54,<1",
  "httpx>=0.28,<1",
  "itsdangerous>=2.2,<3",
  "python-multipart>=0.0.31,<1",
]

[project.optional-dependencies]
test = []

[tool.hatch.build.targets.wheel]
packages = ["src/eneo_module_bff"]
```

`packages/bff/src/eneo_module_bff/__init__.py`:

```python
"""The Eneo module contract for a FastAPI BFF."""

__version__ = "0.1.0"
```

Root `package.json`:

```json
{
  "name": "eneo-module-kit",
  "private": true,
  "workspaces": ["packages/ui", "template/web"],
  "engines": { "node": ">=22.13.0" }
}
```

`.nvmrc`: `22`. `.gitignore`: `node_modules/`, `dist/`, `.venv/`, `__pycache__/`, `*.py[cod]`, `test-results/`, `.env`, `.DS_Store`.

- [ ] **Step 4: Run it and see it pass**

Run: `.venv/bin/pip install -e "packages/bff[test]" && .venv/bin/python -m unittest discover -s packages/bff/tests -t packages/bff`
Expected: `OK`.

- [ ] **Step 5: CI** — `.github/workflows/ci.yml` with one job `bff`, run twice (matrix `lowest-direct` and `highest`): checkout, Python 3.12, a venv from `uv pip install --resolution <matrix value> -e "packages/bff[test]"`, the unittest command, and `pip-audit` on the installed set. Later phases add jobs; do not add them now.

- [ ] **Step 6: Commit.** `git add -A && git commit -m "chore: workspaces, the BFF package skeleton and CI"`

---

## Phase 1 — The BFF package

Result: `eneo-module-bff` implements the contract in `docs/design.md` section 2 and the HTTP surface in section 5, with speech-to-text's tests carried over. Branch `feat/bff`.

Every task follows the same shape: carry the test file over and adapt it, run it and see it fail on the missing module, carry the code over, run it and see it pass, commit.

### Task 1.1: Settings

**Files:**
- Create: `packages/bff/src/eneo_module_bff/settings.py`, `packages/bff/tests/test_settings.py`
- Source: `STT/backend/app/config.py`, `STT/backend/tests/test_config.py`, `STT/backend/tests/test_branding.py` (the settings cases)

**Interfaces — Produces:**

```python
class Organization(BaseModel): name: str; logo: Literal["default", "custom"] | None; dark_logo: bool = False
class LogoFile(BaseModel): media_type: Literal["image/svg+xml", "image/png"]; content: bytes

class Settings(BaseModel):
    eneo_backend_url: str
    eneo_public_url: str
    module_public_url: str
    module_key: str
    eneo_api_key: str
    eneo_api_key_header_name: str = "X-API-Key"
    session_secret: str
    cookie_secure: bool = True
    session_max_age_seconds: int = 8 * 60 * 60
    upload_proxy_timeout_seconds: float = 1800.0
    home_path: str = "/"                      # where the callback lands when no `next` is given
    organization: Organization | None = None
    organization_logo: LogoFile | None = None
    organization_logo_dark: LogoFile | None = None

    @property
    def module_origin(self) -> str: ...

def load_settings(*, default_organization: Organization | None = None, home_path: str = "/") -> Settings: ...
```

Changes from the source, and only these:
- Removed: `AuthMode`, `auth_mode`, `app_access_code`, `demo_space_id`, `FlowListScope`, `flow_list_scope`, and every branch on them. `ENEO_PUBLIC_URL` is always required.
- `DEFAULT_ORGANIZATION` (Sundsvall) becomes the `default_organization` argument; the kit's default is no organisation.
- New: `home_path`. It replaces the literal `"/flows"` in `module_path` (Task 1.2).
- Everything else, including the validation messages, `_parse_bool`, `_read_logo`, `_organization` and `_required_url`, is copied unchanged.

- [ ] **Step 1:** Carry over `test_config.py` as `test_settings.py`. Delete the cases that test `AUTH_MODE`, `APP_ACCESS_CODE`, `DEMO_SPACE_ID` and the flow-list scope. Change `from app.config import …` to `from eneo_module_bff.settings import …`. In cases that expect Sundsvall by default, pass `default_organization=Organization(name="Sundsvalls kommun", logo="default")`, and add one case: with no organisation variables and no default, `settings.organization is None`.
- [ ] **Step 2:** Run. Expected: `ModuleNotFoundError: eneo_module_bff.settings`.
- [ ] **Step 3:** Carry the code over with the changes above.
- [ ] **Step 4:** Run. Expected: `OK`.
- [ ] **Step 5: Commit.** `feat(bff): settings and start-up validation`

### Task 1.2: The session store and the login handoff

**Files:**
- Create: `packages/bff/src/eneo_module_bff/auth.py`, `packages/bff/tests/test_auth.py`
- Source: `STT/backend/app/module_auth.py`, `STT/backend/tests/test_module_auth.py`

**Interfaces — Consumes:** `Settings`. **Produces:**

```python
SESSION_COOKIE = "eneo_module_session"; STATE_COOKIE = "eneo_module_login_state"; CALLBACK_PATH = "/api/auth/callback"

class ModuleUser(BaseModel): id: str; email: str; username: str | None = None
class ModuleSession(BaseModel):          # the source's EneoSsoSession, without the auth_mode field
    access_token: str; expires_at: int; refresh_at: int; session_expires_at: int
    module_key: str; tenant_id: str; user: ModuleUser
    def refresh_in(self) -> int | None: ...
    def refresh_due(self) -> bool: ...

class ModuleSessionStore: create, get, replace, delete, clear   # unchanged

class ModuleAuth:
    def __init__(self, *, settings: Settings, http_client: httpx.AsyncClient) -> None: ...
    router: APIRouter                      # GET /login, GET /callback, POST /logout, GET /status
    sessions: ModuleSessionStore
    async def require_session(self, connection: HTTPConnection, session_id: str | None) -> ModuleSession: ...
    def require_same_origin(self, connection: HTTPConnection) -> None: ...
    def upstream_auth_headers(self, connection: HTTPConnection) -> dict[str, str]: ...
```

Changes from the source, and only these:
- Removed: `AccessCodeSession`, `AccessCodeLoginRequest`, `login_with_access_code`, the `POST /login` route, `_require_auth_mode` and its calls, the `auth_mode` key in `status` and the `session.auth_mode != …` check in `_live_session`.
- `EneoSsoSession` is renamed `ModuleSession`; `ModuleSession = EneoSsoSession | AccessCodeSession` goes away; `isinstance(session, EneoSsoSession)` branches become unconditional.
- `module_path(value)` takes the fallback from `settings.home_path` instead of `"/flows"`; `PendingLogin.next` has no default and is always set.
- `status` returns `{"authenticated": bool, "user": {...} | None, "session_ends_in": int, "refresh_in": int}` (the last two only when authenticated, `refresh_in` only when a refresh is still possible).
- The Swedish query values `fel=utgangen` and `fel=annan-anvandare` stay as they are: the UI package reads them.

- [ ] **Step 1:** Carry over `test_module_auth.py` as `test_auth.py`. Remove the access-code cases. Replace `from app import main` and its use of `main.app` / `main.module_auth` with a small helper at the top of the file that builds a `FastAPI()` app, a `ModuleAuth(settings=…, http_client=…)` and includes `auth.router` under `/api/auth` (Task 1.4 replaces the helper with `create_app`). Remove the `os.environ.setdefault` block: build `Settings(...)` directly in the helper.
- [ ] **Step 2:** Run. Expected: `ModuleNotFoundError: eneo_module_bff.auth`.
- [ ] **Step 3:** Carry the code over with the changes above.
- [ ] **Step 4:** Run. Expected: `OK`, and the count of test methods equals the source's minus the removed access-code cases. Write both numbers in the commit message.
- [ ] **Step 5: Commit.** `feat(bff): login handoff, session store and token refresh`

### Task 1.3: Dependencies that read the app

**Files:** Create `packages/bff/src/eneo_module_bff/deps.py`, `packages/bff/tests/test_deps.py`.

A module declares its routes at import time, before an app exists. These three functions find the `ModuleAuth` on `request.app.state.module_auth`, so a module writes `Depends(require_session)` without holding the auth object.

```python
from typing import Annotated
from fastapi import Cookie
from fastapi.requests import HTTPConnection
from .auth import SESSION_COOKIE, ModuleAuth, ModuleSession


def _auth(connection: HTTPConnection) -> ModuleAuth:
    return connection.app.state.module_auth


async def require_session(
    connection: HTTPConnection,
    session_id: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> ModuleSession:
    """The caller's live session; 401 with X-Auth-Required for a request, a refused handshake for a WebSocket."""
    return await _auth(connection).require_session(connection, session_id)


def require_same_origin(connection: HTTPConnection) -> None:
    """Writes and WebSocket handshakes only from the module's own origin."""
    _auth(connection).require_same_origin(connection)


def upstream_auth_headers(connection: HTTPConnection) -> dict[str, str]:
    """The service key and the caller's module-user token, for a call to Eneo."""
    return _auth(connection).upstream_auth_headers(connection)
```

- [ ] **Step 1:** Write `test_deps.py`: an app with `app.state.module_auth` set and one route using `Depends(require_session)` and `Depends(require_same_origin)`; assert 401 with `X-Auth-Required: session` without a cookie, 403 for a `POST` with a foreign `Origin`, 200 with a stored session and the right origin, and that `upstream_auth_headers` returns both the API-key header and `Authorization: Bearer …`.
- [ ] **Step 2:** Run, see `ModuleNotFoundError`. **Step 3:** Add the file above. **Step 4:** Run, `OK`.
- [ ] **Step 5: Commit.** `feat(bff): route dependencies that find the module's auth on the app`

### Task 1.4: The application factory

**Files:** Create `packages/bff/src/eneo_module_bff/app.py`, `packages/bff/src/eneo_module_bff/branding.py`, `packages/bff/tests/test_app.py`, `packages/bff/tests/test_branding.py`. Modify `packages/bff/tests/test_auth.py` (use the factory).
Source for branding: `STT/backend/app/main.py` lines 106–131, `STT/backend/tests/test_branding.py`.

**Interfaces — Produces:**

```python
def create_app(
    settings: Settings | None = None,        # None: load_settings()
    *,
    title: str = "Eneo module",
    routers: Sequence[APIRouter] = (),       # the module's own routes, Task 1.9
    proxy_rules: Sequence[ProxyRule] = (),   # Task 1.5
    static_dir: Path | None = None,          # Task 1.7
    http_client: httpx.AsyncClient | None = None,   # tests inject one; otherwise the lifespan owns one
) -> FastAPI: ...
```

The app it returns has `app.state.settings`, `app.state.http` and `app.state.module_auth`, the auth router under `/api/auth`, `GET /api/healthz` and `GET /health` answering `{"ok": true}`, and the branding routes. Routes match in registration order: the kit's own, then `routers`, then the proxy, then the static app, so a module's route wins over the proxy and the page and cannot replace a route of the kit (Task 1.9). When no client is given, `create_app` creates `httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False)` at once (the auth router needs its `ModuleAuth` before the app starts), and the lifespan closes it on shutdown. An injected client is never closed by the app.

- [ ] **Step 1:** `test_app.py`: health on both paths; `app.state` holds the three objects; a client created by the lifespan is closed after shutdown (use `with TestClient(app):`); an injected client is not closed. `test_branding.py`: carry over from the source, building the app with `create_app(Settings(...), http_client=…)`.
- [ ] **Step 2:** Run, see failures. **Step 3:** Implement `branding.py` (the two routes, copied, reading `request.app.state.settings`) and `app.py`. **Step 4:** Replace the helper in `test_auth.py` with `create_app`. Run everything, `OK`.
- [ ] **Step 5: Commit.** `feat(bff): application factory with lifespan-owned resources, health and branding`

### Task 1.5: The deny-by-default proxy

**Files:** Create `packages/bff/src/eneo_module_bff/proxy.py`, `packages/bff/tests/test_proxy.py`.
Source: `STT/backend/app/main.py` lines 134–306 and 691–750, `STT/backend/tests/test_eneo_proxy_auth.py`.

**Interfaces — Produces:**

```python
class ProxyRule(NamedTuple):
    methods: frozenset[str]
    pattern: re.Pattern[str]          # matched with fullmatch against the path after /api/eneo/

RESOURCE_ID = r"[^/]+"
def rule(methods: str | Iterable[str], pattern: str) -> ProxyRule: ...   # rule("GET", r"flows/$")
def leaves_route(path: str) -> bool: ...                                   # the source's _leaves_route, and a control character or backslash
def proxy_router(rules: Sequence[ProxyRule]) -> APIRouter: ...             # GET|POST|PATCH /api/eneo/{path:path}
```

Changes from the source, and only these:
- The rules are an argument. The kit defines none.
- `_resolve_proxy_path`'s acceptance of a path without its trailing slash is removed: it existed because `next dev` strips the slash. A path must match a rule as written.
- `http_client`, `settings` and auth headers come from `request.app.state` and `deps.upstream_auth_headers`.
- The 403 body (`"Eneo resource is not exposed"`), the 502 body and the response handling are copied unchanged. The request headers are the one deliberate departure from "copy unchanged": the source drops a denylist and forwards the rest, so `Transfer-Encoding`, `Forwarded`, `X-Forwarded-*` and the like reach Eneo, which serves every user on one pool with the service key. The kit forwards an allowlist instead, `FORWARDED_REQUEST_HEADERS = {accept, accept-language, content-type, idempotency-key, if-match, if-none-match}`, plus what a module adds with `create_app(forward_request_headers=...)` (never a credential or framing header). The credentials are still set by `upstream_auth_headers`.

- [ ] **Step 1:** Carry over `test_eneo_proxy_auth.py` as `test_proxy.py`. Build the app with `create_app(..., proxy_rules=[rule("GET", r"flows/$"), rule({"GET", "POST"}, rf"flows/{RESOURCE_ID}/runs/$")], http_client=FakeProxyClient())`. Remove access-code cases and the slash-stripping cases. Add: with `proxy_rules=()` every path is 403 and the fake client records no call; `flows/%2E%2E/runs/`, a path containing `?` and one containing `#` are 403 with no upstream call.
- [ ] **Step 2:** Run, see failures. **Step 3:** Carry the code over; `create_app` includes `proxy_router(proxy_rules)`. **Step 4:** Run, `OK`.
- [ ] **Step 5: Commit.** `feat(bff): deny-by-default proxy to Eneo with both credentials`

### Task 1.6: Upload forwarding and signed-file streaming

**Files:** Create `packages/bff/src/eneo_module_bff/transport.py`, `packages/bff/tests/test_transport.py`.
Source: `STT/backend/app/main.py` lines 61–84, 309–359 and 464–593; `STT/backend/tests/test_upload_proxy.py`, `test_audio_proxy.py`.

**Interfaces — Produces:**

```python
async def forward_upload(request: Request, upstream_path: str, upload_file: UploadFile) -> Response:
    """Re-post one multipart file to {ENEO_BACKEND_URL}/api/v1/{upstream_path} with both credentials.
    The time budget is settings.upload_proxy_timeout_seconds, lowered (never below 60 s) by the request's
    X-Upload-Timeout-Seconds header. 504 on timeout, 502 when Eneo cannot be reached, 403 for a path that
    leaves its route."""

async def stream_signed(request: Request, *resource: str, mint_path: str, unavailable: str) -> Response:
    """Mint (or reuse, per session and mint path) Eneo's signed URL and stream the file through with Range."""
```

Changes from the source, and only these: `upstream_url` becomes `upstream_path` (the function prepends the base URL); the signed-URL cache is `request.app.state.signed_urls`, created by `create_app`, not a module global; `settings`, the client and auth headers come from the app.

- [ ] **Step 1:** Carry over the two test files into `test_transport.py`. The test app is `create_app(...)` plus two routes declared in the test, each with `Depends(require_session)` (and `require_same_origin` for the upload), calling the two functions. Keep every case: timeout budget, 504, 502, Range headers forwarded, cache reuse, a rejected URL dropped from the cache, `Cache-Control: private, no-store`.
- [ ] **Step 2:** Run, see failures. **Step 3:** Carry the code over. **Step 4:** Run, `OK`.
- [ ] **Step 5: Commit.** `feat(bff): upload forwarding and signed-file streaming as functions for a module's routes`

### Task 1.7: Serving the UI

**Files:** Create `packages/bff/src/eneo_module_bff/web.py`, `packages/bff/tests/test_web.py`. Modify `app.py` (call it when `static_dir` is given).

The code below ran in a trial on 2026-10-01 (Vite build, Chromium and WebKit, no CSP errors).

```python
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "media-src 'self' blob:",
        "font-src 'self'",
        "connect-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
    ]
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
}


def add_security_headers(app: FastAPI, overrides: dict[str, str] | None = None) -> None:
    """Every response gets the headers unless the route set its own (a same-origin PDF preview, a logo)."""
    headers = {**SECURITY_HEADERS, **(overrides or {})}

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        for name, value in headers.items():
            response.headers.setdefault(name, value)
        return response


def serve_web(app: FastAPI, static_dir: Path) -> None:
    """The built UI: its assets, and its one HTML file for every page of the app.

    Registered last. A path under /api, and a path that names a file that is not there, is a 404, never HTML.
    """
    root = static_dir.resolve()
    app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def page(path: str) -> Response:
        if path.startswith("api/"):
            raise HTTPException(status_code=404)
        if "." in path.rsplit("/", 1)[-1]:
            candidate = (root / path).resolve()
            if candidate.is_file() and root in candidate.parents:
                return FileResponse(candidate)
            raise HTTPException(status_code=404)
        return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})
```

`create_app` calls `add_security_headers(app, security_headers)` always (new keyword argument `security_headers: dict[str, str] | None = None`, for a module that needs `microphone=(self)`), and `serve_web(app, static_dir)` last when `static_dir` is given.

- [ ] **Step 1:** `test_web.py` with a temporary directory holding `index.html`, `assets/app.js`, `favicon.svg`: `/` and `/flows/abc` return the HTML with `no-cache`; `/assets/app.js` 200; `/assets/nope.js` 404; `/logo.png` 404; `/favicon.svg` 200; `/api/nope` 404 with JSON, not HTML; `/../settings.py`-style traversal 404; every response carries the five headers; a route that sets its own `Content-Security-Policy` keeps it; an override replaces `Permissions-Policy`.
- [ ] **Step 2:** Run, see failures. **Step 3:** Add the code. **Step 4:** Run, `OK`.
- [ ] **Step 5: Commit.** `feat(bff): serve the built UI with security headers and a fallback that never answers HTML for a missing file`

### Task 1.8: Running it, and the public names

**Files:** Create `packages/bff/src/eneo_module_bff/serve.py`, `packages/bff/tests/test_serve.py`. Modify `__init__.py`, `packages/bff/README.md` (new).

```python
import uvicorn
from fastapi import FastAPI

WS_MAX_MESSAGE_BYTES = 128 * 1024
WS_MAX_QUEUE = 16


def serve(app: FastAPI | str, *, host: str = "0.0.0.0", port: int = 3001, **overrides: object) -> None:
    """Run the module: one worker (the session store is process-local), no access log (the callback URL
    carries a ticket), and bounded WebSocket buffers."""
    options: dict[str, object] = {
        "host": host,
        "port": port,
        "workers": 1,
        "access_log": False,
        "ws_max_size": WS_MAX_MESSAGE_BYTES,
        "ws_max_queue": WS_MAX_QUEUE,
    }
    if "workers" in overrides or "access_log" in overrides:
        raise ValueError("workers and access_log are fixed: one replica, and no ticket in the logs")
    uvicorn.run(app, **{**options, **overrides})
```

`__init__.py` exports exactly: `__version__`, `create_app`, `serve`, `Settings`, `Organization`, `load_settings`, `ModuleSession`, `ModuleUser`, `ProxyRule`, `rule`, `RESOURCE_ID`, `require_session`, `require_same_origin`, `upstream_auth_headers`, `forward_upload`, `stream_signed`.

- [ ] **Step 1:** `test_serve.py`: patch `uvicorn.run`, call `serve("main:app")`, assert the six options; `serve(app, workers=2)` and `serve(app, access_log=True)` raise `ValueError`; `import eneo_module_bff` exposes exactly the names above (`__all__`).
- [ ] **Step 2:** Run, fail. **Step 3:** Implement; write `packages/bff/README.md` with a 15-line usage example (the template's `main.py` in Task 3.2). **Step 4:** Run the whole suite, `OK`.
- [ ] **Step 5: Commit.** `feat(bff): serve() with the kit's limits, and the package's public names`

### Phase 1 exit

- [ ] The whole suite passes. `grep -rn "access_code\|AUTH_MODE\|DEMO_SPACE\|flows/" packages/bff/src` prints nothing (no speech-to-text route, no access-code remnant).
- [ ] `grep -n "^settings\|^app = \|^http_client\|^_signed_urls" -r packages/bff/src` prints nothing (no import-time state).
- [ ] `.venv/bin/pip wheel packages/bff -w dist-check --no-deps` builds a wheel (delete `dist-check/` after); install it in a fresh venv and `python -c "import eneo_module_bff; print(eneo_module_bff.__all__)"` works.
- [ ] The suite passes at the floors and at the newest versions, and `pip-audit --path <venv>/lib/python3.12/site-packages` reports nothing on both (CI runs both).
- [ ] The pull request lists, per source test file, how many test methods were carried over and which were removed and why.

---

## Phases 2–5 — Cards

Each phase starts with a **kickoff**: read the card, read the sources it names, write the phase's task list in the form of Phase 1's tasks (files, interfaces, changes from the source, test-first steps) as a comment on the phase's bead, and get it reviewed before writing code.

### Phase 2 — UI package, first part: theme, colour mode, providers, shell, brand

| | |
|---|---|
| Result | `@eneo-ai/module-kit` builds with `tsc` to `dist/` and exports the theme, `ModuleProviders`, `useColorMode`, `ModuleShell`, `BrandingProvider`, `Brand`. |
| Sources | Theme, providers, the jsdom shim and the gate changes, verified on 2026-10-01: `docs/reference/astryx-phase0-reference.patch` in this repository (a copy of speech-to-text's verified Astryx foundation; read `kit/theme/eneo.theme.ts`, `kit/ModuleProviders.tsx`, `lib/test-dom.ts`, `tests/register.cjs`, `tests/e2e/checks.ts` in it). `ModuleShell`: the code block under this table. Brand: `STT/frontend/components/Brand.tsx`, `STT/frontend/lib/read-branding.ts`. Do not recreate the theme from memory. |
| Theme | Copy `eneo.theme.ts` unchanged. Build with `npm run astryx -- theme build src/theme/eneo.theme.ts -o src/theme/built/eneo.css`. The built files go in their own folder (beside the source the bundler resolves the `.ts` and silently uses runtime styles) and are committed; CI rebuilds and fails on a diff. |
| Colour mode | New, per design K9: `ColorModeProvider` reads `localStorage["theme"]` (`light`, `dark`, `system`) before the first render, follows `prefers-color-scheme` for `system`, writes the choice back, and passes the mode to Astryx's `<Theme mode>`. `useColorMode()` returns `{ mode, setMode }`. No inline script, no cookie, no dependency. |
| Providers | `ModuleProviders({ children, linkComponent? })`: colour mode, `Theme` with the built theme, `InternationalizationProvider locale="sv-SE"` with Astryx's `sv-SE.json`, and Astryx's `LinkProvider` when `linkComponent` is given. |
| Brand | `BrandingProvider` fetches `/api/branding` once; `Brand` renders the organisation's logo or name and the product name passed as a prop (not the literal "Tal till text"). While the answer is pending it renders the product name alone (design K10). Dark-mode logo swap through CSS on `[data-theme]`, not Tailwind's `dark:`. |
| Package | `peerDependencies`: `react`, `react-dom` `>=19`, `@astryxdesign/core` `0.6.3`, `@stylexjs/stylex` `0.19.1`. `exports`: `.`, `./theme.css`, `./layers.css` (`@layer reset, astryx-base, astryx-theme;`). `devDependencies` include `@astryxdesign/cli` `0.6.3` and an `astryx` script. |
| Tests | node:test with jsdom, as `STT/frontend/lib/test-dom.ts` does, including its dialog and popover shim (in the patch). Cases: the shell has one main region, a named navigation landmark and the Swedish skip link; the stored mode is applied on the first render; `system` follows the media query; `Brand` shows the name alone until branding arrives. |
| Out of scope | Session screens (Phase 4), the integration manifest (Phase 5), anything from a router, Tailwind, next-themes. |
| Exit | `npm run -w packages/ui build` and its tests pass; CI has a `ui` job; the theme freshness check is in CI. |

`ModuleShell` (ran in the 2026-10-01 trial with its test: one main region, a `nav` named by `label`, the Swedish skip link):

```tsx
import type { ReactNode } from "react";
import { AppShell } from "@astryxdesign/core/AppShell";
import { TopNav } from "@astryxdesign/core/TopNav";

/** A page's frame. It holds no state: the page that renders it says what the bar shows. */
export function ModuleShell({ label, heading, end, banner, children }: {
  label: string;          // the navigation landmark's name
  heading: ReactNode;     // the brand, or a way back and a title
  end?: ReactNode;        // the account menu, or what a page shows in its place
  banner?: ReactNode;     // a notice for the whole page
  children: ReactNode;
}) {
  return (
    <AppShell height="auto" mobileNav={false} contentPadding={4} banner={banner} topNav={<TopNav label={label} heading={heading} endContent={end} />}>
      {children}
    </AppShell>
  );
}
```

`AppShell` renders the skip link and the `role="main"` region: a page renders no `<main>` of its own. A `VStack` stretches its children to full width, so every page caps its content with `Layout contentWidth`.

### Phase 3 — The template

| | |
|---|---|
| Result | `template/` is the smallest working module: sign in through a stub Eneo, see one page that lists flows through the proxy, sign out; one container, port 3001. |
| Backend | `template/backend/main.py`: `app = create_app(title=…, routers=[router], proxy_rules=[rule("GET", r"flows/$")], static_dir=…)`, with a comment showing where a module adds routes (on `router`, an `APIRouter`) and rules. `requirements.txt` pins `eneo-module-bff`. Until the first release it pins a commit: `eneo-module-bff @ git+https://github.com/eneo-ai/eneo-module-kit@<full sha>#subdirectory=packages/bff`; CI installs the workspace copy with `pip install -e packages/bff` first. |
| Backend test (Review Focus 5) | `template/backend/tests/test_routes.py` walks `app.routes`: every route under `/api/` except `/api/auth/*`, `/api/healthz` and `/api/branding*` must have `require_session` among its dependencies, and every route with a write method must also have `require_same_origin`. A module author who forgets one gets a failing test. |
| Stub Eneo | `template/stub-eneo/server.py` (standard library or FastAPI): `/module-login` redirects to the callback with a ticket and the unchanged `state`; `POST /api/v1/module-auth/token/`, `GET …/session/`, `POST …/token/refresh/`; `GET /api/v1/flows/` with two flows. Model the payloads on `STT/backend/tests/test_module_auth.py` (`token_payload`) and `STT/frontend/tests/e2e/stub-server.py`. It checks that both credentials arrive and answers 401 otherwise. |
| Web | `template/web`: Vite + React + TypeScript, `react-router` in library mode, `@eneo-ai/module-kit`. `src/main.tsx` imports `layers.css`, Astryx's `reset.css` and `astryx.css`, the kit's `theme.css`, wraps the app in `ModuleProviders`. Pages: `/` (sign-in button → `/api/auth/login`), `/flows` (a `List` of flows from `/api/eneo/flows/`). A minimal `RequireSession` component asks `/api/auth/status` and shows the sign-in page when unauthenticated; Phase 4 replaces it. `vite.config.ts` proxies `/api` to the BFF in development. The entry file shape ran in the 2026-10-01 trial. |
| Container | `template/Dockerfile`: Node 22 builds `web/dist`; `python:3.12-slim` runtime installs the backend's requirements, copies `dist`, runs `python -c "from eneo_module_bff import serve; serve('main:app')"` as a non-root user; `HEALTHCHECK` on `http://127.0.0.1:3001/health`. No Node in the runtime image, no supervisord. `docker-compose.yml` with the module and the stub; `.env.example` with every variable `load_settings` reads. |
| Browser tests | Playwright in `template/web/tests/e2e`: sign in through the stub, land on `/flows`, sign out; a deep link to `/flows` after sign-in; the console has no error and no CSP violation, in Chromium, WebKit and Firefox against the **built container or built files**, not the dev server. |
| Accessibility gate | Copy `checks.ts`, `a11y.spec.ts` and `harness.spec.ts` from `STT/frontend/tests/e2e`, then apply the changes `docs/reference/astryx-phase0-reference.patch` makes to those three files, and write a `screens.ts` with the template's states: `signin`, `flows`, `flows-empty`, `flows-error`, `account-menu`. Projects: phone 320 and 390, laptop 1440 light and dark, 200 % zoom, forced colours, reduced motion. This copy is known debt: it becomes a package export when a second module needs it. |
| Agent setup | `template/AGENTS.md` (module rules: Astryx only, the CLI loop, Swedish, the gate, where to add routes and rules, never remove `require_session`), `template/CLAUDE.md` importing it and `web/AGENTS.md`, the `astryx` script, and `web/AGENTS.md` generated by `npm run astryx -- init --features agents`. |
| Other | `.devcontainer` with Node 22 and Python 3.12; `template/.github/workflows/ci.yml` for a module's own CI (backend tests, web build, gate subset, image build); `docs/new-module.md`: copy the template (`npx degit eneo-ai/eneo-module-kit/template eneo-mod-<name>`), rename, install the module in Eneo's admin (module key, callback URL `https://<domain>/api/auth/callback`, service key), set the environment, run the smoke test in Eneo's `MODULES.md`. `docs/module-contract.md`: design section 2 and 5 expanded with request and response examples taken from the BFF's tests. |
| Out of scope | Any speech-to-text feature. A second example page. A database. More than one allowlisted route. |
| Exit | `docker compose up` in `template/` serves the module on 3001 against the stub; the browser tests and the gate pass; this repository's CI builds the template against the workspace packages. |

### Phase 4 — UI package, second part: the session client

**Gate from outside this repository:** start only when speech-to-text's Phase 1 (Astryx port of the sign-in page, session warning and leave question) is merged into its `feat/astryx` branch. That phase is where the native-dialog contract is proven; this phase carries the proven version over.

| | |
|---|---|
| Result | `@eneo-ai/module-kit/session` exports `SessionProvider`, `useSessionUser`, `RequireSession`, the sign-in screen, the session-end warning and the signed-out cover. The template's minimal `RequireSession` is deleted. |
| Sources | `STT/frontend/components/AuthGate.tsx`, `SessionEndWarning.tsx`, `app/LoginPage.tsx`, `app/inloggad/SignedInAgain.tsx`, `lib/login-state.ts`, `lib/session-keepalive.ts`, `lib/user-identity.ts`, the session part of `lib/api.ts` (`request`, `replayable`, `sessionEnded`), and their tests (`signed-out.test.ts`, `login-state.test.ts`, `session-keepalive.test.ts`, `user-identity.test.ts`, `tests/e2e/session-cover.spec.ts`), all from the merged Phase 1 state, not from `f81a7dd`. |
| Seams | One session-state instance shared by the gate and by `fetchWithSession` (the package's request function): signed out, nothing but `/api/auth/*` leaves the page; a read, or a write with an `Idempotency-Key`, waits for the renewal and is sent once more; other writes fail with a session-expired error. `onIdentity(user)` is called and awaited before children are shown (speech-to-text cleans drafts there). `signedOutControls` is a slot for what stays reachable while signed out. Navigation is a `navigate(path)` prop. No import of recording, drafts or a router. Access-code branches are removed. |
| Keep | Ordered status answers; keepalive cleanup; renewal in its own window with `BroadcastChannel`; wrong-user handling (`fel=annan-anvandare`, `fel=utgangen`); the warning five minutes before the end; focus given back after renewal; the signed-out contract: page inert and invisible, a modal sign-in dialog with an opaque backdrop, page dialogs closed while signed out. |
| Tests | The carried-over unit tests, and `session-cover.spec.ts` adapted to the template (a page dialog on the example page). The stub Eneo gains a way to end the session on demand. |
| Out of scope | Changing any behaviour above. A second auth mode. |
| Exit | The template signs in, warns, covers and renews with the package's session client; unit tests, browser tests and the gate pass. |

### Phase 5 — Astryx integration, docs and the first release

**Gate from outside this repository:** the owner's answers on public or private packages and the `@eneo-ai` npm scope (`docs/design.md` section 7).

| | |
|---|---|
| Integration | `packages/ui/astryx.integration.mjs` created with `npm run astryx -- integration add …`: page templates `eneo-signin`, `eneo-module-page` (shell + list); one doc topic `eneo-module` (the rules in `template/AGENTS.md`, and the loop for a new page); at most 8 agent lines. `npm run astryx -- integration pack --check` passes. In the template, `npm run astryx -- build "en sida i en Eneo-modul"` proposes the kit's template first, and the regenerated `web/AGENTS.md` carries the kit's lines. |
| Release | Version `0.1.0` of both packages, a changelog, a tag. Publishing commands are run by the owner or with the owner's explicit go. The template's `requirements.txt` and `package.json` then pin `0.1.0`. |
| Packed-consumer check | In a clean directory outside the repository: copy `template/`, install the packed npm tarball and the built wheel (not the workspace), build, run the browser tests. |
| Docs | `README.md` updated from "not built yet" to how to start a module; `docs/new-module.md` verified by following it once from scratch. |
| Hand-over | Comment on speech-to-text's adoption bead (`stt-plan-c-module-kit-gwh.3` in that repository's board) with the released versions and every place the kit differs from speech-to-text's own code. |
| Out of scope | Codemods, a `testing` or `a11y` export, a skill, an MCP server. |
