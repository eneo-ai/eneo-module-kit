# Eneo module

The smallest working Eneo module: a sign-in page, one page behind the login that lists Eneo's flows, one route of its own.
It runs on `eneo-module-kit`: the kit's FastAPI backend does the login handoff, the session and a deny-by-default proxy,
and `@eneo-ai/module-kit` gives the theme, colour mode, shell and brand. One process, one container, port 3001, `/health`.

- **Try it:** `cp .env.example .env && docker compose up --build`, open http://localhost:3001. A stub Eneo stands in for Eneo.
- **Start a module:** copy this folder, rename it, set `PRODUCT_NAME` in `web/src/config.ts` and `<title>` in `web/index.html`.
- **Settings:** `.env.example` lists every variable. Register the module in Eneo's admin (module key, callback URL
  `MODULE_PUBLIC_URL/api/auth/callback`, service key).
- **Add a route:** in `backend/routes.py` on `router`, behind `require_session`; to call Eneo, one `rule(...)` in `backend/main.py`.
- **Add a page:** a route in `web/src/App.tsx` inside `RequireSession`; its states in `web/tests/e2e/screens.ts`.
- **Develop:** run `python3 stub-eneo/server.py`, the backend (`cd backend && python -c "from eneo_module_bff import serve; serve('main:build_app', factory=True)"` with `.env`'s variables, and `MODULE_PUBLIC_URL=http://localhost:5173`), and `cd web && npm run dev`.
- **Test:** `python -m unittest discover -s backend/tests -t backend`; in `web/`: `npm run test:e2e` (browsers, the accessibility gate).
- **Rules for people and agents:** `AGENTS.md`.
