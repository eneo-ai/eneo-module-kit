# Agent instructions: eneo-module-kit

The starter for Eneo modules. `packages/bff`, `packages/ui` and `template/` are built and tested; the UI package's session client, the Astryx integration and the first release are planned. Read `README.md` first (what is built, what stays in each module), then `docs/README.md` (the index of every page and its status).

## Directory map

| Path | Holds | Status |
|---|---|---|
| `packages/bff/src/eneo_module_bff/` | The BFF package, one file per concern: `app.py` (factory), `auth.py` (login, session, refresh), `deps.py` (route dependencies), `proxy.py` (allowlist proxy), `transport.py` (uploads, signed files), `limits.py` (body limit), `web.py` (security headers, built UI), `branding.py`, `settings.py`, `serve.py`. `__init__.py` holds the public names | built |
| `packages/bff/tests/` | unittest, one file per module of the package | built |
| `packages/bff/README.md` | The package's public names, HTTP surface, answers and limits | current |
| `packages/ui/src/` | The UI package: `color-mode.tsx`, `ModuleProviders.tsx`, `ModuleShell.tsx`, `branding.tsx`, `theme/eneo.theme.ts` (source) and `theme/built/` (generated, committed), `layers.css`, `base.css`; `index.ts` holds the public names | built |
| `packages/ui/tests/` | node:test with jsdom, one file per concern | built |
| `template/` | The smallest working module: `backend/` (the kit's BFF with one allowlist rule and one guarded route), `stub-eneo/` (Eneo's side, development only), `web/` (Vite, React, react-router: `src/`, and `tests/e2e/` for the browsers and the accessibility gate), `Dockerfile`, `docker-compose.yml`, `.env.example`, `.devcontainer/`, `.github/workflows/ci.yml` (a module's own CI), its own `AGENTS.md` | built |
| `docs/` | `architecture.md`, `guides/`, `decisions/`, `glossary.md`, `design.md` (long form); `docs/README.md` is the index | current |
| `.github/workflows/ci.yml` | CI: jobs `bff` (lowest and newest versions, `pip-audit`), `ui`, `template-backend`, `template-web`, `template-image`, each against the packages of the same commit | built |

## Commands

From the repository root (Python 3.12):

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e "packages/bff[test]"
.venv/bin/python -m unittest discover -s packages/bff/tests -t packages/bff                      # all
.venv/bin/python -m unittest discover -s packages/bff/tests -t packages/bff -p "test_proxy.py"   # one file
```

The UI package and the template (Node 22; the BFF installed as above):

```bash
npm ci
npm run -w packages/ui lint
npm test -w packages/ui
npm run -w packages/ui build
npm run -w packages/ui theme:build && git diff --exit-code -- packages/ui/src/theme/built   # the theme is generated: commit what it writes
.venv/bin/python -m unittest discover -s template/backend/tests -t template/backend
.venv/bin/python -m unittest discover -s template/stub-eneo
npx playwright install --with-deps chromium webkit firefox                                 # once
npm run -w template/web test:e2e                      # builds, starts the stub and the backend, browsers and the gate
```

The browser tests start servers on `E2E_APP_PORT` (default 3011) and `E2E_STUB_PORT` (default 8011): set both when other agents run the gate too. `.venv/bin/python` at the repository root is the interpreter they use (`PYTHON` overrides it). Narrow a run with `-- --project=chromium`.

CI also runs the BFF suite at the lowest versions the dependency ranges allow. Locally, in a throwaway environment:

```bash
V=$(mktemp -d) && uv venv "$V" && uv pip install --python "$V/bin/python" --resolution lowest-direct -e "packages/bff[test]" \
  && "$V/bin/python" -m unittest discover -s packages/bff/tests -t packages/bff; rm -rf "$V"
```

Never `pkill -f`; stop only what you started. Dependencies are ranges with security floors (`packages/bff/pyproject.toml`); add no runtime dependency without a line in `docs/design.md`.

## Rules that are already decided

- One stack: Vite + React + Astryx for the UI, FastAPI for the BFF, one process and one container. Do not add Next.js, Hono, Tailwind or a second UI library.
- The BFF package holds the module contract with Eneo (login handoff, session, token refresh, deny-by-default proxy, transport primitives). A module's route allowlist and its own protocols stay in the module: no module-specific route in `packages/bff`, no allowlist entry shipped by the kit.
- No import-time application state in `packages/bff`: no module-level `settings`, `app`, `http_client` or cache. Everything hangs off the app `create_app` returns.
- A behaviour change comes with its test in `packages/bff/tests/`. A carried-over behaviour keeps its test.
- The UI package imports nothing from a router or a meta-framework, no stylesheet from its code, and nothing from the template (`packages/ui/tests/package.test.ts` pins this).
- Astryx is pinned to an exact version. Run its CLI through the package script (`npm run astryx -- <command>`), read `npm run astryx -- component <Name>` before using a component, and never guess a prop.
- No ejected Astryx components and no authored StyleX. A design-system shortfall is fixed once, in the theme.
- User-facing text in the template is Swedish. No fonts or scripts from other origins. These docs and the code comments are English.
- Accessibility bar: WCAG 2.2 AA, 44 px touch targets, a visible focus indicator, proven by the gate the template ships.

The reasons are in `docs/decisions/` (one page each) and `docs/design.md`.

## How to find things

| Question | Look in |
|---|---|
| What does a route return, and when? | `packages/bff/README.md` ("HTTP surface", "Answers the package gives"), then the file named in `docs/architecture.md` ("Where each fact lives") |
| What does a setting do? | `docs/guides/configuration.md`, `packages/bff/src/eneo_module_bff/settings.py` (`load_settings`) |
| How does login, refresh or a proxied request work? | The diagrams in `docs/architecture.md`; the code in `auth.py` and `proxy.py` |
| Why is it like this? | `docs/decisions/README.md`, then `docs/design.md` sections 3 and 6 |
| What does a term mean? | `docs/glossary.md` |
| What is covered by a test? | `packages/bff/tests/test_<module>.py`, named after the file it tests |
| An exact symbol, string or status code | `rg` in `packages/bff/src` and `packages/bff/tests` |

## Keep the docs true

Code and docs change in one commit. If they disagree, the code wins: fix the doc.

| If you change | Update |
|---|---|
| A setting, its default or its check (`settings.py`) | `docs/guides/configuration.md` (the table), `packages/bff/README.md` if it names it |
| A route, a status code or an error body | `packages/bff/README.md` (the two tables), the diagram in `docs/architecture.md` that shows it, `docs/design.md` section 5 |
| A public name (`__init__.py`) | `packages/bff/README.md` ("Public names"), `docs/guides/build-a-module.md` |
| A limit or a security property | `docs/guides/security-checklist.md`, the decision page it belongs to |
| A name the UI package exports (`packages/ui/src/index.ts`) or a prop of one | `packages/ui/README.md`, `docs/guides/ui-package.md` |
| The template (a file it ships, a command in its README, the Dockerfile, a CI job) | `docs/guides/new-module.md`, `docs/architecture.md` (the image and CI sections) |
| A decision | A new page in `docs/decisions/` (the next K number) and its row in `docs/decisions/README.md`; mark the old page superseded |

Page rules: start with `Purpose:`, `Read this when:` and `Related:`; one fact in one place; every claim about code names a path, never a line; diagrams are Mermaid `flowchart` or `sequenceDiagram` only, with a sentence above each; say whether a part is built, planned or temporary.

## What not to touch

- The speech-to-text repository. This repository copies from it and never changes it.
- `docs/reference/astryx-phase0-reference.patch`: a frozen copy, the source the UI package was built from.
- `packages/ui/src/theme/built/` and the block between the `ASTRYX:START` and `ASTRYX:END` markers of `template/web/AGENTS.md` by hand: both are generated (`npm run -w packages/ui theme:build`; `npm run astryx -- init --features agents` in `template/web`).
- `docs/design.md` section 2 (the module contract with Eneo): it mirrors Eneo's side (`docs/deployment/MODULES.md` in `eneo-ai/eneo`); change it only together with that.
- `.beads/issues.jsonl` by hand: use `br`.

## What the template gives every new module

- Built: `template/AGENTS.md` with the module's rules, a `template/CLAUDE.md` that imports it and `web/AGENTS.md`, the pinned Astryx CLI with an `astryx` npm script, and the block `astryx init --features agents` generates (in `template/web/AGENTS.md`, between its markers: do not edit by hand).
- Planned: the UI package registered as an Astryx integration, so `astryx build` proposes the Eneo shell and the generated block carries the kit's own lines.
- No custom MCP server and no skill. Add a skill only when agents are seen skipping these files.

## Build scaffolding (temporary)

This section, the plan, the Beads board and the reference patch exist only while the kit is built. Permanent pages do not depend on them.

- Design: `docs/design.md`. Plan: `docs/plans/2026-10-01-module-kit-plan.md`. Read "Global Constraints" and "How to work" in the plan every time.
- Work order and status live in Beads in this repository (prefix `kit`): `br ready --json`, claim, close with evidence. Each bead names the files it may touch and what is out of scope. Do not start a bead that is not ready.
- The source to extract from is `eneo-ai/eneo-mod-speech-to-text` at commit `f81a7dd`, cloned beside this repository: `backend/app/` and `backend/tests/` for the BFF. The verified Astryx foundation (theme, providers, test shims, gate changes) is in `docs/reference/astryx-phase0-reference.patch`.
