# eneo-module-kit

Purpose: the starter for Eneo modules, small web apps that run beside an Eneo installation on their own domain and use Eneo as their AI engine.
Read this when: you start a module, work on a part of the kit, or want to know what is built and what is planned.
Related: [docs index](docs/README.md), [architecture](docs/architecture.md), [build a module](docs/guides/build-a-module.md), [decisions](docs/decisions/README.md), [AGENTS.md](AGENTS.md).

A module needs the same things every time: the login handoff from Eneo, a server-side session, a proxy that sends the right credentials, a themed and accessible UI shell, and a container image. This repository holds those parts once, so a new module imports them instead of copying them.

The first module, [eneo-mod-speech-to-text](https://github.com/eneo-ai/eneo-mod-speech-to-text), is the source the kit is extracted from. Treat every API as provisional (0.x) until that module runs on the kit and a second module has used it.

## Status

| Part | Path | What it is | Status |
|---|---|---|---|
| BFF package | `packages/bff/` | `eneo-module-bff`: FastAPI, the module contract with Eneo | **Built and tested.** Version 0.1.0, not released. |
| UI package | `packages/ui/` | `@eneo-ai/module-kit`: React and Astryx, theme, providers, page shell, session screens | Planned. Not in the repository yet. |
| Template | `template/` | The smallest working module, built against both packages on every commit | Planned. Not in the repository yet. |
| Docs | `docs/` | Architecture, guides, decisions, the module contract | Current. |

What is built versus planned is marked on every page. The decisions behind both are in [docs/decisions/](docs/decisions/README.md).

## Quick start: the BFF

From the repository root (Python 3.12):

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e "packages/bff[test]"
.venv/bin/python -m unittest discover -s packages/bff/tests -t packages/bff
```

A module's `main.py` is a few lines:

```python
from eneo_module_bff import create_app, rule

app = create_app(title="My module", proxy_rules=[rule("GET", r"flows/$")])
```

```bash
python -c "from eneo_module_bff import serve; serve('main:app')"
```

It needs the environment of [configuration](docs/guides/configuration.md) and an Eneo to sign in against. To try it without one, follow [local development](docs/guides/local-development.md), which has a stub Eneo and a walk through the login. [Build a module](docs/guides/build-a-module.md) covers guards, proxy rules, uploads and signed files.

## The module contract, in short

Eneo stays the installation's only login. A module:

1. Sends the browser to Eneo's `/module-login` with its `module_key`, its registered callback and a one-time `state`.
2. Receives a one-time ticket on its callback and exchanges it server-side, with its own service key, for a short-lived module-user token.
3. Keeps that token in a server-side session. The browser only holds an opaque, HttpOnly session cookie.
4. Sends **both** the service key and the module-user token on every call to Eneo, and refreshes the token until Eneo's session ceiling.
5. Listens on port 3001 and answers `/health`.

The full contract is in [design.md](docs/design.md) section 2, in Eneo's [module operator guide](https://github.com/eneo-ai/eneo/blob/develop/docs/deployment/MODULES.md) and in its "Module Authentication" reference. The flow as diagrams: [architecture](docs/architecture.md#login-handoff).

## The three parts

```
packages/bff/    eneo-module-bff        FastAPI: module login, session, proxy to Eneo          built
packages/ui/     @eneo-ai/module-kit    React + Astryx: theme, providers, page shell, screens  planned
template/        the smallest working module, built against both packages on every commit       planned
docs/            the module contract with Eneo, architecture, guides and decisions
```

A new module starts as a copy of `template/` and imports the two packages. It does not copy package code, so a fix to login or to the UI arrives as a version bump.

**`packages/bff`** (built), the contract above, ready to use:

- Configuration with start-up validation.
- Login, callback, ticket exchange, session store, single-flight token refresh, logout, session status.
- A same-origin check for writes and WebSocket handshakes.
- Transport primitives: a deny-by-default proxy that adds both credentials, upload forwarding, file streaming with Range support.
- Health, branding, security headers, and serving the built UI.

**`packages/ui`** (planned):

- The Eneo theme for [Astryx](https://astryx.atmeta.com), built to static CSS, and the providers a page needs (theme, Swedish strings).
- A presentational page shell and brand lockup.
- The session screens: sign-in, the warning before the login ends, the cover while signed out.
- Generic loading, problem and offline states.

**`template/`** (planned), a Vite + React app served as static files by the BFF, in one process and one container: a `main.py` that declares the module's own allowed Eneo routes, a sign-in page and one example page, Dockerfile, compose file, CI, devcontainer, agent instructions, an accessibility gate, and a stub Eneo for development.

## What stays in each module

- **Its route allowlist.** The proxy denies by default; a module names the Eneo routes it exposes.
- Its domain features and protocols (for speech-to-text: recording, live transcription, transcript editing).
- Its own copy, recovery messages and draft handling.

## Built for AI agents

This repository has an [AGENTS.md](AGENTS.md) (directory map, commands, rules) and a `CLAUDE.md` that imports it. Every module made from the template will start with the same agent setup (planned), so an agent produces the same kind of UI in each one without being corrected:

- `AGENTS.md` with the module's rules, and a `CLAUDE.md` that imports it.
- The Astryx CLI, pinned, behind an `astryx` npm script, and the block `astryx init --features agents` generates.
- The UI package as an Astryx integration: it adds the Eneo page templates, a doc topic and the kit's own lines to that block, and `astryx build` proposes the Eneo shell first.

There is no custom MCP server and no skill. Astryx's hosted MCP server is optional for discovery; the pinned CLI is the source of truth. See [K12](docs/decisions/k12-agent-setup.md).

## Where to read next

| You want | Read |
|---|---|
| The pictures: parts, login, proxy, uploads, deployment | [docs/architecture.md](docs/architecture.md) |
| To write a module | [docs/guides/build-a-module.md](docs/guides/build-a-module.md) |
| Every setting | [docs/guides/configuration.md](docs/guides/configuration.md) |
| To run against a stub Eneo | [docs/guides/local-development.md](docs/guides/local-development.md) |
| What to check before going live | [docs/guides/security-checklist.md](docs/guides/security-checklist.md) |
| Why it is this way | [docs/decisions/](docs/decisions/README.md), [docs/design.md](docs/design.md) |
| The BFF's routes, answers and names | [packages/bff/README.md](packages/bff/README.md) |
| A term | [docs/glossary.md](docs/glossary.md) |
| Every page, with its status | [docs/README.md](docs/README.md) |

## What comes next

| Part | Can start |
|---|---|
| BFF package, extracted from speech-to-text's backend with its tests | Done |
| Template skeleton and contract docs | Now |
| UI package: theme and providers | When speech-to-text's Astryx foundation is on its `main` |
| UI package: shell and session screens | When speech-to-text's first ported phase is merged |
| Speech-to-text running on the kit | After its Astryx port, on a released kit version |

## Build scaffolding (temporary)

The implementation plan (`docs/plans/2026-10-01-module-kit-plan.md`) and the work order in Beads (`.beads/`, prefix `kit`) exist only while the kit is built. Permanent pages do not depend on them.

## Licence

AGPL-3.0-only, the same licence as Eneo: see [LICENSE](LICENSE).
