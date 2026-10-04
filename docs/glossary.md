# Glossary

Purpose: fix the meaning of the terms the kit's docs and code use, so one word names one thing.
Read this when: a term in the docs, the code or an Eneo document is unclear, or you are about to coin a new one.
Related: [architecture](architecture.md), [design (module contract)](design.md), [configuration](guides/configuration.md).

| Term | Meaning |
|---|---|
| Eneo | The AI platform a module runs beside. It is the installation's only login and the module's AI engine. |
| Module | A small web app on its own domain that uses Eneo. It has a backend (the BFF, built on this kit) and a UI. Registered in Eneo with a module key, a callback URL and a service key. |
| Kit | This repository: the BFF package, the planned UI package and the planned template. |
| Template | The smallest working module (planned, `template/`). A new module starts as a copy of it. Packages are imported; the template is copied. |
| BFF | Backend for frontend: the module's server side. It holds the session and the credentials, and the browser talks only to it. Package `eneo-module-bff`. |
| Module key | The module's name in Eneo (`MODULE_KEY`): lowercase kebab-case, as registered in Eneo. |
| Service key | The module's own API key for Eneo (`ENEO_API_KEY`). It is sent in a header whose name is `ENEO_API_KEY_HEADER_NAME` (default `X-API-Key`). It never reaches the browser. |
| Module-user token | A short-lived token Eneo issues for one signed-in user of one module. Sent as `Authorization: Bearer ...`, together with the service key, on every call to Eneo. Never reaches the browser. |
| Ticket | The one-time code Eneo puts on the module's callback URL after login. The module exchanges it server-side for a module-user token. |
| State | An unpredictable value that binds one login to one browser. It travels in the redirect and in a signed cookie, and the callback requires both to match. |
| Handoff | The login flow between Eneo and the module: login, Eneo's login page, callback, ticket exchange, session. See [architecture](architecture.md#login-handoff). |
| Session | The module's server-side record of one login: token, user, tenant, expiry. Held in memory. The browser holds only its opaque id in the cookie `eneo_module_session`. |
| Session end | The fixed end of a login: the earlier of `SESSION_MAX_AGE_MINUTES` and Eneo's own session ceiling. |
| Refresh | Renewing the module-user token through Eneo, at half its lifetime, one refresh in flight per session. |
| Same-origin check | A write (and a WebSocket handshake) must carry an `Origin` equal to the module's own (`MODULE_PUBLIC_URL`), else 403. |
| Proxy | The route `/api/eneo/{path}` that forwards the browser's requests to Eneo with both credentials. Denies everything until the module names a route. |
| Rule (allowlist) | One allowed route of the proxy: methods and a pattern matched against the path after `/api/eneo/`. Made with `rule(...)`. |
| Deny by default | Nothing is exposed until named: not a path, not a request header. |
| Upload forwarding | `forward_upload`: re-posts one file from the browser to Eneo, after the route's guards have run. |
| Mint path | The Eneo route (called with POST) that returns a signed URL for a file. Passed to `stream_signed`. |
| Signed URL | A short-lived URL from Eneo that is itself the credential for one file. Kept with the session, never given to the browser. |
| Stream slot | One of `MAX_CONCURRENT_STREAMS` places for files streaming at once. |
| Module network | The network the module container shares with Eneo's backend. |
| Beads | The issue tracker (`br`, `.beads/`) that holds the work order of this repository while the kit is built. Not part of the kit. |

The BFF's answers are English, except two query values it puts on a redirect and the UI package reads: `fel=utgangen` (the session ended) and `fel=annan-anvandare` (another user signed in on a renewal). The template's user-facing text (planned) is Swedish.
