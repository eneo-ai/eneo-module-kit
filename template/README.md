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
- **Rules for people and agents:** `AGENTS.md`.
