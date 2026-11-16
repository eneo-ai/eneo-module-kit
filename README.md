# eneo-module-kit

Purpose: the starter for Eneo modules, small web apps that run beside an Eneo installation on their own domain and use Eneo as their AI engine.
Read this when: you start a module, work on a part of the kit, or want to know what is built and what is planned.
Related: [docs index](docs/README.md), [architecture](docs/architecture.md), [new module](docs/guides/new-module.md), [build a module](docs/guides/build-a-module.md), [decisions](docs/decisions/README.md), [AGENTS.md](AGENTS.md).

På svenska, för workshopdeltagare: [Prova en modul på tio minuter](docs/guides/prova-en-modul.md).

## What a module is, and when you need one

Assistants and spaces are the foundation of Eneo. Most needs are met there, without code: a prompt, a model and the right knowledge. Start there.

A module is for what they cannot give you: **an interface of your own and logic of your own**. It is a small web app on its own address, beside Eneo. Eneo stays the only login and is the module's AI engine, so the module does one thing well. The first one, [speech to text](https://github.com/eneo-ai/eneo-mod-speech-to-text), records, transcribes and lets a person edit the text.

Every module needs the same things: the login handoff from Eneo, a server-side session, a way to Eneo's API that denies everything it was not told to allow, a themed and accessible page frame, a container image and CI. The kit holds them once. **The packages are imported, the template is copied, and you build only what your module does.**

## Quick start: from a clone to a signed-in module

You need Git, Node 22.22.2 or newer and Python 3.12 or newer, on macOS, Linux or Windows. You need no Eneo: the template has a stub Eneo to develop against. CI runs these commands on all three systems.

```bash
git clone https://github.com/eneo-ai/eneo-module-kit.git
cd eneo-module-kit
node scripts/new-module.mjs ../eneo-mod-example
cd ../eneo-mod-example
node stub-eneo/dev.mjs --check
node stub-eneo/dev.mjs
```

| Command | What you should see |
|---|---|
| `node scripts/new-module.mjs ../eneo-mod-example` | A minute or two of installing and building, ending with `The module is in ...` |
| `node stub-eneo/dev.mjs --check` | It starts the stub Eneo and the module, signs in and stops. The last line starts with `OK: signed in through the stub Eneo` and ends with `{"greeting":"Hej Erik Lund"}` |
| `node stub-eneo/dev.mjs` | `The module runs on http://localhost:3001 against the stub Eneo on http://localhost:8411.` Open that address, press **Logga in med Eneo**, and the page **Välj ett flöde** shows `Hej Erik Lund` and two flows. Ctrl+C stops it |

The new module has its own `README.md`, `AGENTS.md`, `CLAUDE.md` and a skill, so a coding agent started in its folder knows how to build on it. What each step does, the same steps by hand, and what to do when one fails: [new module](docs/guides/new-module.md).

> **Start from a checkout, as above, not from the release.** The GitHub release `v0.1.0` does not fit the template on `main`: its UI package needs Astryx 0.6.3 and the template has 0.7.12, so `npm install` of the release's tarball stops with `ERESOLVE`. The packages are not on npm or PyPI either. This holds until a newer release exists.

The kit is extracted from speech to text. Treat every API as provisional (0.x) until a second module has used it.

## Status

| Part | Path | What it is | Status |
|---|---|---|---|
| BFF package | `packages/bff/` | `eneo-module-bff`: FastAPI, the module contract with Eneo | **Built and tested.** Version 0.1.0, released as an asset of the GitHub release [`v0.1.0`](https://github.com/eneo-ai/eneo-module-kit/releases/tag/v0.1.0); not on PyPI yet. |
| UI package | `packages/ui/` | `@eneo-ai/module-kit`: React and Astryx: theme, colour mode, providers, page shell, brand | **Built and tested.** Version 0.1.0, released as an asset of the GitHub release [`v0.1.0`](https://github.com/eneo-ai/eneo-module-kit/releases/tag/v0.1.0); not on npm yet. `@eneo-ai/module-kit/session` is the session client: the gate (`RequireSession`), the sign-in screen, the page a login window lands on (`SignedInAgain`) and `fetchWithSession`. See `packages/ui/README.md`. |
| Template | `template/` | The smallest working module: backend, stub Eneo, Vite app, Dockerfile, compose files, CI that publishes the tested image, releases by tag, agent files | **Built and tested** against both packages on every commit. Its pages run on the kit's session client. |
| Docs | `docs/` | Architecture, guides, decisions, the module contract | Current. |
| Release 0.1.0 | | Both packages as assets of the GitHub release [`v0.1.0`](https://github.com/eneo-ai/eneo-module-kit/releases/tag/v0.1.0) (the UI package's tarball, the BFF's wheel and sdist, `SHA256SUMS`), built by CI from the tagged commit | **Released** 2026-11-08. Publishing to npm and PyPI is pending. The release does not fit the template on `main` (its UI package needs Astryx 0.6.3, the template has 0.7.12): a module made from the template installs the packages of a checkout ([quick start](#quick-start-from-a-clone-to-a-signed-in-module)). |

What is built versus planned is marked on every page. The decisions behind both are in [docs/decisions/](docs/decisions/README.md).

## Work on the BFF package

For a change to the package itself, not for starting a module. From the repository root (Python 3.12):

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

[New module](docs/guides/new-module.md) has every step after the quick start, in order: rename, environment, test, build the image, register in Eneo, and what CI proves. A plain `docker build` of the template as it ships fails (its BFF pin is a placeholder, and its lock looks for the UI package in `web/vendor/`): [the guide](docs/guides/new-module.md#6-build-the-image) builds the image with the packages of this checkout.

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
packages/ui/     @eneo-ai/module-kit    React + Astryx: theme, providers, shell, brand, session   built
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
- The session client, `@eneo-ai/module-kit/session`: the sign-in screen, keeping the login (a keepalive, a warning five minutes before the end), and a cover over the page, with a sign-in dialog, when the login has ended, so nothing on the page is lost.

**`template/`** (built), a Vite + React app served as static files by the BFF, in one process and one container: a backend that declares the module's own allowed Eneo routes and one guarded route of its own, a sign-in page and one example page, Dockerfile, a production compose file with a Traefik overlay, module CI that publishes the tested image and releases it by tag ([release and deploy](docs/guides/deploy.md)), devcontainer, agent instructions, one command that starts it against the stub Eneo (`stub-eneo/dev.mjs`), browser tests in three browsers, an accessibility gate in Chromium at eleven screen settings and in WebKit and Firefox at four, production checks of what the backend sends with the built UI in all three, unit tests with guards of the module's code, and a stub Eneo for development.

## What stays in each module

- **Its route allowlist.** The proxy denies by default; a module names the Eneo routes it exposes.
- Its domain features and protocols (for speech-to-text: recording, live transcription, transcript editing).
- Its own copy, recovery messages and draft handling.

## Built for AI agents

This repository has an [AGENTS.md](AGENTS.md) (directory map, commands, rules) and a `CLAUDE.md` that imports it. Every module made from the template starts with guidance for setup, Eneo integration and UI work:

- `AGENTS.md` with the module's rules, and a `CLAUDE.md` that imports it and `web/AGENTS.md`.
- A local [eneo-module skill](template/.agents/skills/eneo-module/SKILL.md), linked by `AGENTS.md` and imported by `CLAUDE.md`. It guides setup and feature work through the existing examples, contract and checks.
- The Astryx CLI, pinned, behind an `astryx` npm script, and the block `astryx init --features agents` generates (`web/AGENTS.md`).
- The UI package registers its page and sign-in templates, `eneo-module` topic and eight agent guidance lines with the pinned Astryx CLI. See [the UI guide](docs/guides/ui-package.md#astryx-integration).

Astryx's hosted MCP server is optional for discovery; the pinned CLI is the source of truth. There is no custom MCP server. See [K17](docs/decisions/k17-module-development-skill.md).

## Where to read next

| You want | Read |
|---|---|
| The pictures: parts, login, proxy, uploads, UI layers, image, deployment | [docs/architecture.md](docs/architecture.md) |
| To try a module in ten minutes, in Swedish | [docs/guides/prova-en-modul.md](docs/guides/prova-en-modul.md) |
| To start a module | [docs/guides/new-module.md](docs/guides/new-module.md) |
| To write a module's backend | [docs/guides/build-a-module.md](docs/guides/build-a-module.md) |
| To release and deploy a module | [docs/guides/deploy.md](docs/guides/deploy.md) |
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
| UI package: the session client and screens | Done |
| Astryx integration | Built: two reference templates, the `eneo-module` topic and generated agent guidance |
| Release 0.1.0 of both packages | Released 2026-11-08 as GitHub release assets, built by `.github/workflows/release.yml` |
| Both packages on npm and PyPI | Pending. Public packages under `@eneo-ai` and AGPL-3.0-only are decided; the npm scope and the PyPI project are set up first ([design.md](docs/design.md) section 7) |
| The template on the release's pins | Planned: its `backend/requirements.txt` and `web/package-lock.json` name the release instead of a commit and a packed tarball |
| Speech-to-text running on the kit | Planned. It runs on Astryx with its own copies of this code, and moves to the kit on a released kit version |

## Licence

AGPL-3.0-only, the same licence as Eneo: see [LICENSE](LICENSE).

## Build scaffolding (temporary)

The implementation plan (`docs/plans/2026-10-01-module-kit-plan.md`) and the work order in Beads (`.beads/`, prefix `kit`) exist only while the kit is built. Permanent pages do not depend on them.
