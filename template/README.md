# Eneo module

The smallest working Eneo module: a sign-in page, one page behind the login that lists Eneo's flows, one route of its own.
It runs on `eneo-module-kit`: the kit's FastAPI backend does the login handoff, the session and a deny-by-default proxy,
and `@eneo-ai/module-kit` gives the theme, colour mode, shell and brand. One process, one container, port 3001, `/health`.

A module built from this template is AGPL-3.0-only, like Eneo (see `LICENSE`).

- **Run it.** From the module's folder, with the stub Eneo (development only; macOS, Linux and Windows alike):
  ```bash
  node stub-eneo/dev.mjs --check   # starts both, signs in as a browser would, stops
  node stub-eneo/dev.mjs           # keeps both running until Ctrl+C
  ```
  `--check` has started it when it ends with `OK: signed in through the stub Eneo, the page is served, and /api/example
  answered {"greeting":"Hej Erik Lund"}` and exit code 0. The second command serves the module on http://localhost:3001
  (the stub on http://localhost:8411): "Logga in med Eneo", then "Välj ett flöde" shows "Hej Erik Lund" and two flows.
  `--port 3002 --stub-port 8412` choose other ports. It uses the stub's values of `.env.example`, not `.env`, and needs
  `web/dist` and `.venv` with `eneo-module-bff` (or the python `PYTHON` names). If it says there is no Python or the UI is
  not built, the folder is not set up (a plain copy of the template or a fresh clone has no `.venv`, no `web/node_modules`
  and no tarball in `web/vendor/`). Set it up from a checkout of the kit, cloned outside this folder:
  ```bash
  git clone https://github.com/eneo-ai/eneo-module-kit.git
  cd eneo-module-kit && node scripts/new-module.mjs /path/to/this/module
  ```
  It packs the UI package into `web/vendor/`, runs `npm ci` and `npm run build` in `web/`, makes `.venv` and installs
  `backend/requirements.lock` with hashes and the checkout's BFF (Node 22.22.2 or newer, Python 3.12 or newer). The GitHub
  release `v0.1.0` does not fit this template (its UI package wants `@astryxdesign/core` 0.6.3, the template has 0.7.12, so
  `npm install` stops with `ERESOLVE`) and the packages are not on npm or PyPI: until a newer release exists, they come
  from a checkout of the kit. Steps by hand and errors: [when it does not work](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md#when-it-does-not-work).
- **Run it in a container.** As it ships, the template installs the packages of a checkout of the kit (its BFF pin is a
  placeholder, and its lock looks for the UI package in `web/vendor/`), so a plain `docker build` fails. From the root of
  the kit repository, build the image with the packages of that checkout, then start it with the stub Eneo:
  ```bash
  npm ci && npm run -w packages/ui build && mkdir kit-context
  npm pack -w packages/ui --pack-destination kit-context && cp -R packages/bff kit-context/bff
  docker build --build-context kit=kit-context -t eneo-module:local template
  cd template && cp .env.example .env && docker compose up      # then open http://localhost:3001
  ```
  A module that installs both packages from a kit GitHub release that fits the template (`v0.1.0` does not) instead ([where the packages come from](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md#where-the-packages-come-from))
  runs `cp .env.example .env && docker compose up --build` in its own folder. `docker compose up` merges
  `docker-compose.override.yml` (the local build, port 3001, the stub Eneo); production runs `docker-compose.yml` alone.
- **Start a module:** copy this folder, rename it, set `PRODUCT_NAME` in `web/src/config.ts`, `<title>` and `<noscript>` in `web/index.html`, the icons in `web/public/`, the drafts' prefix in `web/src/drafts.ts`, and
  the image's name in `docker-compose.yml` to `ghcr.io/<owner>/<repository>` of the module's repository (CI checks it).
- **Settings:** `.env.example` lists every variable. Register the module in Eneo's admin (module key, callback URL
  `MODULE_PUBLIC_URL/api/auth/callback`, service key).
- **Add a route:** in `backend/routes.py` on `router`, behind `require_session`; to call Eneo, one `rule(...)` in `backend/main.py`.
  There is no public backend route ([open question](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/decisions/README.md#open-questions)).
- **Add a page:** a route in `web/src/App.tsx` with its title, under `Private` (the kit's `RequireSession`) when it needs a session;
  a page outside `Private` is open, like the sign-in page. Its states in `web/tests/e2e/screens.ts`.
- **Test:** `python -m unittest discover -s backend/tests -t backend`; in `web/`: `npm test` (unit tests and the code's rules),
  `npm run test:e2e` (browsers, the accessibility gate and the production checks; builds first), or `npm run test:prod` for the
  production checks alone. If you set `PYTHON` for them, give an absolute path to a python that has `eneo-module-bff`.
- **Locks:** `web/package-lock.json` and `backend/requirements.lock` pin everything, and `npm ci` and the image use them. As the
  template ships, `npm ci` in `web/` needs the packed UI package in `web/vendor/` (see its README); a module that installs the
  tarball of a release that fits the template (`v0.1.0` does not) by its address does not ([where the packages come from](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md#where-the-packages-come-from)).
- **Release and deploy:** CI (`.github/workflows/ci.yml`) builds the image once and, on main, publishes it as `sha-<commit>` after
  every job passed; `git tag vX.Y.Z && git push origin vX.Y.Z` on a commit CI passed gives that image its version without
  rebuilding it (`release.yml`). `docker-compose.yml` runs it, chosen by `MODULE_VERSION`, read-only;
  `docker-compose.traefik.yml` adds Traefik with HTTPS on a host without a proxy. `/health` says which build runs.
  Dokploy and plain Docker Compose: [release and deploy](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/deploy.md).
- **Which version runs:** Version in the account menu shows the release, the commit and the build time of the image, with a button
  that copies them for a report of a fault (`VersionInfo` from the kit, read from `/api/healthz`).
- **Rules for people and agents:** `AGENTS.md`. The local [eneo-module skill](.agents/skills/eneo-module/SKILL.md)
  guides setup and feature work. `CLAUDE.md` imports both the rules and the skill.
- **Full guides:** [create a module](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md),
  [add backend routes](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/build-a-module.md), and
  [configuration](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/configuration.md) in the kit repository.
- **The stub Eneo** (`stub-eneo/server.py`, development and tests only) signs everyone in as Erik Lund and answers what the backend
  asks of Eneo. Control routes, all `POST`, for what a test needs to provoke: `/__stub/end-session` (Eneo refuses the tokens
  from now on: the module's session ends at its next token refresh); `/__stub/session?ends_in=S&token_seconds=T` (the logins made
  after it end S seconds after the login, with tokens of T seconds the backend refreshes at half: `token_seconds=4` makes
  `end-session` take seconds, `ends_in=200` opens the five-minute warning at once; `reset` restores 28800 and 900);
  `/__stub/login-as?user=erik|sara` (who the next logins are, to see a renewal that signs in someone else);
  `/__stub/flows?mode=normal|empty|error`. Each holds for the logins of the caller's `stub_scope` cookie, which every browser
  test has its own of (`web/tests/e2e/fixtures.ts`), so that tests running at once do not meet; a `curl` without it changes
  what everyone else without one gets. `web/tests/e2e/session-cover.spec.ts` uses them.
- **Sessions:** `RequireSession` (from `@eneo-ai/module-kit/session`) shows the sign-in screen, keeps the login, warns five
  minutes before its end and, when it has ended, covers the page with a dialog that asks for a new login in a window of its
  own (`/inloggad`, route in `App.tsx`). Call the backend with `fetchWithSession`; close a dialog of the page while
  `useSignedOut()` is true (`web/src/pages/Flows.tsx` shows both).
