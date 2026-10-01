# Local development against a stub Eneo

Purpose: run a module on your machine and sign in without an Eneo installation.
Read this when: you are developing a module's backend, or reproducing a login, refresh or proxy problem.
Related: [new module](new-module.md), [build a module](build-a-module.md), [configuration](configuration.md), [architecture: login handoff](../architecture.md#login-handoff).

The template ships a stub Eneo: `template/stub-eneo/server.py` (`stub-eneo/server.py` in a module made from it). It is stdlib Python and implements Eneo's side of the [module contract](../design.md): the login redirect, the ticket exchange, the session check, the refresh and one resource, `GET /api/v1/flows/`. A module that is not made from the template copies that one file. Every call after the exchange must carry both credentials, or the stub answers 401, as Eneo does.

It is a development aid, not a model of Eneo: it signs in one fixed user (Erik Lund), accepts a ticket it issued once, and its tokens last 15 minutes (`TOKEN_SECONDS` in the file) within an eight-hour login. It never ships in the image.

## The stub

```bash
python3 stub-eneo/server.py [port]          # default 8411
```

| Variable | Default | Meaning |
|---|---|---|
| `STUB_PORT` | `8411` | The port, when none is given as an argument |
| `STUB_HOST` | `127.0.0.1` | The address it listens on. `0.0.0.0` for a container to reach it |
| `STUB_MODULE_KEY` | `eneo-module` | The module key it accepts: the module's `MODULE_KEY` |
| `STUB_ENEO_API_KEY` | `stub-service-key` | The service key it accepts: the module's `ENEO_API_KEY` |

What it answers (the same list is the docstring of the file):

| Call | Answer |
|---|---|
| `GET /module-login?module_key&redirect_uri&state` | 303 back to `redirect_uri` with a one-time ticket (valid 60 s) and the unchanged `state`. 400 for a wrong module key or a missing parameter |
| `POST /api/v1/module-auth/token/` | The ticket, once, for a module-user token. Needs the service key |
| `GET /api/v1/module-auth/{module_key}/session/` | Who the token is. Needs both credentials |
| `POST /api/v1/module-auth/{module_key}/token/refresh/` | A new token. Needs both credentials |
| `GET /api/v1/flows/` | Two published flows. Needs both credentials |
| `GET /health` | `{"ok": true}` |

For tests, two unauthenticated control routes:

| Call | Effect |
|---|---|
| `POST /__stub/end-session` | Every token is refused from now on, as when Eneo ends the login: the module's session ends at its next token refresh |
| `POST /__stub/session?ends_in=S&token_seconds=T` | For the logins made after this call: the session ends S seconds after the login (Eneo's ceiling; a refresh keeps it) and a token lives T seconds (the module refreshes at half). Defaults 28800 and 900; `reset` as a value restores them |
| `POST /__stub/login-as?user=erik\|sara` | Who the logins made after this call are (default Erik Lund), to show a renewal that signs in someone else |
| `POST /__stub/flows?mode=normal\|empty\|error` | What the flow list answers: two flows, none, or a 500 |

## Run the module against it

Any module. The values below are `template/.env.example`'s, with the stub on the host; use your own ports if 3001 or 8411 are taken. From the module's folder (a virtual environment with `eneo-module-bff` installed, and the built UI in `web/dist`: see [new module](new-module.md)):

```bash
# terminal 1: the stub on 8411
python3 stub-eneo/server.py

# terminal 2: the module on 3001, from backend/
cd backend
export ENEO_BACKEND_URL=http://127.0.0.1:8411
export ENEO_PUBLIC_URL=http://localhost:8411
export MODULE_PUBLIC_URL=http://localhost:3001
export MODULE_KEY=eneo-module
export ENEO_API_KEY=stub-service-key
export SESSION_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")   # at least 32 characters
export COOKIE_SECURE=false                       # the module is on http here
python -c "from eneo_module_bff import serve; serve('main:build_app', factory=True)"
```

`ENEO_PUBLIC_URL` is where the browser is sent for login and `ENEO_BACKEND_URL` is where the module calls: here the same stub, by two names. A module of your own that builds its app as `app = create_app(...)` runs with `serve('main:app')`; see [build a module](build-a-module.md).

## Sign in and call a route

In a browser, open `http://localhost:3001`. Or walk it by hand, which shows each step of the [handoff](../architecture.md#login-handoff):

```bash
M=http://localhost:3001
rm -f jar
# 1. the module redirects to Eneo and sets the state cookie
LOGIN=$(curl -s -i -c jar "$M/api/auth/login?next=/flows" | grep -i '^location' | tr -d '\r' | cut -d' ' -f2)
# 2. the stub sends the browser back with a ticket
CALLBACK=$(curl -s -i "$LOGIN" | grep -i '^location' | tr -d '\r' | cut -d' ' -f2)
# 3. the callback exchanges the ticket and sets the session cookie
curl -s -i -b jar -c jar "$CALLBACK" | grep -iE '^HTTP|^location|^set-cookie'
# 4. use the session
curl -s -b jar "$M/api/auth/status"       # authenticated, user, session_ends_in, refresh_in
curl -s -b jar "$M/api/example"           # {"greeting":"Hej Erik Lund"}, the template's own route
curl -s -b jar "$M/api/eneo/flows/"       # the proxy: the stub's two flows
curl -s -b jar -w ' %{http_code}\n' "$M/api/eneo/users/"   # 403: no rule names it
curl -s -i "$M/api/example" | grep -iE '^HTTP|^x-auth'     # 401 and X-Auth-Required: session
# 5. a write needs the module's own Origin
curl -s -b jar -X POST -w ' %{http_code}\n' "$M/api/auth/logout"                              # 403
curl -s -b jar -c jar -X POST -H "Origin: $M" -w ' %{http_code}\n' "$M/api/auth/logout"      # 200
```

`/api/example` and the one proxy rule are the template's (`backend/routes.py`, `backend/main.py`).

## Things to try

| To see | Do |
|---|---|
| A refresh | Lower `TOKEN_SECONDS` in the stub (for example to 20): the token is refreshed at half its life, on the next request or `GET /api/auth/status` after it. |
| The session ending | Set `SESSION_MAX_AGE_MINUTES=1` on the module: a minute later the next request is a 401. |
| Eneo ending the login | `curl -X POST localhost:8411/__stub/end-session`: a call to Eneo (`/api/eneo/flows/`) now answers 401, and the module's next refresh is refused and ends the session. With `__stub/session?token_seconds=4` set before the login, that takes seconds, and the page is covered by the sign-in dialog. |
| The warning before the end | `curl -X POST "localhost:8411/__stub/session?ends_in=200"`, then sign in: the page warns at once (five minutes before the end). `?ends_in=reset&token_seconds=reset` restores the defaults. |
| Someone else signing in | `curl -X POST "localhost:8411/__stub/login-as?user=sara"` before the new login: after an end the page stays covered and says whom to sign in as; before the warning's renewal, the renewal is refused (`fel=annan-anvandare`) and the old login is kept. |
| An empty list, a failing Eneo | `curl -X POST "localhost:8411/__stub/flows?mode=empty"` or `mode=error`, then reload the flows page; `mode=normal` restores it. |
| Eneo not answering a refresh | Make `refresh` in the stub answer 503: the session keeps its token and asks again in 10 s. With 401 it ends. |
| A failed login | Do steps 1 and 2 above, stop the stub, then do step 3: the callback redirects to `/?auth_error=exchange_unavailable`. |
| A forged callback | `curl -i -b jar "$M/api/auth/callback?ticket=t&state=wrong"` after step 1: it redirects to `/?auth_error=invalid_state`. |

## Limits of this setup

- Over http: `COOKIE_SECURE=false` is for this only. In production it stays `true`.
- The stub does not check the redirect URI, and it signs in anyone: Eneo does the real login. The module checks `state` itself.
- For the UI with hot reload, see [new module](new-module.md#4-run-it-against-the-stub).
