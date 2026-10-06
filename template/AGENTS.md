# Agent instructions: this Eneo module

A module made from `eneo-module-kit`: a FastAPI backend (the kit's BFF) serving a Vite + React + Astryx app, one process
and one container. Read `README.md` first. The UI rules below are in addition to the generated block in `web/AGENTS.md`;
where they differ, these win.

## Where things are

- `backend/main.py`: the app, and `PROXY_RULES`, the Eneo routes this module may call. `backend/routes.py`: the module's
  own API routes (`router`). `backend/tests/`: they run without Eneo.
- `web/src/`: the app. `main.tsx` (providers, stylesheets), `App.tsx` (routes), `Frame.tsx` (the shell every page uses),
  `config.ts` (the module's name), `pages/`.
- `web/tests/e2e/`: browser tests against the built app, and the accessibility gate. `stub-eneo/`: Eneo's side of the
  contract, for development and tests. It is never shipped.

## Rules

- **Every API route needs `require_session`; a route that writes also needs `require_same_origin`.** Never remove them
  to make a test pass. `backend/tests/test_routes.py` fails when one is missing.
- **The proxy denies by default.** Add one `rule(...)` to `PROXY_RULES` per Eneo route the app calls, with the methods
  it needs, and a test for it. Do not add a catch-all.
- Build UI from Astryx components. From `web/`: `npm run astryx -- build "<idea>"`, then
  `npm run astryx -- component <Name>` for every component. Never guess a prop.
- A page renders no `<main>` and no skip link: `Frame` (the kit's `ModuleShell`) has them. Cap a page's content with
  the `Layout` in `Frame`; a `VStack` stretches its children to the window's whole width.
- No Tailwind, no ejected Astryx component, no authored StyleX (`stylex.create`, `xstyle`). Colours, spacing and radii
  are Astryx tokens (`var(--color-*)`, `var(--spacing-*)`), never hex or pixel values. A design-system shortfall (a target
  under 44 px, a missing focus ring) is fixed once in the kit's theme, not in a page.
- Astryx is pinned to an exact version. Do not upgrade it in a feature change.
- User-facing text is Swedish and `lang="sv"`. No font, script, image or request to another origin.
- The Content Security Policy has no `unsafe-inline`: no inline `<script>`, no `style="..."` in markup. Styles set from
  script (`element.style.x = ...`, a React `style` prop) are fine.
- Accessibility bar: WCAG 2.2 AA, 44 px touch targets (24 px with a mouse), a visible focus indicator. A new page adds its
  states to `web/tests/e2e/screens.ts`; `npm run test:e2e` in `web/` is the proof, and its thresholds are never lowered.
- A page that needs a session goes inside `RequireSession`, and calls the backend with `fetchWithSession` (both from the kit's
  `session` export): when the login ends the page is covered and kept, and a read waits for the new login. A dialog of
  the page is closed while `useSignedOut()` says so (`isOpen={open && !signedOut}`, its state above it). The browser holds only an opaque cookie; the module-user
  token never reaches it.

## Checks

- Backend: `python -m unittest discover -s backend/tests -t backend` (from the module's folder).
- Web: `npm run lint`, `npm run build`, and `npm run test:e2e` (builds first; starts the stub Eneo and the backend itself).
  `PYTHON`, if you set it for `test:e2e`, must be an absolute path to a python that has `eneo-module-bff`: a relative one fails.
