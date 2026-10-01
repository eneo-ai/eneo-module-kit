# The UI package

Purpose: say how a module installs `@eneo-ai/module-kit`, wires it up, and what each export does.
Read this when: you build a module's pages, change the colour mode, the page shell or the brand lockup, or touch the theme.
Related: [new module](new-module.md), [architecture](../architecture.md#the-ui-app-and-its-layers), [decisions K9](../decisions/k09-colour-mode-in-the-ui-package.md), [K10](../decisions/k10-branding-without-templating.md), [K11](../decisions/k11-astryx-pinned.md), [package README](../../packages/ui/README.md), [BFF README](../../packages/bff/README.md).

`@eneo-ai/module-kit` (`packages/ui`, version 0.1.0, not released) is the UI half of a module, for a static Vite + React app: the Eneo theme for [Astryx](https://astryx.atmeta.com), the colour mode, the providers a page needs, the page shell and the brand lockup. It imports nothing from a router or a meta-framework (a test pins this). Built: those, and the session client (`@eneo-ai/module-kit/session`: the gate, the sign-in screen, the warning before the login ends, the cover while signed out). Planned: the Astryx integration.

## Install

The package is not on npm yet. Pack it from a checkout of this repository:

```bash
# in the kit checkout
npm ci
npm run -w packages/ui build
npm pack -w packages/ui --pack-destination /path/to/dir      # writes eneo-ai-module-kit-0.1.0.tgz
```

- **A module made from the template** puts the tarball in `web/vendor/` and runs `npm ci`: the template's `web/package-lock.json` already says the package is found there, and every other package is locked with its hash. After a change of a dependency, `node scripts/relock.mjs <tarball>` regenerates the lock. Not `npm install <tarball>`: it rewrites `package.json` and the lock to a `file:` path. [New module](new-module.md#2-install-the-packages) has the steps.
- **Any other app** installs the tarball: `npm install /path/to/dir/eneo-ai-module-kit-0.1.0.tgz`.

Install the tarball, not the folder (`npm install file:../eneo-module-kit/packages/ui`). A folder install is a symlink, and the package then finds `react` in the kit's `node_modules`, the module finds its own: two copies of React, and hooks fail. (Checked: the two paths resolve to different files.) Inside this repository the template's `web/` is an npm workspace, which hoists one copy, so the template needs no tarball there. The template's Dockerfile puts the tarball in `web/vendor/` itself: see [new module](new-module.md#6-build-the-image).

Node: a module that uses the package needs `>=22.13.0` (the Astryx CLI's own minimum, the package's `engines`). Working in this repository needs `^22.22.2 || ^24.15.0 || >=26.0.0`, and `template/web` needs `>=22.22.0` ([new module](new-module.md#node-and-python)).

Peer dependencies, all exact except React: `@astryxdesign/core` `0.6.3`, `@stylexjs/stylex` `0.19.1`, `react` and `react-dom` `>=19`. The module lists them itself (the template's `web/package.json` does).

## Wire it up

The package imports no stylesheet from its code; the module imports five, in this order:

```tsx
// web/src/main.tsx (the template's, with React Router's Link passed as it is)
import "@eneo-ai/module-kit/layers.css";   // first: declares the cascade layers
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@eneo-ai/module-kit/theme.css";    // the built Eneo theme
import "@eneo-ai/module-kit/base.css";     // what the theme cannot say
import { BrandingProvider, ModuleProviders } from "@eneo-ai/module-kit";

createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <ModuleProviders linkComponent={Link}>
      <BrandingProvider defaultLogo="/brand/logo.svg">
        <App />
      </BrandingProvider>
    </ModuleProviders>
  </BrowserRouter>,
);
```

A page is a `ModuleShell` with the brand in its heading:

```tsx
<ModuleShell label="Min modul" heading={<Brand productName="Min modul" href="/flows" />} end={<AccountMenu />}>
  <Layout height="auto" contentWidth={960} padding={4}>…</Layout>
</ModuleShell>
```

The template wraps that once in `web/src/Frame.tsx`, so a page renders `<Frame>`.

## The five exports of the package

| Import | What it is |
|---|---|
| `@eneo-ai/module-kit` | The code, below. |
| `@eneo-ai/module-kit/layers.css` | `@layer reset, astryx-base, astryx-theme;` Import it first, so the layers have their order. |
| `@eneo-ai/module-kit/theme.css` | The built Eneo theme. Generated from `packages/ui/src/theme/eneo.theme.ts` by `npm run theme:build` (in `packages/ui`), committed in `src/theme/built/`, and CI fails when it is stale. |
| `@eneo-ai/module-kit/base.css` | What the theme cannot say: the shell's bar scrolls away with the page, the brand's mark sizing and colour-mode swap, forced-colour edges for buttons and the slider, no ring on a heading that takes focus (`data-phase-heading`), and the cover that hides the page while the login has ended. Unlayered on purpose: it wins over the design system's layered styles. |
| `@eneo-ai/module-kit/session` | The session client, below. |

## The code

| Name | What it is |
|---|---|
| `ModuleProviders({ children, linkComponent? })` | The colour mode, Astryx's `<Theme>` with the built Eneo theme, Astryx's own words in Swedish (`sv-SE`), the place Astryx's toasts (`useToast`) appear (a `LayerProvider` inside the theme: without it `useToast` mounts a root of its own that speaks English), and, with `linkComponent`, Astryx's `LinkProvider`. |
| `ColorModeProvider` | The colour mode alone. `ModuleProviders` has one; use it directly only outside `ModuleProviders`. |
| `useColorMode()` | `{ mode, resolved, setMode }`. `mode` is the choice (`light`, `dark`, `system`), `resolved` is what is shown (the operating system's for `system`), `setMode(next)` applies and stores it. Throws outside a `ColorModeProvider`. |
| `readStoredColorMode(storage?)` | The stored choice, or `system` when there is none, it is not one of the three, or storage throws. |
| `COLOR_MODE_KEY` | `"theme"`. |
| `ModuleShell({ label, heading, start?, end?, banner?, height?, children })` | The page frame: top bar, skip link, one `role="main"` region. `label` names the navigation landmark; `heading` is the brand; `start` follows it and may wrap; `end` is the account menu; `banner` is a notice above the bar; `height` is `"auto"` (the page grows, the window scrolls) or `"fill"` (the shell is the window's height and the main region scrolls itself). |
| `BrandingProvider({ children, defaultLogo?, deadlineMs?, fetchImpl? })` | Asks `GET /api/branding` once, when the app starts. `defaultLogo` is the module's own copy of its bundled logo. `deadlineMs` defaults to `BRANDING_DEADLINE_MS` (2000). `fetchImpl` is for tests. |
| `BRANDING_DEADLINE_MS` | `2000`. |
| `Brand({ productName, href?, onClickCapture? })` | The header lockup: the organisation's mark, a divider and the product's name; without an organisation the name alone. With `href` it is a link, named for both. |
| `eneoTheme` | The built theme object, for `<Theme>` outside `ModuleProviders`. |
| `Branding`, `ColorMode` | Types: the answer of `/api/branding`, and `"light" \| "dark" \| "system"`. |

## Colour mode

- The key is `localStorage["theme"]` with the values `light`, `dark`, `system`: the key and values next-themes used, so a person's choice made in an app on it carries over ([K9](../decisions/k09-colour-mode-in-the-ui-package.md)).
- It is read when the provider first renders, so the first paint is already in the right mode, and passed to Astryx's `<Theme mode>`, which sets `data-theme` on the document for `light` and `dark` (for `system` it sets none, and the browser's preference decides).
- There is no inline script and no cookie: the page's Content-Security-Policy has no `unsafe-inline` ([K4](../decisions/k04-static-ui-served-by-the-bff.md)). A module must not add one to fix a flash of the wrong mode.
- `system` follows `prefers-color-scheme` and its changes. A choice made in another tab reaches this one (the `storage` event).
- Storage that is missing or throws is not an error: no choice is `system`, and a choice still applies for the visit.
- A module's own menu uses `useColorMode()`: the template's `AccountMenu` has the three choices.

## Links

The package imports no router. Astryx draws some links itself (the brand in the top bar, a link button); `ModuleProviders linkComponent={...}` makes them the app's router links, through Astryx's `LinkProvider`. The component receives the props of an anchor, `href` first (`href`, `children` and the usual anchor attributes), and also `to`, the same address, which Astryx adds for routers that take their address as `to`. So React Router's `Link` is passed as it is, and a component that takes `href` needs nothing more:

```tsx
<ModuleProviders linkComponent={Link}>   {/* Link from "react-router" */}
```

A router whose link wants something else needs a small adapter of its own. (A test in `packages/ui/tests/readme.test.ts` pins this: Astryx gives the component `href` and `to`, and a press moves the router, not the page.) The template's `main.tsx` still wraps `Link` in a small `RouterLink` that turns `href` into `to`: it predates this and is not needed.

Without `linkComponent` the links are plain anchors and a click reloads the page. A link that leaves the app for another origin or for the BFF (`/api/auth/login`) is a plain `<a>`, as the template's sign-in page does.

## Branding

- `BrandingProvider` asks `/api/branding` once. It is optional: there is one deadline, and on a slow or failing answer the header shows the product name alone (the failure goes to the console). Until it has answered nothing of an organisation is shown, so no page shows one municipality's mark before another's ([K10](../decisions/k10-branding-without-templating.md)).
- The organisation is a deployment setting of the BFF (`ORGANIZATION_NAME`, `ORGANIZATION_LOGO`, `ORGANIZATION_LOGO_DARK`, `SHOW_ORGANIZATION`: see [configuration](configuration.md)). Its `logo` is `custom` (the deployment's own, served by `/api/branding/logo/light` and `/dark`), `default`, or none.
- **The kit ships no organisation's mark.** `default` means the logo the module bundles in its own frontend: the module passes its URL as `defaultLogo` (a file under its `public/`). Without `defaultLogo`, an organisation whose logo is `default` shows its name as text. The BFF serves no file for `default`.
- `Brand` takes the product's name as a prop: it is the page's own, never the kit's.
- Sizing and the choice between a deployment's two logos are CSS in `base.css`, by the attribute `data-brand-logo` on the mark: `default`, `light`, `dark`, `plain` (one logo for both modes), `name` (no logo). The mode that decides is the document's `data-theme`.

## The shell

- A page renders no `<main>` and no skip link: `ModuleShell` has them.
- Cap a page's content with Astryx's `Layout contentWidth`: a stack stretches its children to the window's whole width.
- A page that must not be left (a recording, a sending) passes less in `end` and `heading`; the shell decides nothing.
- The bar scrolls away with the page (`base.css`): stuck to the top it would hide a focused control (WCAG 2.4.11).

## The session client

`@eneo-ai/module-kit/session` keeps the login of a page that can outlive its login. SSO only: it uses the BFF's `GET /api/auth/status`, `GET /api/auth/login?next=&renew=` and the `X-Auth-Required: session` mark on a 401 ([design.md](../design.md) section 5). A page's whole use of it, from the template's `web/src/App.tsx`:

```tsx
<Route path="/inloggad" element={<SignedInAgain productName={PRODUCT_NAME} />} />   {/* where a login window ends */}
<Route
  path="/flows"
  element={
    <RequireSession productName={PRODUCT_NAME} signInTitle={PRODUCT_NAME} signInDescription={SIGN_IN_TEXT}>
      <Flows />
    </RequireSession>
  }
/>
```

and every call to the backend through `fetchWithSession(path, init)` instead of `fetch` (the template's `getJson` in `web/src/session.ts`).

| Export | What it is |
|---|---|
| `RequireSession` | The gate. Signed out: the sign-in screen (`signIn` replaces it; `navigate` with `signInPath` sends the person to a route of the app's own). Signed in: `children`, the keepalive (the backend's `refresh_in`), a status read when the page is seen and when a login window says it is done, the warning five minutes before the end, and, when the login has ended, the cover and the sign-in dialog. `onIdentity(user)` is awaited before `children` are shown. `signedOutControls` and `signedOutNote` are for what stays reachable while signed out. |
| `useSessionUser()`, `useSignedOut()`, `useSignedOutSlot()` | The user; whether the login has ended; the place in the sign-in dialog to portal what must stay reachable into. |
| `fetchWithSession(path, init)` | `fetch` over the page's one session state. Signed out, nothing but `/api/auth/*` leaves the page: a GET or HEAD, or a request with an `Idempotency-Key`, waits for the new login and is sent once more; any other fails with `SessionExpiredError`. Answers are returned as they came. |
| `SignInScreen`, `SignedInAgain` | The sign-in screen (one button that starts Eneo's login; it says once when a callback failed, `?auth_error=`); the page a login in a window of its own lands on: it tells the module's tabs (`SESSION_CHANNEL`, `"eneo-module:session"`) and closes itself, or says why a renewal was refused (`?fel=annan-anvandare`, `?fel=utgangen`). Route it at `signedInAgainPath` (default `/inloggad`). |
| `createSessionState()`, `sessionState`, `createFetchWithSession(state)`, `SessionExpiredError`, `isSessionEndedAnswer`, `refusalOf`, `sessionUser`, `userDisplayName`, `userInitial` | The state (one per page, shared by the gate and `fetchWithSession`), for tests and for a transport that is not `fetch`; the error; the helpers. The package README lists them. |

When the login has ended the page is covered, not removed: it stays mounted with all it holds, hidden and out of reach (`inert`), under a native modal dialog with an opaque backdrop that nothing but the new login closes, opened in a window of its own. Only the page's own user signing in again lifts it; someone else's login keeps the page covered and says whom to sign in as. A native dialog of the page is the module's to close while signed out (`isOpen={open && !useSignedOut()}`): see [build a module](build-a-module.md#10-sessions-and-dialogs) and the [security checklist](security-checklist.md#the-cover-for-an-ended-login). The decision: [K15](../decisions/k15-cover-for-an-ended-login.md). The flow: [architecture](../architecture.md#how-a-page-learns-the-login-ended-and-gets-it-back). The Swedish words are in `packages/ui/src/session/messages.ts`.

## Fix a shortfall once

A design-system shortfall (a target under 44 px, a missing focus ring, a label that cannot be read in dark mode) is fixed once, in `packages/ui/src/theme/eneo.theme.ts`, then `npm run theme:build` in `packages/ui`, and the regenerated `src/theme/built/` is committed. Astryx is pinned to an exact version in the package and in the template ([K11](../decisions/k11-astryx-pinned.md)); an upgrade is its own change. No ejected Astryx component and no authored StyleX.

## Develop the package

From the repository root:

```bash
npm ci
npm run -w packages/ui lint       # tsc --noEmit
npm test -w packages/ui           # node:test with jsdom
npm run -w packages/ui build      # tsc to dist/, the stylesheets beside it, and a check that dist/index.js loads with its names
npm run -w packages/ui theme:build && git diff --exit-code -- packages/ui/src/theme/built    # what CI's `ui` job also runs
```

Tests are in `packages/ui/tests/`, one file per concern: colour mode, providers, shell, branding, theme, the session client (`session-gate`, `session-state`, `session-keepalive`, `session-user`), the README's link example, and the package itself (no router import, no CSS import from code, exact pins, every export is built).
