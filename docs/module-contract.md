# The module contract in requests

Purpose: show, call by call, what the BFF sends to Eneo and what it expects back, with examples, and what it does with each failure.
Read this when: you build or change a stub Eneo, debug a login or a refresh, or check that Eneo's side matches the BFF.
Related: [design.md](design.md) section 2 (the contract as a table), [architecture](architecture.md#login-handoff), [local development](guides/local-development.md), `template/stub-eneo/server.py` (the examples below are its answers), Eneo's [module operator guide](https://github.com/eneo-ai/eneo/blob/develop/docs/deployment/MODULES.md).

Eneo's own side is in `eneo-ai/eneo`; this page is the BFF's side, in `packages/bff/src/eneo_module_bff/auth.py`. Where they differ, Eneo's is the contract and the BFF has a bug. Placeholders: `SERVICE_KEY` is `ENEO_API_KEY` in the header named by `ENEO_API_KEY_HEADER_NAME` (default `X-API-Key`), `MODULE_KEY` is the module's key, `TOKEN` is a module-user token.

## 1. Start login

The browser asks the module, the module redirects to Eneo's public address.

```http
GET {MODULE_PUBLIC_URL}/api/auth/login?next=/flows

303 See Other
Location: {ENEO_PUBLIC_URL}/module-login?module_key=MODULE_KEY&redirect_uri={MODULE_PUBLIC_URL}/api/auth/callback&state=STATE
Set-Cookie: eneo_module_login_state=...; HttpOnly; SameSite=Lax; Max-Age=300; Path=/api/auth/callback
```

`state` is 32 random bytes, URL-safe. `redirect_uri` is the callback registered in Eneo with the module key.

## 2. Eneo returns the browser with a ticket

Eneo signs the user in, then redirects the browser to the callback (the stub answers 303):

```http
303 See Other
Location: {MODULE_PUBLIC_URL}/api/auth/callback?ticket=TICKET&state=STATE
```

`state` must be the one the module sent. The ticket works once.

## 3. Exchange the ticket

Server to server, with the service key only.

```http
POST {ENEO_BACKEND_URL}/api/v1/module-auth/token/
SERVICE_KEY_HEADER: SERVICE_KEY
Content-Type: application/json

{"ticket": "TICKET"}
```

```json
200 OK
{
  "access_token": "vPgwPdlU4VKJDvppM8ZCUky7Rl5JfXCL",
  "token_type": "bearer",
  "expires_in": 900,
  "session_expires_at": "2026-10-02T02:55:00.359916+00:00",
  "module_key": "eneo-module",
  "tenant_id": "tenant-1",
  "user": {"id": "user-1", "email": "erik.lund@example.test", "username": "Erik Lund"}
}
```

The BFF requires `token_type` `bearer`, `module_key` equal to its own, `expires_in` above zero, and a `session_expires_at` in the future (without a time zone it is read as UTC). `username` is optional. A used ticket is a 400 from the stub.

## 4. Confirm the session

Both credentials, so Eneo checks the token it just issued.

```http
GET {ENEO_BACKEND_URL}/api/v1/module-auth/MODULE_KEY/session/
SERVICE_KEY_HEADER: SERVICE_KEY
Authorization: Bearer TOKEN
```

```json
200 OK
{"module_key": "eneo-module", "tenant_id": "tenant-1", "user": {"id": "user-1", "email": "erik.lund@example.test", "username": "Erik Lund"}}
```

`module_key`, `tenant_id` and `user.id` must equal those of the exchange.

## 5. Refresh

At half the token's lifetime, with both credentials, one refresh in flight per session.

```http
POST {ENEO_BACKEND_URL}/api/v1/module-auth/MODULE_KEY/token/refresh/
SERVICE_KEY_HEADER: SERVICE_KEY
Authorization: Bearer TOKEN
```

The answer has the shape of step 3. The BFF accepts it only for the same `module_key`, `tenant_id` and `user.id`, with `expires_in` above zero; the new token's expiry is capped at the session's end.

## 6. Resource calls

Every call to Eneo for a signed-in user carries both credentials:

```http
GET {ENEO_BACKEND_URL}/api/v1/flows/
SERVICE_KEY_HEADER: SERVICE_KEY
Authorization: Bearer TOKEN
```

```json
200 OK
{"has_more": false, "count": 2, "items": [{"id": "flow-1", "name": "Nämndmöte till rapport", "description": "...", "published_version": 3, "is_published": true, "space_id": "space-1", "space_name": "Kommunledningskontoret"}]}
```

A call without both is a 401 from Eneo (and from the stub).

## What the BFF does with each answer

| Step | Eneo's answer | The BFF |
|---|---|---|
| Callback | `ticket` or `state` missing, `state` different from the cookie's, or the cookie missing, expired or forged | 303 to `/?auth_error=invalid_state`; no call to Eneo |
| 3 | No answer | `exchange_unavailable` |
| 3 | Not 200 | `exchange_failed` |
| 3 | Not JSON of the shape above, wrong `module_key`, no time left | `exchange_invalid` |
| 4 | No answer | `validation_unavailable` |
| 4 | Not 200 | `validation_failed` |
| 4 | Not the shape above, or another identity than step 3 | `validation_invalid` |
| 5 | 408, 429, 5xx, no answer, or an unexpected error in the module | The session keeps its still valid token and asks again in 10 s |
| 5 | Any other non-200, a body that is not the shape above, another identity, or `expires_in` not above zero | The session ends; the next request is a 401 |
| 6 | Any status | Passed through with its body, except a redirect (301, 302, 303, 307, 308), which is a 502 `upstream_redirect` |

An `auth_error` code reaches the browser as the query of `/?auth_error=<code>`. The state cookie is deleted by every callback answer, and those answers carry `Cache-Control: no-store` and `Referrer-Policy: no-referrer`.

## A renewal

`GET /api/auth/login?renew=true` (the page opens it in another window before the login ends) binds the login to the user signed in now. With no live session it answers 303 to `next` with `fel=utgangen` and does not start a login. If another user signs in, the callback keeps the old session and redirects to `next` with `fel=annan-anvandare`.
