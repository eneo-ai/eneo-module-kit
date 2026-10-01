# Eneo module

The smallest working Eneo module: a sign-in page, one page behind the login that lists Eneo's flows, one route of its own.
It runs on `eneo-module-kit`: the kit's FastAPI backend does the login handoff, the session and a deny-by-default proxy,
and `@eneo-ai/module-kit` gives the theme, colour mode, shell and brand. One process, one container, port 3001, `/health`.

- **Try it before the first release** (the packages are not published yet, so a plain `docker build` fails). From the root of
  the kit repository, build the image with the packages of that checkout, then start it with the stub Eneo:
  ```bash
  npm ci && npm run -w packages/ui build && mkdir kit-context
  npm pack -w packages/ui --pack-destination kit-context && cp -R packages/bff kit-context/bff
  docker build --build-context kit=kit-context -t eneo-module template
  cd template && cp .env.example .env && docker compose up      # then open http://localhost:3001
  ```
  After the release, in a module's own folder: `cp .env.example .env && docker compose up --build`.
- **Start a module:** copy this folder, rename it, set `PRODUCT_NAME` in `web/src/config.ts` and `<title>` in `web/index.html`.
- **Settings:** `.env.example` lists every variable. Register the module in Eneo's admin (module key, callback URL
  `MODULE_PUBLIC_URL/api/auth/callback`, service key).
- **Add a route:** in `backend/routes.py` on `router`, behind `require_session`; to call Eneo, one `rule(...)` in `backend/main.py`.
- **Add a page:** a route in `web/src/App.tsx` inside `RequireSession`; its states in `web/tests/e2e/screens.ts`.
- **Test:** `python -m unittest discover -s backend/tests -t backend`; in `web/`: `npm run test:e2e` (browsers and the accessibility
  gate; builds first). If you set `PYTHON` for it, give an absolute path to a python that has `eneo-module-bff`.
- **Locks:** `web/package-lock.json` and `backend/requirements.lock` pin everything, and `npm ci` and the image use them. Before the
  release `npm ci` in `web/` needs the packed UI package in `web/vendor/` (see its README).
- **Rules for people and agents:** `AGENTS.md`.
- **The stub Eneo** (`stub-eneo/server.py`, development and tests only) signs everyone in as Erik Lund and answers what the backend
  asks of Eneo. Control routes, all `POST`, for what a test needs to provoke: `/__stub/end-session` (Eneo refuses every token
  from now on: the module's session ends at its next token refresh); `/__stub/session?ends_in=S&token_seconds=T` (the logins made
  after it end S seconds after the login, with tokens of T seconds the backend refreshes at half: `token_seconds=4` makes
  `end-session` take seconds, `ends_in=200` opens the five-minute warning at once; `reset` restores 28800 and 900);
  `/__stub/login-as?user=erik|sara` (who the next logins are, to see a renewal that signs in someone else);
  `/__stub/flows?mode=normal|empty|error`. `web/tests/e2e/session-cover.spec.ts` uses them.
- **Sessions:** `RequireSession` (from `@eneo-ai/module-kit/session`) shows the sign-in screen, keeps the login, warns five
  minutes before its end and, when it has ended, covers the page with a dialog that asks for a new login in a window of its
  own (`/inloggad`, route in `App.tsx`). Call the backend with `fetchWithSession`; close a dialog of the page while
  `useSignedOut()` is true (`web/src/pages/Flows.tsx` shows both).
