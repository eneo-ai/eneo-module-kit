# Start a new module from the template

Purpose: take `template/` from a copy to a module that signs in through Eneo, runs in one container and has its own CI, in order.
Read this when: you are creating a module, or you want to know what the template gives you and what CI proves about it.
Related: [build a module](build-a-module.md) (the backend in detail), [UI package](ui-package.md), [local development](local-development.md), [configuration](configuration.md), [security checklist](security-checklist.md), [architecture](../architecture.md#the-template-and-its-image), `template/README.md`, `template/AGENTS.md`.

`template/` is the smallest working module: a sign-in page, one page behind the login that lists Eneo's flows, one route of its own, and everything around them. It imports the two packages and copies none of their code. Built and tested, on the kit's session client (`@eneo-ai/module-kit/session`: it keeps the login, warns before it ends and covers the page for a new login in place). The UI package also supplies Astryx reference templates and agent guidance. The first release of the packages is pending.

## What you get

| Path in `template/` | What it is |
|---|---|
| `backend/main.py` | `build_app(...)`: the kit's `create_app` with this module's `PROXY_RULES` (one: `GET flows/`) and its router. The image runs it with `serve('main:build_app', factory=True)`. |
| `backend/routes.py` | The module's own routes on `router`: one, `GET /api/example`, behind `require_session`. |
| `backend/tests/` | Run without Eneo. `test_app.py`: the page, the deep link, 404s, the route, the proxy and its allowlist. `test_routes.py` with `guards.py`: fails when a route lacks `require_session` (or a write lacks `require_same_origin`). |
| `backend/requirements.lock` | Everything the BFF depends on, with hashes: a generated, hash-pinned `uv pip compile` of the BFF's requirements. Install it first. The kit's CI fails when it drifts from the BFF's requirements. |
| `backend/requirements.txt` | The BFF itself, pinned to a commit of the kit until its first release (`<full sha>` is a placeholder). |
| `stub-eneo/server.py` | Eneo's side of the contract, stdlib only, for development and tests. Never shipped in the image. See [local development](local-development.md). |
| `web/` | A Vite + React + react-router app on `@eneo-ai/module-kit`: `main.tsx` (providers, stylesheets), `App.tsx` (routes), `Frame.tsx` (the shell every page uses), `config.ts` (`PRODUCT_NAME`), `session.ts` (`signOut`, which says `false` when the backend refuses or gives no answer so that `AccountMenu` can say so in a toast, and `getJson` over `fetchWithSession`), `AccountMenu.tsx` (who is signed in, the colour mode, Version, which opens the kit's `VersionInfo` in a dialog, and signing out), `pages/Flows.tsx`. The sign-in screen, the gate and the page a login window lands on (`/inloggad`) come from the kit; `App.tsx` routes them. |
| `web/package-lock.json`, `web/vendor/`, `web/scripts/relock.mjs` | The web app's own lock, with hashes. Before the release it finds `@eneo-ai/module-kit` in `web/vendor/` (the packed tarball, not committed); `relock.mjs` regenerates the lock. Both go when the package is published. |
| `web/tests/e2e/` | Playwright against the built app, and the accessibility gate. |
| `web/scripts/ci-failure.mjs` | `npm run ci:failure`: what failed in a CI run, read on your machine ([quality](quality.md#a-red-ci-job)). |
| `Dockerfile`, `.dockerignore`, `.env.example` | One image, one process, port 3001, its base images pinned by digest. `.env.example` lists every variable the backend reads, and `MODULE_VERSION`. |
| `docker-compose.yml`, `docker-compose.override.yml`, `docker-compose.traefik.yml` | Production: the published image, chosen by `MODULE_VERSION`, read-only and without capabilities. Development: merged by `docker compose up`, it builds the image and runs the stub. Traefik with HTTPS and HSTS, for a host without a proxy. See [release and deploy](deploy.md). |
| `.devcontainer/` | Python 3.12 and Node 22, ports 3001, 5173 and 8411 forwarded. |
| `.github/workflows/ci.yml`, `release.yml` | A module's own CI, which publishes the tested image as `sha-<commit>`, and its releases by tag ([CI](#ci), [release and deploy](deploy.md)). |
| `AGENTS.md`, `CLAUDE.md`, `web/AGENTS.md` | The module's rules for agents; `web/AGENTS.md` is the block `astryx init --features agents` generates. |
| `.agents/skills/eneo-module/SKILL.md` | A local skill for setup and feature work, linked from `AGENTS.md` and imported by `CLAUDE.md`. It routes agents to the existing examples, contract and checks. |

## Before the first release

Neither package is published. `web/package.json` names `@eneo-ai/module-kit` `0.1.0`, and `backend/requirements.txt` holds a placeholder, so a plain copy cannot install them yet, and a plain `docker build` fails. Until the release:

| Package | How a module gets it |
|---|---|
| `@eneo-ai/module-kit` | The packed tarball in `web/vendor/`, then `npm ci` ([step 2](#2-install-the-packages)). Not `npm install <tarball>`, which rewrites the manifest and the lock, and never a `file:` folder (two copies of React). |
| `eneo-module-bff` | Its third-party packages from `backend/requirements.lock`, then the BFF itself: a commit pin in `backend/requirements.txt` (replace `<full sha>` with the commit of this repository you start from), or `pip install --no-deps /path/to/eneo-module-kit/packages/bff` on your own machine. |

After the release both are version pins, and in a module's own folder `docker build -t my-module .` and `docker compose up --build` work. Before it, build the image with the build context of [step 6](#6-build-the-image).

## Node and Python

| What | Needs |
|---|---|
| A module that uses the UI package | Node `>=22.13.0`: the Astryx CLI's own minimum (`engines` of `@eneo-ai/module-kit`) |
| `template/web` | Node `>=22.22.0` (its `engines`) |
| Working in the kit repository (`npm ci`, the tests, the build) | Node `^22.22.2 \|\| ^24.15.0 \|\| >=26.0.0`: what the locked development tools need together (root `package.json`; a test in `packages/ui` fails when a bumped dependency asks for more) |
| The backend | Python 3.12 |

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
| The image's name | `image:` in `docker-compose.yml`: `ghcr.io/<owner>/<repository>` of the module's repository, in lower case. CI's `compose` job fails until it is |

A module in its own repository makes the copy its root: `template/` becomes `.`. Keep dotfiles when copying;
they include the skill, development environment and CI.

## 2. Install the packages

The web app. `web/package-lock.json` says that `@eneo-ai/module-kit` `0.1.0` is found in `web/vendor/eneo-ai-module-kit-0.1.0.tgz`, with no hash (it is the kit's own build, which changes with every commit); every other package is locked with its hash. Put the packed UI package there, and install from the lock:

```bash
# in the kit checkout
npm ci && npm run -w packages/ui build
npm pack -w packages/ui --pack-destination /path/to/eneo-mod-<name>/web/vendor

# in the module's web/ folder
npm ci
```

After a change of a dependency or of the kit's version, regenerate the lock: `node scripts/relock.mjs /path/to/the-tarball.tgz` (in `web/`). Do not `npm install <tarball>`: it rewrites `package.json` to a `file:` path. The tarball is not committed (`web/vendor/.gitignore`). After the release, delete `web/vendor/` and `web/scripts/relock.mjs` and run `npm install @eneo-ai/module-kit@<version>`: the lock then names the registry, with its hash.

The backend. A virtual environment for the module; the locked third-party packages first, then the BFF:

```bash
python3.12 -m venv .venv
.venv/bin/pip install --require-hashes --no-deps -r backend/requirements.lock
.venv/bin/pip install --no-deps /path/to/eneo-module-kit/packages/bff       # on your machine; a module's repository uses its commit pin instead:
# .venv/bin/pip install --no-deps -r backend/requirements.txt              # after replacing <full sha>
```

`backend/requirements.lock` is generated, not edited: its header holds the `uv pip compile` command, and `--exclude-newer` fixes the index's state so the same command gives the same file. `requirements.txt` stays: Docker, CI and the devcontainer install it after the lock, and it is where the BFF's version is pinned (after the release its one line is `eneo-module-bff==x.y.z`). After the release a module lists `eneo-module-bff==x.y.z` and its own packages in a `requirements.in` and compiles its own lock.

After installation, use the pinned CLI to discover the kit's components and page templates, then regenerate its agent instructions:

```bash
# in the module's web/ folder
npm run astryx -- build "en sida i en Eneo-modul"
npm run astryx -- docs eneo-module
npm run astryx -- init --features agents
```

The page suggestion is `eneo-module-page`; `eneo-signin` uses the shared sign-in screen. Adapt reference source at the owning route, retaining the template's existing `Frame` where it already supplies the shell. [The UI guide](ui-package.md#astryx-integration) shows how to read or materialize the templates.

## 3. Set the environment

The optional accent settings and their contrast checks are in [configuration](configuration.md). Keep the branding stylesheet link in `web/index.html`; the template already includes it and needs no custom visual CSS for the accent.

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

`npm run test:e2e` needs the Playwright browsers once: `npx playwright install --with-deps chromium webkit firefox`. It builds first, then starts the stub and the backend on ports of its own: `E2E_APP_PORT` (default 3011) and `E2E_STUB_PORT` (default 8011); `PYTHON` names, as an absolute path (a relative one fails), the interpreter with `eneo-module-bff` installed (without it the config looks for `../.venv` beside the kit's checkout, then `python3`); `E2E_EXTERNAL_URL` tests a module that is already running (the container) instead. What it proves: [below](#what-ci-proves). Read a failure from `web/test-results/`: the trace of a failed test is kept (`npx playwright show-trace <trace.zip>`), `results.json` is Playwright's report of the run, each gate test writes `findings.json` (the measurements), and `SHOTS=1` also writes a picture of every state to `web/test-results/shots/`. Where each check lives, a red CI job (`npm run ci:failure`), a test that fails only in CI (`GATE_CPU`) and the stand-still rule: [quality](quality.md).

## 6. Build the image

One image, one process: Node 22 builds `web/dist` from `web/package-lock.json` (`npm ci`), Python installs the locked packages with their hashes (`backend/requirements.lock`) and then the BFF, and a `python:3.12-slim` runtime image copies both and runs `serve('main:build_app', factory=True)` as a non-root user (uid 10001). `HEALTHCHECK` is `/health` on 3001. No Node and no supervisor at run time. The build arguments `SOURCE_REVISION`, `BUILD_DATE` and `SOURCE_URL`, which CI passes, become the image's OCI labels (`org.opencontainers.image.revision`, `created`, `source`) and the environment `/health` answers from ([configuration](configuration.md#which-build-runs)); a build without them, as the ones below, says none.

Until the release, give the build a context named `kit` that holds the packed UI package and a copy of the BFF. The Dockerfile then puts the tarball where the lock looks for it (`web/vendor/`) and installs the BFF from the copy instead of the commit pin (this is what the kit's CI does):

```bash
# in the kit checkout
npm ci && npm run -w packages/ui build
mkdir kit-context
npm pack -w packages/ui --pack-destination kit-context
cp -R packages/bff kit-context/bff
docker build --build-context kit=kit-context -t eneo-module:local template
```

After the release: `docker build -t my-module .` in the module's folder.

Run it against the stub without compose (the stub must listen beyond localhost for the container to reach it: `STUB_HOST=0.0.0.0`, and `host.docker.internal` names the host on Docker Desktop and OrbStack; on Linux add `--add-host=host.docker.internal:host-gateway`):

```bash
STUB_HOST=0.0.0.0 python3 stub-eneo/server.py &
docker run -d --name my-module -p 127.0.0.1:3001:3001 \
  -e ENEO_BACKEND_URL=http://host.docker.internal:8411 -e ENEO_PUBLIC_URL=http://localhost:8411 \
  -e MODULE_PUBLIC_URL=http://localhost:3001 -e MODULE_KEY=eneo-module -e ENEO_API_KEY=stub-service-key \
  -e SESSION_SECRET=change-me-to-at-least-32-random-characters -e COOKIE_SECURE=false eneo-module:local
curl -fsS http://localhost:3001/health        # {"ok":true,"revision":null,"build_date":null,"release":null,"source":null}
```

Or with compose. `docker compose up` merges `docker-compose.override.yml`, which runs the module from the image `eneo-module:local`, publishes port 3001 and starts the stub as a second service (`stub-eneo` on 8411). Before the release it starts the image built above; after it, `docker compose up --build` builds it. The module runs as in production, read-only and without capabilities:

```bash
cd template && cp .env.example .env && docker compose up      # then open http://localhost:3001
```

Production runs `docker-compose.yml` alone, with the published image: [release and deploy](deploy.md).

## 7. Add to it

| To add | Do |
|---|---|
| A route of the module | In `backend/routes.py`, on `router`, with `Depends(require_session)` (and `require_same_origin` for a write). `backend/tests/test_routes.py` fails without them. |
| A call to Eneo | One `rule(...)` in `PROXY_RULES` in `backend/main.py` per Eneo route, with the methods it needs, and a test. No catch-all. For an upload or a file, see [build a module](build-a-module.md). |
| A page | A route in `web/src/App.tsx`, inside `RequireSession` when it needs a session, rendering `<Frame>`; calls to the backend go through `fetchWithSession` (the template's `getJson`), and a dialog of the page is closed while `useSignedOut()` is true ([build a module](build-a-module.md#10-sessions-and-dialogs)). Build it from Astryx components: `npm run astryx -- build "<idea>"` and `npm run astryx -- component <Name>` in `web/`, never a guessed prop. Its states go in `web/tests/e2e/screens.ts`, so the gate measures them; a state that is the page as it opens also goes in `BY_ADDRESS` of `web/tests/e2e/still.spec.ts` ([quality](quality.md#what-is-on-screen-stands-still)), a control that is not pressed as the others are in a list of `web/tests/e2e/controls.spec.ts`, with its reason ([quality](quality.md#every-control-does-something)), and each state its curated ARIA snapshots ([quality](quality.md#what-a-screen-reader-is-given)). |
| A design-system fix | Once, in the kit's theme ([UI package](ui-package.md#fix-a-shortfall-once)), not in a page. |

The module's rules for people and agents are in its `AGENTS.md`. It links back to the kit's backend and
configuration guides, which are not copied into the module. From `web/`, `npm run astryx -- docs eneo-module`
reads the UI package's guidance locally.

## 8. Register it in Eneo and go live

In Eneo's admin, register the module: its module key, the callback URL `https://<your domain>/api/auth/callback` (that is `MODULE_PUBLIC_URL` plus `/api/auth/callback`), and a service key, which becomes `ENEO_API_KEY`. The steps and the smoke test are in Eneo's [module operator guide](https://github.com/eneo-ai/eneo/blob/develop/docs/deployment/MODULES.md). Then walk the [security checklist](security-checklist.md), and release and run it: [release and deploy](deploy.md).

## CI

A module's own CI is `template/.github/workflows/ci.yml`, with `release.yml` beside it; in a module's repository both move to the root's `.github/workflows/`. Every action is pinned to the commit of a release and every image to a digest, the token may only read unless a job needs more, and a newer push to a pull request replaces the older run.

| Job | What it runs |
|---|---|
| `backend` | The backend's and the stub's tests, on the locked packages |
| `web` | The browser tests in four parts, each on a runner of its own: `main` (the module in three browsers and the gate in Chromium), `devices` (the tablets and a phone on its side), `webkit` and `firefox` (the gate in each). A part that fails keeps `web/test-results` as the artifact `web-<part>-results`, which `npm run ci:failure` reads ([quality](quality.md#a-red-ci-job)); the kit's `template-web` job does the same, as `template-web-<part>-results` |
| `audit` | `pip-audit` on `backend/requirements.lock`, and `npm audit --omit=dev --audit-level=high` in `web/` |
| `compose` | `docker compose config` for the production file alone, with the Traefik overlay, and merged with the development override; and that `docker-compose.yml` pulls the image this repository publishes |
| `image` | Builds the image once, with its SBOM and provenance and the build arguments of [which build runs](configuration.md#which-build-runs); runs it as `docker-compose.yml` does until it is healthy; checks that `/health` and the revision label say the commit; keeps it as an artifact |
| `publish` | On main, after every job passed: pushes the kept image, by its digest, as `ghcr.io/<owner>/<repository>:sha-<commit>` |

`release.yml` gives that image its version when a tag `vX.Y.Z` is pushed, and builds nothing: [release and deploy](deploy.md#from-a-commit-to-a-release).

## What CI proves

The kit's CI (`.github/workflows/ci.yml`) builds the template against the packages of the same commit, not published ones, so the two packages are always proven to work together ([K1](../decisions/k01-one-repository-three-parts.md)). A module's own CI runs the same three kinds of check against its pinned versions.

| Job (kit) | What it runs | What it proves |
|---|---|---|
| `bff` (lowest and newest versions) | The BFF suite, then `pip-audit` | The package works at the lowest and the newest dependency versions its ranges allow, with no known advisory in either set |
| `ui` | `npm run -w packages/ui lint`, `npm test`, `build`, then `theme:build` and `git diff --exit-code` | The UI package type-checks, passes its tests, builds, and its committed theme is not stale |
| `template-backend` | The template's hash-locked third-party packages, then the workspace BFF, then the template's backend and stub tests; then it regenerates `backend/requirements.lock` from the BFF's requirements (`uv pip compile`, at the date the lock records) and fails on any difference | The module's routes are guarded, the allowlist is the one route, the page and 404s behave, and the lock is the BFF's current requirements |
| `template-web` | `npm run -w template/web test:e2e`, in the four parts a module's `web` job has: the module in Chromium, WebKit and Firefox, and the gate in Chromium, on the tablets, in WebKit and in Firefox | Sign-in through the stub, the shell (one main region, a named navigation, the skip link), the proxied route, the module's own route, sign-out, a deep link without a session, 401 and 403 and 404 where they belong, the strict CSP header, stored and system dark mode, the account menu's colour choice, the release, commit and build time of a release's build in the version dialog (the test backend is given them), a logo for each mode, a failing Eneo with retry, a sign-out that the backend refuses or that gets no answer (the person stays on the page and a toast says so, and trying again signs out), and the session cover (`session-cover.spec.ts`: a page dialog closed and back with its edit after the new login, nothing but the new login closes the sign-in dialog, someone else's login keeps the page covered, the warning five minutes before the end, the dialog scrolling as a whole at 320 x 200); every test fails on a CSP violation, a redirect outside the sign-in, and a console error, uncaught error or failed request it did not declare ([quality](quality.md#what-every-test-watches-for)); and the gate (below) |
| `template-audit` | `pip-audit` on `template/backend/requirements.lock`, and `npm audit --omit=dev --audit-level=high` on `template/web/package-lock.json` alone | The two locks a module starts from hold no known advisory (high and critical, for npm) |
| `template-image` | `docker compose config` for the three compose combinations; `docker build` with the `kit` context and CI's build arguments, under the name and a release tag the compose file pulls; `docker compose -f docker-compose.yml up --wait`; `/health` and the revision label | The compose files are valid, the image builds from the workspace packages, it runs read-only and without capabilities until healthy, and it says its commit and the release the deployment names |
| `workflows` | actionlint, with shellcheck, on `.github/workflows/ci.yml` and the template's `ci.yml` and `release.yml` | The workflows a module ships are valid, though no run of the kit executes them |

The gate runs `a11y.spec.ts` for every state in `screens.ts` (`signin`, `flows`, `account-menu`, `version`, `flows-empty`, `flows-error`, `session-warning`, `signed-out`) in fifteen projects: in Chromium phone 320 light, phone 390 light and dark, laptop 1440 light and dark, 200 % zoom, forced colours, reduced motion, both tablets and a phone on its side; in WebKit a phone, a tablet and a laptop; in Firefox a laptop ([quality](quality.md#webkit-and-firefox)). It checks axe (every WCAG violation blocks), every control named (in Chromium), placeholder contrast, target sizes (24 px with a mouse, 44 px under `pointer: coarse`), reflow at every width, text spacing, and no endless motion with reduced motion. Every gate test also has the sentinel the flow tests have (a state that causes a failure on purpose declares it in `screens.ts`). `header-fit.spec.ts` checks that at 320 px with text spacing the brand and the account button keep apart. `keyboard.spec.ts`, in all of them but the phone on its side, tabs through each screen from the top: every stop shows focus (WCAG 2.4.7) and is not hidden under anything (2.4.11), focus leaves the page at the end (no trap, 2.1.2), and on a phone the order reads top to bottom (2.4.3); the account menu, the version dialog (back to the account button), the page's dialog, the warning and the sign-in dialog keep focus inside and give it back. `still.spec.ts`, on the two phones, the upright tablet and the laptop in light, opens `signin`, `flows`, `flows-empty`, `flows-error` and `session-warning` by their address and fails when something on screen moves as an answer arrives ([quality](quality.md#what-is-on-screen-stands-still)). `controls.spec.ts`, on phone 390 and laptop 1440 in light, both tablets and the four WebKit and Firefox projects, presses every control of every state in a fresh copy of it and fails one that does nothing, breaks something or leaves something open ([quality](quality.md#every-control-does-something)). `aria.spec.ts`, on phone 390 and laptop 1440 in light and in WebKit and on laptop 1440 in Firefox, holds each state to a snapshot of what a screen reader is given, curated by hand ([quality](quality.md#what-a-screen-reader-is-given)). `harness.spec.ts` tests the gate itself, once in each engine. Thresholds are never lowered. The gate's code is a copy of speech-to-text's: known debt, to become a package export when a second module needs it.
