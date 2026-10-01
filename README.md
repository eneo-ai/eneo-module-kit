# eneo-module-kit

Purpose: the starter for Eneo modules, small web apps that run beside an Eneo installation on their own domain and use Eneo as their AI engine.
Read this when: you start a module, work on a part of the kit, or want to know what is built and what is planned.
Related: [docs index](docs/README.md), [architecture](docs/architecture.md), [new module](docs/guides/new-module.md), [build a module](docs/guides/build-a-module.md), [decisions](docs/decisions/README.md), [AGENTS.md](AGENTS.md).

A module needs the same things every time: the login handoff from Eneo, a server-side session, a proxy that sends the right credentials, a themed and accessible UI shell, and a container image. This repository holds those parts once, so a new module imports them instead of copying them.

The first module, [eneo-mod-speech-to-text](https://github.com/eneo-ai/eneo-mod-speech-to-text), is the source the kit is extracted from. Treat every API as provisional (0.x) until that module runs on the kit and a second module has used it.

## Status

| Part | Path | What it is | Status |
|---|---|---|---|
| BFF package | `packages/bff/` | `eneo-module-bff`: FastAPI, the module contract with Eneo | **Built and tested.** Version 0.1.0, not released. |
| UI package | `packages/ui/` | `@eneo-ai/module-kit`: React and Astryx: theme, colour mode, providers, page shell, brand | **Built and tested.** Version 0.1.0, not released. Planned: the session client (sign-in screen, warning before the login ends, the cover while signed out). |
| Template | `template/` | The smallest working module: backend, stub Eneo, Vite app, Dockerfile, compose file, CI, agent files | **Built and tested** against both packages on every commit. Its `RequireSession` is a minimal stand-in for the session client. |
| Docs | `docs/` | Architecture, guides, decisions, the module contract | Current. |
| First release | | Both packages published, the template pinned to their versions | Planned. Until then a module installs the packages from a checkout of this repository. |

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

## Quick start: a module with a UI

From the repository root (Node 22.22.2 or newer, Python 3.12). The packages are not published yet, so the UI package goes in `web/vendor/` as a tarball and the BFF is installed from its folder:

```bash
npm ci && npm run -w packages/ui build
mkdir -p /tmp/kit-pack && npm pack -w packages/ui --pack-destination /tmp/kit-pack
cp -R template ../eneo-mod-example && cd ../eneo-mod-example
cp /tmp/kit-pack/eneo-ai-module-kit-0.1.0.tgz web/vendor/
(cd web && npm ci && npm run build)
python3.12 -m venv .venv && .venv/bin/pip install --require-hashes --no-deps -r backend/requirements.lock
.venv/bin/pip install --no-deps /path/to/eneo-module-kit/packages/bff
```

Then the stub Eneo and the backend, as in step 4 of the guide below.

[New module](docs/guides/new-module.md) has every step in order: rename, environment, run against the stub, test, build the image, register in Eneo, and what CI proves. Until the first release a plain `docker build` of the template fails (the packages are not published): [the guide](docs/guides/new-module.md#6-build-the-image) builds the image with the packages of this checkout, as `template/README.md` does.

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
packages/ui/     @eneo-ai/module-kit    React + Astryx: theme, providers, page shell, brand    built (session screens planned)
template/        the smallest working module, built against both packages on every commit       built
docs/            the module contract with Eneo, architecture, guides and decisions
```

A new module starts as a copy of `template/` and imports the two packages. It does not copy package code, so a fix to login or to the UI arrives as a version bump.

**`packages/bff`** (built), the contract above, ready to use:

- Configuration with start-up validation.
- Login, callback, ticket exchange, session store, single-flight token refresh, logout, session status.
- A same-origin check for writes and WebSocket handshakes.
- Transport primitives: a deny-by-default proxy that adds both credentials, upload forwarding, file streaming with Range support.
- Health, branding, security headers, and serving the built UI.

**`packages/ui`** (built; [guide](docs/guides/ui-package.md)):

- The Eneo theme for [Astryx](https://astryx.atmeta.com), built to static CSS, and the providers a page needs (colour mode, theme, Swedish strings, links through the app's router).
- A presentational page shell and brand lockup.
- Planned: the session screens (sign-in, the warning before the login ends, the cover while signed out) and generic loading, problem and offline states.

**`template/`** (built), a Vite + React app served as static files by the BFF, in one process and one container: a backend that declares the module's own allowed Eneo routes and one guarded route of its own, a sign-in page and one example page, Dockerfile, compose file, module CI, devcontainer, agent instructions, an accessibility gate in three browsers, and a stub Eneo for development.

## What stays in each module

- **Its route allowlist.** The proxy denies by default; a module names the Eneo routes it exposes.
- Its domain features and protocols (for speech-to-text: recording, live transcription, transcript editing).
- Its own copy, recovery messages and draft handling.

## Built for AI agents

This repository has an [AGENTS.md](AGENTS.md) (directory map, commands, rules) and a `CLAUDE.md` that imports it. Every module made from the template starts with the same agent setup, so an agent produces the same kind of UI in each one without being corrected:

- `AGENTS.md` with the module's rules, and a `CLAUDE.md` that imports it and `web/AGENTS.md`.
- The Astryx CLI, pinned, behind an `astryx` npm script, and the block `astryx init --features agents` generates (`web/AGENTS.md`).
- Planned: the UI package as an Astryx integration, so that `astryx build` proposes the Eneo shell first and the generated block carries the kit's own lines.

There is no custom MCP server and no skill. Astryx's hosted MCP server is optional for discovery; the pinned CLI is the source of truth. See [K12](docs/decisions/k12-agent-setup.md).

## Where to read next

| You want | Read |
|---|---|
| The pictures: parts, login, proxy, uploads, UI layers, image, deployment | [docs/architecture.md](docs/architecture.md) |
| To start a module | [docs/guides/new-module.md](docs/guides/new-module.md) |
| To write a module's backend | [docs/guides/build-a-module.md](docs/guides/build-a-module.md) |
| To build its pages | [docs/guides/ui-package.md](docs/guides/ui-package.md) |
| Every setting | [docs/guides/configuration.md](docs/guides/configuration.md) |
| To run against a stub Eneo | [docs/guides/local-development.md](docs/guides/local-development.md) |
| What to check before going live | [docs/guides/security-checklist.md](docs/guides/security-checklist.md) |
| The calls between the BFF and Eneo, with examples | [docs/module-contract.md](docs/module-contract.md) |
| Why it is this way | [docs/decisions/](docs/decisions/README.md), [docs/design.md](docs/design.md) |
| The BFF's routes, answers and names | [packages/bff/README.md](packages/bff/README.md) |
| The UI package's names | [packages/ui/README.md](packages/ui/README.md) |
| A term | [docs/glossary.md](docs/glossary.md) |
| Every page, with its status | [docs/README.md](docs/README.md) |

## What comes next

| Part | State |
|---|---|
| BFF package, extracted from speech-to-text's backend with its tests | Done |
| Template skeleton | Done |
| UI package: theme, colour mode, providers, shell, brand | Done |
| UI package: the session client and screens | Planned |
| Astryx integration, the first release of both packages | Planned. The owner decides first whether the packages are public and who owns the `@eneo-ai` npm scope ([design.md](docs/design.md) section 7) |
| Speech-to-text running on the kit | After its Astryx port, on a released kit version |

## Build scaffolding (temporary)

The implementation plan (`docs/plans/2026-10-01-module-kit-plan.md`) and the work order in Beads (`.beads/`, prefix `kit`) exist only while the kit is built. Permanent pages do not depend on them.
