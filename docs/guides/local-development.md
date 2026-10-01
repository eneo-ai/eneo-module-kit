# Local development against a stub Eneo

Purpose: run a module on your machine and sign in without an Eneo installation.
Read this when: you are developing a module's backend, or reproducing a login, refresh or proxy problem.
Related: [build a module](build-a-module.md), [configuration](configuration.md), [architecture: login handoff](../architecture.md#login-handoff).

The planned template will ship a stub Eneo (`template/stub-eneo/server.py`) and a compose file. Until it exists, use the stub below: about 60 lines, FastAPI only, no state worth keeping. It implements Eneo's side of the [module contract](../design.md): the login redirect, the ticket exchange, the session check, the refresh, and one resource, `GET /api/v1/flows/`. Every call after the exchange must carry both credentials, or the stub answers 401, as Eneo does.

It is a development aid, not a model of Eneo: it signs in one fixed user, issues any ticket, and never expires a token.

## 1. The stub

Save as `stub_eneo.py`, next to your `main.py`:

```python
"""A stand-in for Eneo's side of the module contract, for local development. Not for production."""

import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse

MODULE_KEY = "my-module"
SERVICE_KEY = "dev-service-key"  # the module's ENEO_API_KEY
USER = {"id": "user-1", "email": "anna@example.test", "username": "anna"}

app = FastAPI()
tokens: set[str] = set()


def token_response() -> dict:
    token = secrets.token_urlsafe(24)
    tokens.add(token)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 600,
        "session_expires_at": (datetime.now(timezone.utc) + timedelta(hours=8)).isoformat(),
        "module_key": MODULE_KEY,
        "tenant_id": "tenant-1",
        "user": USER,
    }


def require_both(x_api_key: str | None, authorization: str | None) -> None:
    """Every call after the ticket exchange carries the service key and the module-user token."""
    if x_api_key != SERVICE_KEY or authorization is None or authorization.removeprefix("Bearer ") not in tokens:
        raise HTTPException(status_code=401, detail="both credentials are required")


@app.get("/module-login")
def module_login(module_key: str, redirect_uri: str, state: str) -> RedirectResponse:
    # A real Eneo signs the user in first. Here everyone is Anna.
    return RedirectResponse(f"{redirect_uri}?{urlencode({'ticket': secrets.token_urlsafe(16), 'state': state})}", status_code=302)


@app.post("/api/v1/module-auth/token/")
def exchange(x_api_key: str | None = Header(default=None)) -> dict:
    if x_api_key != SERVICE_KEY:
        raise HTTPException(status_code=401, detail="service key required")
    return token_response()


@app.get(f"/api/v1/module-auth/{MODULE_KEY}/session/")
def session(x_api_key: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict:
    require_both(x_api_key, authorization)
    return {"module_key": MODULE_KEY, "tenant_id": "tenant-1", "user": USER}


@app.post(f"/api/v1/module-auth/{MODULE_KEY}/token/refresh/")
def refresh(x_api_key: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> dict:
    require_both(x_api_key, authorization)
    return token_response()


@app.get("/api/v1/flows/")
def flows(x_api_key: str | None = Header(default=None), authorization: str | None = Header(default=None)) -> list[dict]:
    require_both(x_api_key, authorization)
    return [{"id": "f1", "name": "Summarise"}, {"id": "f2", "name": "Translate"}]
```

The header `X-API-Key` is the default name of `ENEO_API_KEY_HEADER_NAME`. Change both if you change one.

## 2. Run the stub and the module

Two terminals, from the directory that holds `main.py` and `stub_eneo.py` (a virtual environment with the package installed, as in [build a module](build-a-module.md#1-install-the-package)). Use your own ports if 3001 or 8001 are taken.

```bash
# terminal 1: the stub on 8001
python -m uvicorn stub_eneo:app --port 8001
```

```bash
# terminal 2: the module on 3001
export ENEO_BACKEND_URL=http://localhost:8001
export ENEO_PUBLIC_URL=http://localhost:8001
export MODULE_PUBLIC_URL=http://localhost:3001
export MODULE_KEY=my-module
export ENEO_API_KEY=dev-service-key
export SESSION_SECRET=$(python3 -c "print('x' * 40)")   # at least 32 characters; any value in development
export COOKIE_SECURE=false                              # the module is on http here
python -c "from eneo_module_bff import serve; serve('main:app')"
```

`MODULE_KEY` and `ENEO_API_KEY` must equal `MODULE_KEY` and `SERVICE_KEY` in the stub. `ENEO_PUBLIC_URL` is where the browser is sent for login and `ENEO_BACKEND_URL` is where the module calls: in development they are the same address.

## 3. Sign in and call a route

In a browser, open `http://localhost:3001/api/auth/login?next=/api/auth/status`: you are sent to the stub, back to the callback, and land on the status JSON with your session cookie set. Or walk it by hand, which shows each step of the [handoff](../architecture.md#login-handoff):

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
curl -s -b jar "$M/api/ping"              # {"ok":true}, from your own route
curl -s -b jar "$M/api/eneo/flows/"       # the proxy: the stub's two flows
curl -s -b jar -w ' %{http_code}\n' "$M/api/eneo/users/"   # 403: no rule names it
curl -s -i "$M/api/ping" | grep -iE '^HTTP|^x-auth'        # 401 and X-Auth-Required: session
# 5. a write needs the module's own Origin
curl -s -b jar -X POST -w ' %{http_code}\n' "$M/api/auth/logout"                              # 403
curl -s -b jar -c jar -X POST -H "Origin: $M" -w ' %{http_code}\n' "$M/api/auth/logout"      # 200
```

`/api/ping` and the two proxy rules are the ones in the example `main.py` of [build a module](build-a-module.md#2-write-mainpy). The proxy call needs the stub's `GET /api/v1/flows/`, and the rule `rule("GET", r"flows/$")`.

## 4. Things to try

| To see | Do |
|---|---|
| A refresh | Lower `expires_in` in the stub's `token_response` (for example to 20): the token is refreshed at half its life, on the next request or `GET /api/auth/status` after it. |
| The session ending | Lower `session_expires_at` in the stub, or set `SESSION_MAX_AGE_MINUTES=1` on the module: a minute later the next request is a 401. |
| Eneo refusing a refresh | Make `refresh` in the stub raise `HTTPException(status_code=401)`: the session ends. With `status_code=503`: the session keeps its token and asks again in 10 s. |
| A failed login | Do steps 1 and 2 of section 3, stop the stub, then do step 3: the callback redirects to `/?auth_error=exchange_unavailable`. |

## Limits of this setup

- Over http: `COOKIE_SECURE=false` is for this only. In production it stays `true`.
- The module's UI is not served here. With a built UI, pass `static_dir` to `create_app`; the planned template adds a Vite dev server that proxies `/api` to the module.
- The stub does not check `state`, the redirect URI or the module key on `/module-login`: Eneo does, and the module checks `state` itself (try a callback with a wrong `state`: it redirects to `/?auth_error=invalid_state`).
