# eneo-module-kit

The starter for Eneo modules: small web apps that run beside an Eneo installation on their own domain and use
Eneo as their AI engine.

A module needs the same things every time: the login handoff from Eneo, a server-side session, a proxy that sends
the right credentials, a themed and accessible UI shell, and a container image. This repository holds those parts
once, so a new module imports them instead of copying them.

> **Status: not built yet.** This README describes the intended shape. The first module,
> [eneo-mod-speech-to-text](https://github.com/eneo-ai/eneo-mod-speech-to-text), is the source the kit is extracted
> from. Treat every API as provisional (0.x) until that module runs on the kit.

## What it will contain

```
packages/ui/     @eneo-ai/module-kit    React + Astryx: theme, providers, page shell, session screens
packages/bff/    eneo-module-bff        FastAPI: module login, session, proxy to Eneo
template/        the smallest working module, built against both packages on every commit
docs/            the module contract with Eneo, and design decisions
```

A new module starts as a copy of `template/` and imports the two packages. It does not copy package code, so a fix
to login or to the UI arrives as a version bump.

## The module contract, in short

Eneo stays the installation's only login. A module:

1. Sends the browser to Eneo's `/module-login` with its `module_key`, its registered callback and a one-time `state`.
2. Receives a one-time ticket on its callback and exchanges it server-side, with its own service key, for a
   short-lived module-user token.
3. Keeps that token in a server-side session. The browser only holds an opaque, HttpOnly session cookie.
4. Sends **both** the service key and the module-user token on every call to Eneo, and refreshes the token until
   Eneo's session ceiling.
5. Listens on port 3001 and answers `/health`.

The full contract is in Eneo's
[module operator guide](https://github.com/eneo-ai/eneo/blob/develop/docs/deployment/MODULES.md) and its
"Module Authentication" reference.

## What each part owns

**`packages/bff`** — the contract above, ready to use:

- Configuration with start-up validation.
- Login, callback, ticket exchange, session store, single-flight token refresh, logout, session status.
- A same-origin check for writes and WebSocket handshakes.
- Transport primitives: a deny-by-default proxy that adds both credentials, upload forwarding, file streaming with
  Range support.
- Health, branding, security headers, and serving the built UI.

**`packages/ui`**:

- The Eneo theme for [Astryx](https://astryx.atmeta.com), built to static CSS, and the providers a page needs
  (theme, Swedish strings).
- A presentational page shell and brand lockup.
- The session screens: sign-in, the warning before the login ends, the cover while signed out.
- Generic loading, problem and offline states.

**`template/`** — a Vite + React app served as static files by the BFF, in one process and one container: a
`main.py` that declares the module's own allowed Eneo routes, a sign-in page and one example page, Dockerfile,
compose file, CI, devcontainer, agent instructions, an accessibility gate, and a stub Eneo for development.

## What stays in each module

- **Its route allowlist.** The proxy denies by default; a module names the Eneo routes it exposes.
- Its domain features and protocols (for speech-to-text: recording, live transcription, transcript editing).
- Its own copy, recovery messages and draft handling.

## Choices already made

| Choice | Why |
|---|---|
| One stack, not a framework-agnostic kit: Vite + React + Astryx, served by FastAPI | One process and one runtime in the image, and no proxy hop in front of uploads and WebSockets. The UI package imports nothing from a router or a meta-framework, and the BFF's HTTP surface is documented, so either half can be replaced later. |
| FastAPI for the BFF | The login and proxy code exists, is tested, and matches Eneo's own stack. |
| Astryx for the UI | Components, layout and accessibility are imported, not copied and maintained. The house bar above the defaults (44 px touch targets, a measured focus ring) is met once, in the theme. |
| Packages are imported, the template is copied | Shared code is fixed in one place; only the thin per-module glue is owned by the module. |

## Build order

| Part | Can start |
|---|---|
| BFF package, extracted from speech-to-text's backend with its tests | Now |
| Template skeleton and contract docs | Now |
| UI package: theme and providers | When speech-to-text's Astryx foundation is on its `main` |
| UI package: shell and session screens | When speech-to-text's first ported phase is merged |
| Speech-to-text running on the kit | After its Astryx port, on a released kit version |

The design record behind these choices is in the speech-to-text repository under `docs/plans/`.
