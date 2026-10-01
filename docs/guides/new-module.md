# Start a new module from the template

Purpose: take `template/` from a copy to a module that signs in through Eneo, runs in one container and has its own CI, in order.
Read this when: you are creating a module, or you want to know what the template gives you and what CI proves about it.
Related: [build a module](build-a-module.md) (the backend in detail), [UI package](ui-package.md), [local development](local-development.md), [configuration](configuration.md), [security checklist](security-checklist.md), [architecture](../architecture.md#the-template-and-its-image), `template/README.md`, `template/AGENTS.md`.

`template/` is the smallest working module: a sign-in page, one page behind the login that lists Eneo's flows, one route of its own, and everything around them. It imports the two packages and copies none of their code. Built and tested. Not built yet: the session client (the warning before the login ends, renewal, the cover while signed out: the template's `RequireSession` asks `/api/auth/status` once per page load and nothing more) and the first release of the packages.

## What you get

| Path in `template/` | What it is |
|---|---|
| `backend/main.py` | `build_app(...)`: the kit's `create_app` with this module's `PROXY_RULES` (one: `GET flows/`) and its router. The image runs it with `serve('main:build_app', factory=True)`. |
| `backend/routes.py` | The module's own routes on `router`: one, `GET /api/example`, behind `require_session`. |
| `backend/tests/` | Run without Eneo. `test_app.py`: the page, the deep link, 404s, the route, the proxy and its allowlist. `test_routes.py` with `guards.py`: fails when a route lacks `require_session` (or a write lacks `require_same_origin`). |
| `backend/requirements.txt` | The BFF, pinned to a commit of the kit until its first release (`<full sha>` is a placeholder). |
| `stub-eneo/server.py` | Eneo's side of the contract, stdlib only, for development and tests. Never shipped in the image. See [local development](local-development.md). |
| `web/` | A Vite + React + react-router app on `@eneo-ai/module-kit`: `main.tsx` (providers, stylesheets), `App.tsx` (routes), `Frame.tsx` (the shell every page uses), `config.ts` (`PRODUCT_NAME`), `RequireSession.tsx`, `session.ts`, `AccountMenu.tsx`, `pages/SignIn.tsx`, `pages/Flows.tsx`. |
| `web/tests/e2e/` | Playwright against the built app, and the accessibility gate. |
| `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example` | One image, one process, port 3001. The compose file runs the module and the stub. `.env.example` lists every variable the backend reads. |
| `.devcontainer/` | Python 3.12 and Node 22, ports 3001, 5173 and 8411 forwarded. |
| `.github/workflows/ci.yml` | A module's own CI. |
| `AGENTS.md`, `CLAUDE.md`, `web/AGENTS.md` | The module's rules for agents; `web/AGENTS.md` is the block `astryx init --features agents` generates. |

## Before the first release

Neither package is published. `web/package.json` names `@eneo-ai/module-kit` `0.1.0`, and `backend/requirements.txt` holds a placeholder, so a plain copy cannot install them yet. Until the release:

| Package | How a module gets it |
|---|---|
| `@eneo-ai/module-kit` | The packed tarball: [UI package: install](ui-package.md#install). Never a `file:` folder (two copies of React). |
| `eneo-module-bff` | A commit pin in `backend/requirements.txt` (replace `<full sha>` with the commit of this repository you start from), or `pip install /path/to/eneo-module-kit/packages/bff` for work on your own machine. |

After the release both are version pins, and a plain `docker build -t my-module .` and `docker compose up --build` work as `template/README.md` says. Today they do not: the build fails at the BFF install. Use the build context below.

## 1. Copy and rename

From a checkout of this repository:

```bash
cp -R template ../eneo-mod-<name> && cd ../eneo-mod-<name>
```

(`npx degit eneo-ai/eneo-module-kit/template eneo-mod-<name>` does the same from GitHub once `template/` is on the default branch; not checked.) Then:

| Change | Where |
|---|---|
| The module's name in the top bar and the page's `<h1>` | `PRODUCT_NAME` in `web/src/config.ts` |
| The browser tab | `<title>` in `web/index.html` |
| The module key (lowercase kebab-case) | `MODULE_KEY` in `.env` (step 3). The stub's key is `eneo-module`: set `STUB_MODULE_KEY` to change it. |
| The API title | `title=` in `backend/main.py` |

A module in its own repository makes the copy its root: `template/` becomes `.`.

## 2. Install the packages

```bash
# the UI package: pack it in the kit checkout (see the UI package guide), then, in the module's web/ folder
npm install /path/to/dir/eneo-ai-module-kit-0.1.0.tgz

# the BFF: a virtual environment for the module, from the kit checkout
python3.12 -m venv .venv
.venv/bin/pip install /path/to/eneo-module-kit/packages/bff
```

`npm install <tarball>` rewrites the dependency in `web/package.json` to a `file:` path of the tarball; keep that out of a commit you share, or put the tarball somewhere stable.

## 3. Set the environment

```bash
cp .env.example .env
```

For the stub Eneo the values work as they are. Change them for a real Eneo:

| Variable | Set to |
|---|---|
| `ENEO_BACKEND_URL`, `ENEO_PUBLIC_URL` | Eneo's address from the module's network, and from the browser |
| `MODULE_PUBLIC_URL` | This module's own address. The callback is `MODULE_PUBLIC_URL/api/auth/callback` |
| `MODULE_KEY`, `ENEO_API_KEY` | The module key and service key registered in Eneo (step 8) |
| `SESSION_SECRET` | At least 32 random characters: `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `COOKIE_SECURE` | `false` only over plain http. Production is https and `true` |

Every variable, its default and its check: [configuration](configuration.md).

## 4. Run it against the stub

From the module's folder. This is the built app, served by the backend, as it runs in the image.

```bash
# the UI, built to web/dist
(cd web && npm run build)

# the stub Eneo, on 8411
python3 stub-eneo/server.py
```

```bash
# the module, on 3001, in a second terminal: the variables of .env.example (or .env), then the backend
cd backend
set -a; . ../.env; set +a                              # .env.example has the same values
export ENEO_BACKEND_URL=http://127.0.0.1:8411          # .env names the stub as docker compose reaches it: stub-eneo
../.venv/bin/python -c "from eneo_module_bff import serve; serve('main:build_app', factory=True)"
```

The backend serves `web/dist` beside its source by default (`STATIC_DIR` overrides it; the image sets it). Open `http://localhost:3001` and sign in: the stub signs everyone in as Erik Lund. The curl walk of [local development](local-development.md) shows each step of the handoff.

To work on the UI with hot reload: the stub, the backend (as above, but `MODULE_PUBLIC_URL=http://localhost:5173`), and `cd web && npm run dev`. Vite proxies `/api` to the backend on 127.0.0.1:3001 (`web/vite.config.ts`, from the template's README; this one is not checked here).

## 5. Test it

```bash
# from the module's folder, in the module's virtual environment
.venv/bin/python -m unittest discover -s backend/tests -t backend
.venv/bin/python -m unittest discover -s stub-eneo

# in web/: builds, starts the stub and the backend itself, runs the browsers and the gate
cd web && PYTHON="$(pwd)/../.venv/bin/python" npm run test:e2e
```

`npm run test:e2e` needs the Playwright browsers once: `npx playwright install --with-deps chromium webkit firefox`. It builds first, then starts the stub and the backend on ports of its own: `E2E_APP_PORT` (default 3011) and `E2E_STUB_PORT` (default 8011); `PYTHON` names, as an absolute path (a relative one fails), the interpreter with `eneo-module-bff` installed (without it the config looks for `../.venv` beside the kit's checkout, then `python3`); `E2E_EXTERNAL_URL` tests a module that is already running (the container) instead. What it proves: [below](#what-ci-proves). Read a failure from `web/test-results/`: the trace of a failed test is kept (`npx playwright show-trace <trace.zip>`), each gate test writes `findings.json` (the measurements), and `SHOTS=1` also writes a picture of every state to `web/test-results/shots/`.

## 6. Build the image

One image, one process: Node 22 builds `web/dist`, a `python:3.12-slim` runtime image installs the backend's requirements, copies the build, and runs `serve('main:build_app', factory=True)` as a non-root user (uid 10001). `HEALTHCHECK` is `/health` on 3001. No Node and no supervisor at run time.

Until the release, give the build a context named `kit` that holds the packed UI package and a copy of the BFF. The Dockerfile then uses them in place of the pins (this is what the kit's CI does):

```bash
# in the kit checkout
npm ci && npm run -w packages/ui build
mkdir kit-context
npm pack -w packages/ui --pack-destination kit-context
cp -R packages/bff kit-context/bff
docker build --build-context kit=kit-context -t my-module template
```

After the release: `docker build -t my-module .` in the module's folder.

Run it against the stub without compose (the stub must listen beyond localhost for the container to reach it: `STUB_HOST=0.0.0.0`, and `host.docker.internal` names the host on Docker Desktop and OrbStack; on Linux add `--add-host=host.docker.internal:host-gateway`):

```bash
STUB_HOST=0.0.0.0 python3 stub-eneo/server.py &
docker run -d --name my-module -p 127.0.0.1:3001:3001 \
  -e ENEO_BACKEND_URL=http://host.docker.internal:8411 -e ENEO_PUBLIC_URL=http://localhost:8411 \
  -e MODULE_PUBLIC_URL=http://localhost:3001 -e MODULE_KEY=eneo-module -e ENEO_API_KEY=stub-service-key \
  -e SESSION_SECRET=change-me-to-at-least-32-random-characters -e COOKIE_SECURE=false my-module
curl -fsS http://localhost:3001/health        # {"ok":true}
```

With `docker compose up --build` (after the release, `cp .env.example .env` first) the stub runs as a second service, `stub-eneo` on 8411.

## 7. Add to it

| To add | Do |
|---|---|
| A route of the module | In `backend/routes.py`, on `router`, with `Depends(require_session)` (and `require_same_origin` for a write). `backend/tests/test_routes.py` fails without them. |
| A call to Eneo | One `rule(...)` in `PROXY_RULES` in `backend/main.py` per Eneo route, with the methods it needs, and a test. No catch-all. For an upload or a file, see [build a module](build-a-module.md). |
| A page | A route in `web/src/App.tsx`, inside `RequireSession` when it needs a session, rendering `<Frame>`. Build it from Astryx components: `npm run astryx -- build "<idea>"` and `npm run astryx -- component <Name>` in `web/`, never a guessed prop. Its states go in `web/tests/e2e/screens.ts`, so the gate measures them. |
| A design-system fix | Once, in the kit's theme ([UI package](ui-package.md#fix-a-shortfall-once)), not in a page. |

The module's rules for people and agents are in its `AGENTS.md`.

## 8. Register it in Eneo and go live

In Eneo's admin, register the module: its module key, the callback URL `https://<your domain>/api/auth/callback` (that is `MODULE_PUBLIC_URL` plus `/api/auth/callback`), and a service key, which becomes `ENEO_API_KEY`. The steps and the smoke test are in Eneo's [module operator guide](https://github.com/eneo-ai/eneo/blob/develop/docs/deployment/MODULES.md). Then walk the [security checklist](security-checklist.md).

## CI

A module's own CI is `template/.github/workflows/ci.yml`. In a module's repository, move it to the root as `.github/workflows/ci.yml`.

## What CI proves

The kit's CI (`.github/workflows/ci.yml`) builds the template against the packages of the same commit, not published ones, so the two packages are always proven to work together ([K1](../decisions/k01-one-repository-three-parts.md)). A module's own CI runs the same three kinds of check against its pinned versions.

| Job (kit) | What it runs | What it proves |
|---|---|---|
| `bff` (lowest and newest versions) | The BFF suite, then `pip-audit` | The package works at the lowest and the newest dependency versions its ranges allow, with no known advisory in either set |
| `ui` | `npm run -w packages/ui lint`, `npm test`, `build`, then `theme:build` and `git diff --exit-code` | The UI package type-checks, passes its tests, builds, and its committed theme is not stale |
| `template-backend` | The template's backend and stub tests, with the workspace BFF | The module's routes are guarded, the allowlist is the one route, the page and 404s behave |
| `template-web` | `npm run -w template/web test:e2e` in Chromium, WebKit and Firefox, and the gate | Sign-in through the stub, the shell (one main region, a named navigation, the skip link), the proxied route, the module's own route, sign-out, a deep link without a session, 401 and 403 and 404 where they belong, the strict CSP header, stored and system dark mode, the account menu's colour choice, a logo for each mode, a failing Eneo with retry; every test fails on a console error or a CSP violation; and the gate (below) |
| `template-image` | `docker build` with the `kit` context, `docker run`, `curl /health` | The image builds from the workspace packages and the app starts and answers |

The gate runs `a11y.spec.ts` for every state in `screens.ts` (`signin`, `flows`, `account-menu`, `flows-empty`, `flows-error`) in eight projects: phone 320 light, phone 390 light and dark, laptop 1440 light and dark, 200 % zoom, forced colours, reduced motion. It checks axe (every WCAG violation blocks), every control named, placeholder contrast, target sizes (24 px with a mouse, 44 px under `pointer: coarse`), reflow at 320 px and 200 % zoom, text spacing, and no endless motion with reduced motion. `header-fit.spec.ts` checks that at 320 px with text spacing the brand and the account button keep apart. `harness.spec.ts` tests the gate itself. Thresholds are never lowered. The gate's code is a copy of speech-to-text's: known debt, to become a package export when a second module needs it.
