# K19. A session ends when Eneo confirms that the login is over

Purpose: record when a refusal from Eneo ends a module's session, and why a refusal alone does not.
Read this when: you change how the BFF reads Eneo's refusals, `ModuleAuth.login_refused`, `raise_if_session_ended`, or what the browser gets when a login ends.
Related: [decisions](README.md), [BFF package: when Eneo ends the login](../../packages/bff/README.md#when-eneo-ends-the-login), [security checklist](../guides/security-checklist.md#what-the-kit-enforces), [K15](k15-cover-for-an-ended-login.md), [module contract](../module-contract.md).

Status: Accepted, 2026-11-18. Built: `packages/bff/src/eneo_module_bff/auth.py` (`refuses_the_login`, `ModuleAuth.login_refused`, `ModuleSessionStore.delete_if_token`), `deps.py` (`raise_if_session_ended`).

## Context

Eneo can end a login before the module's session ends: a changed password, "log out everywhere", a user who is gone. Left to the token refresh, the session would stay until the next refresh, and the page would show Eneo's refusal as an error instead of asking for a new login.

Eneo refuses such a token with 401 and the code `authentication_error`. So does a route of Eneo's that takes no module tokens, for a valid one. The code alone is not proof that the login is over, and ending a session on it would sign people out because a module called the wrong route.

## Decision

A refusal that may end the login (401, `authentication_error` at the top of the JSON body) starts one check: the BFF asks Eneo's session route with the same token, bounded in time (10 seconds, the answer included) and in size. Only when that route refuses the token too does the session end, and only if it still holds the refused token or a renewed one past its end: the session and its signed URLs are deleted in one step, and the browser gets the 401 of an ended session (`X-Auth-Required: session`). Anything else confirms nothing: the session stays and Eneo's answer goes on unchanged. A session that is gone already gets the ended-session answer without a check, and so does a call whose own check confirmed nothing while another refusal of the same token ended the session.

The rule lives in `ModuleAuth`, and every call made with the user's token uses it: the proxy, `forward_upload`, the minting in `stream_signed`, and a module's own calls through `raise_if_session_ended`. Fetching a file with its signed URL does not: a refused signed URL says nothing about the login.

The alternatives are ending the session on the code alone (it signs people out for a module's mistake) and waiting for the next refresh (the page shows Eneo's refusal for up to half a token's lifetime). No new trust is added: the session ends only on Eneo's own word, and the check uses the route the login already uses.

## Consequences

- A refused call costs at most one more small call to Eneo. Two refusals at once each ask once; the session ends once.
- A token refreshed before or during the check keeps its session while that session is live: the refusal is about the old token. A renewed session past its end is ended.
- A module that calls Eneo itself must pass the answer to `raise_if_session_ended`, read (not `stream=True`); a streamed answer is a `RuntimeError`, so the mistake shows at the first call.
- Proof: `packages/bff/tests/test_login_end.py`.
