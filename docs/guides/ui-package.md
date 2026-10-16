# The UI package

Purpose: say how a module installs `@eneo-ai/module-kit`, wires it up, and what each export does.
Read this when: you build a module's pages, change the colour mode, the page shell or the brand lockup, or touch the theme.
Related: [new module](new-module.md), [architecture](../architecture.md#the-ui-app-and-its-layers), [decisions K9](../decisions/k09-colour-mode-in-the-ui-package.md), [K10](../decisions/k10-branding-without-templating.md), [K11](../decisions/k11-astryx-pinned.md), [package README](../../packages/ui/README.md), [BFF README](../../packages/bff/README.md).

`@eneo-ai/module-kit` (`packages/ui`, version 0.1.0, not released) is the UI half of a module, for a static Vite + React app: the Eneo theme for [Astryx](https://astryx.atmeta.com), the colour mode, the providers a page needs, the page shell and the brand lockup. It imports nothing from a router or a meta-framework (a test pins this). Built: those, the Astryx integration, and the session client (`@eneo-ai/module-kit/session`: the gate, the sign-in screen, the warning before the login ends, the cover while signed out).

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

## Astryx integration

The installed package exposes `astryx.integration.mjs`, two templates and the `eneo-module` documentation topic. The pinned CLI discovers them from `node_modules`. The copied template also carries a local module-development skill; it uses these CLI contributions. From a module's `web/` folder:

```bash
npm run astryx -- build "en sida i en Eneo-modul"
npm run astryx -- docs eneo-module
npm run astryx -- template eneo-module-page
npm run astryx -- template eneo-signin
npm run astryx -- init --features agents
```

With a destination path, `template` writes the reference TSX, for example `npm run astryx -- template eneo-module-page src/pages/NewPage.tsx`. Read the component contracts before adapting it. `eneo-module-page` demonstrates a bounded flow list or empty state inside `ModuleShell`; `eneo-signin` delegates to `SignInScreen`. Neither template supplies an API client or routing. Private routes remain inside `RequireSession`; loading, errors and data belong to that route. If the module already uses `Frame`, retain its shell and adapt only the page content.

`init --features agents` regenerates the managed block in `AGENTS.md`, including the kit's eight guidance lines. Do not edit that block by hand. Package maintainers check the contribution roots with `npm run -w packages/ui astryx -- integration pack --check`, then verify discovery and template type checking from a packed consumer outside the repository.

## Wire it up

The package imports no stylesheet from its code; the module imports five, in this order, and renders its router:

```tsx
// web/src/main.tsx (the template's)
import "@eneo-ai/module-kit/layers.css";   // first: declares the cascade layers
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@eneo-ai/module-kit/theme.css";    // the built Eneo theme
import "@eneo-ai/module-kit/base.css";     // what the theme cannot say
import { router } from "./App";

history.scrollRestoration = "manual";      // RouteEffects owns the scroll after a navigation
createRoot(document.getElementById("root")!).render(<RouterProvider router={router} />);   // RouterProvider from "react-router/dom"
```

The template's router is React Router's data router (`createBrowserRouter` in `web/src/App.tsx`): a navigation can be held back to ask first (`useBlocker`), a page's code can be fetched when its route is first entered (`lazy`), and a page that cannot be shown has an error boundary. The providers are in the root route's component, inside the router, so that `Link` works:

```tsx
// web/src/App.tsx (the template's, shortened)
function Root() {
  const { pathname, key } = useLocation();
  const title = [...useMatches()].reverse().map((match) => match.handle?.title).find(Boolean);
  return (
    <ModuleProviders linkComponent={Link}>
      <BrandingProvider defaultLogo="/brand/logo.svg">
        <RouteEffects path={pathname} entry={key} type={useNavigationType()} title={title}>
          <Outlet />
        </RouteEffects>
      </BrandingProvider>
    </ModuleProviders>
  );
}

export const router = createBrowserRouter([
  {
    Component: Root,
    HydrateFallback: RootLoading,                     // the providers and <LoadingShell>, while the first page's code arrives
    children: [
      {
        ErrorBoundary: RouteError,                    // <ErrorPage productName error={useRouteError()} />
        children: [
          { index: true, handle: { title: "Logga in · Min modul" }, element: <SignInScreen … /> },
          { path: "inloggad", element: <SignedInAgain productName="Min modul" /> },
          { Component: Private, children: [            // <RequireSession …><Outlet /></RequireSession>
            { path: "flows", handle: { title: "Välj ett flöde · Min modul" }, lazy: page(() => import("./pages/Flows")) },
          ] },
          { path: "*", element: <NotFoundPage productName="Min modul" /> },
        ],
      },
    ],
  },
]);
```

A page is a `ModuleShell` with the brand in its heading:

```tsx
<ModuleShell label="Min modul" heading={<Brand productName="Min modul" href="/flows" />} end={<AccountMenu />}>
  <Layout height="auto" contentWidth={960} padding={4}>…</Layout>
</ModuleShell>
```

The template wraps that once in `web/src/Frame.tsx`, so a page renders `<Frame>`.

## Package exports

| Import | What it is |
|---|---|
| `@eneo-ai/module-kit` | The code, below. |
| `@eneo-ai/module-kit/layers.css` | `@layer reset, astryx-base, astryx-theme;` Import it first, so the layers have their order. |
| `@eneo-ai/module-kit/theme.css` | The built Eneo theme. Generated from `packages/ui/src/theme/eneo.theme.ts` by `npm run theme:build` (in `packages/ui`), committed in `src/theme/built/`, and CI fails when it is stale. |
| `@eneo-ai/module-kit/base.css` | What the theme cannot say: the shell's bar scrolls away with the page, the brand's mark sizing and colour-mode swap, no transition while the colour mode switches (`data-theme-switching`), the text size set in iOS on an iPhone or iPad (Dynamic Type, in the `reset` layer), no smooth scroll and a still spinner and progress bar with reduced motion, forced-colour edges for buttons, the slider and the progress bar, no ring on a heading that takes focus (`data-phase-heading`), a wait's spinner held back for its first 300 ms (`eneo-wait`), and the cover that hides the page while the login has ended, and a menu's height: Astryx caps a menu at 300 px, which holds six of the theme's 44 px touch rows, so a longer menu may take the window below the top bar (at most 30rem) and scrolls beyond it. Unlayered on purpose, but for the iOS text size: it wins over the design system's layered styles. |
| `@eneo-ai/module-kit/session` | The session client, below. |
| `@eneo-ai/module-kit/templates/eneo-module-page.tsx`, `@eneo-ai/module-kit/templates/eneo-signin.tsx` | Reference TSX source used by the Astryx CLI. Adapt it into the owning module route. |

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
| `OfflineBanner({ productName, message?, status? })` | The notice that the connection is gone, for the shell's `banner`: [below](#online-status). |
| `useConnection(status?)` | `"online"`, `"offline"` (the device has no network) or `"unreachable"` (it has, and a request did not reach the module), and a new render when it changes. |
| `LoadingShell({ productName })` | The page while it waits: the bar, a hidden `<h1>` with the name and a spinner ("Laddar") that shows only after 300 ms (`eneo-wait` in `base.css`), so a quick answer leaves no blink of it. `RequireSession` waits in it, and so can a router while a page's code arrives. |
| `SlowWait({ onRetry, children? })` | Beside a wait with no end in sight: nothing for 15 seconds, then "Det tar längre tid än vanligt." in a status region that was there from the start, "Försök igen" (which calls `onRetry` and judges the wait afresh) and the page's other ways on (`children`). |
| `lazyLoader(get)`, `useLoaded(loader)`, `LoadFailure({ children, keeps?, reload? })` | Code a page fetches when it first needs it (`lazyLoader(() => import("./Editor"))`): fetched once and kept, shared by pages that ask meanwhile. `useLoaded` gives `{ value, failed }`. A failed fetch is kept too: a browser keeps it per address, so there is no retry, and `LoadFailure` says what could not be fetched (and `keeps`, what a reload gives back) beside one action, "Ladda om sidan". Nothing reloads by itself. |
| `RouteEffects({ path, entry, type, title?, children })`, `useRouteReady(ready)` | What a navigation gives the person, around the router's page: [below](#pages-and-navigation). |
| `NotFoundPage({ productName, homeHref? })`, `ErrorPage({ productName, error, homeHref? })` | The pages that stand in for one that cannot be shown: [below](#pages-and-navigation). |
| `useLeaveQuestion(active, warning)` | Leaving a page that holds work asks first: `{ question, leaveFirst, holds }`, [below](#leaving-a-page). |
| `createDrafts(prefix, storage?)` | What someone has typed but not sent, kept per person in this tab: [below](#drafts). |
| `onlineStatus`, `createOnlineStatus(target?, now?)` | The page's one status, which the session client's requests report to, and a way to build one over a stand-in window (tests). A module's own transport reports with `onlineStatus.sending()`, `reportReachable(sent)` and `reportNetworkFailure()`. |
| `VersionInfo({ productName })` | Which build of the module runs, from `GET /api/healthz`, read when it is shown: [below](#which-version-runs). |
| `CopyButton({ text, label, name?, variant? })` | Copies `text` as plain text. A check replaces the copy icon and a screen reader hears "Kopierat" once; the words stay, so the button keeps its width. A copy that fails says "Kunde inte kopiera" until the next press. `name` is the accessible name when it says more than `label`, and starts with it. |
| `Branding`, `BuildIdentity`, `ColorMode`, `Connection`, `Drafts`, `DraftStorage`, `Loader`, `OnlineStatus` | Types: the answer of `/api/branding`, which build runs (`release`, `revision`, `build_date`, `source`, each `null` when not known), and `"light" \| "dark" \| "system"`. |

## Colour mode

- The key is `localStorage["theme"]` with the values `light`, `dark`, `system`: the key and values next-themes used, so a person's choice made in an app on it carries over ([K9](../decisions/k09-colour-mode-in-the-ui-package.md)).
- Before the page's code has run, the template's first-paint script sets it: `web/public/color-mode.js`, which `web/index.html` loads in its head, sets `data-theme` on the document for a stored `light` or `dark` and nothing for `system`. It is a file of the page's own origin, so the Content-Security-Policy, which has no `unsafe-inline` ([K4](../decisions/k04-static-ui-served-by-the-bff.md)), allows it; a module must not add an inline script instead. It reads the same key as the provider (`COLOR_MODE_KEY`).
- The provider reads the choice when it first renders and passes it to Astryx's `<Theme mode>`, which sets `data-theme` on the document for `light` and `dark` (for `system` it sets none, and the browser's preference decides). No cookie.
- For the frames that apply a new mode, `<html>` carries `data-theme-switching`, and a rule in `base.css` turns every transition off: the surfaces and the text change at once, and no control fades in after them.
- `system` follows `prefers-color-scheme` and its changes. A choice made in another tab reaches this one (the `storage` event).
- Storage that is missing or throws is not an error: no choice is `system`, and a choice still applies for the visit.
- A module's own menu uses `useColorMode()`: the template's `AccountMenu` has the three choices.

## Links

The package imports no router. Astryx draws some links itself (the brand in the top bar, a link button); `ModuleProviders linkComponent={...}` makes those that go to a page of the app the app's router links, through Astryx's `LinkProvider`. The component receives the props of an anchor, `href` first (`href`, `children` and the usual anchor attributes), and also `to`, the same address, which Astryx adds for routers that take their address as `to`. So React Router's `Link` is passed as it is, and a component that takes `href` needs nothing more:

```tsx
<ModuleProviders linkComponent={Link}>   {/* Link from "react-router" */}
```

A router whose link wants something else needs a small adapter of its own. (`packages/ui/tests/readme.test.ts` pins this: Astryx gives the component `href` and `to`, and a press moves the router, not the page.)

Only a page of the app opened in the same tab is the router's. Every other link stays a plain anchor that the router never sees, whatever component was given: a fragment, `mailto:`, another origin (also `//host`), a path under `/api` (a file of the backend, the login), a `target` other than `_self`, and a `download`. A router link to `/api/...` would be a navigation to a path the router has no page for. `packages/ui/tests/links.test.ts` presses each kind.

Without `linkComponent` every link is a plain anchor and a click on one to a page reloads the page.

## Branding

- `BrandingProvider` asks `/api/branding` once, when the first `Brand` shows: a page without one (the login window's) asks nothing. It is optional: there is one deadline, and on a slow or failing answer the header shows the product name alone (the failure goes to the console). Until it has answered nothing of an organisation is shown, so no page shows one municipality's mark before another's ([K10](../decisions/k10-branding-without-templating.md)).
- The organisation is a deployment setting of the BFF (`ORGANIZATION_NAME`, `ORGANIZATION_LOGO`, `ORGANIZATION_LOGO_DARK`, `SHOW_ORGANIZATION`: see [configuration](configuration.md)). Its `logo` is `custom` (the deployment's own, served by `/api/branding/logo/light` and `/dark`), `default`, or none.
- Keep `<link rel="stylesheet" href="/api/branding/theme.css" />` in the document head, as `template/web/index.html` does. The BFF supplies the validated accent family before themed content appears; the UI package continues to use its existing Eneo theme. Accent settings are in [configuration](configuration.md).
- **The kit ships no organisation's mark.** `default` means the logo the module bundles in its own frontend: the module passes its URL as `defaultLogo` (a file under its `public/`). Without `defaultLogo`, an organisation whose logo is `default` shows its name as text. The BFF serves no file for `default`.
- `Brand` takes the product's name as a prop: it is the page's own, never the kit's.
- Sizing and the choice between a deployment's two logos are CSS in `base.css`, by the attribute `data-brand-logo` on the mark: `default`, `light`, `dark`, `plain` (one logo for both modes), `name` (no logo). The mode that decides is the document's `data-theme`.
- The header lets the product name wrap beside the account control on narrow screens, including with wider system fonts and increased text spacing. The theme owns the gap; `base.css` handles Astryx 0.6.3's heading internals, which have no theme targets.

## Which version runs

- `VersionInfo` shows the release, the commit's first seven characters and when the image was built (in the reader's time), each "Okänd" when the BFF does not know it; a button that copies the support details (the product's name, each value whole, the page's address); and, when the repository is known, the release's and the commit's pages on GitHub, in a new tab.
- The module has no version of its own: the UI and the BFF ship as one image, and `/api/healthz` says what the image was built from and the release the deployment names ([configuration](configuration.md#which-build-runs)). A local build says nothing of itself.
- It reads the answer when it is shown, with a deadline of 10 s; a failed read says so and offers "Försök igen". Put it where a person opens it, not on every page: the template's account menu has "Version", which opens it in a dialog (`template/web/src/AccountMenu.tsx`).

## Pages and navigation

The package imports no router: the module's router gives `RouteEffects` the path (`useLocation().pathname`), the history entry's key (`useLocation().key`) and how it was reached (`useNavigationType()`), as the template's `Root` does.

- **The title** of the route (the template's `handle.title`, `<page> · <product>`) is set at once, in a layout effect. A page that names itself more closely does so in an effect, which runs after it, and has the last word.
- **The rest waits for the page's content**: a page calls `useRouteReady(ready)` once it has its first real content (the list answered), not a spinner. In the next frame, once: the title is said through Astryx's live region; the focus goes to the page's heading (`[data-phase-heading]`, an `h1` with `tabindex`, else the first `h1` of the main region, made focusable with `tabindex="-1"`) when it is on no element, unless the person pressed a key or the pointer since and put the focus somewhere the page did not remove; and the window scrolls to the top for a link, or to where the person left the entry for Back and Forward. Set `history.scrollRestoration = "manual"`: this is the one place that scrolls after a navigation.
- Only a new path is a navigation: a page that writes `?run=` into the address changes its own state. The first load, and the redirect the first page sends the person on by before any page has its content, do none of it.
- `SignInScreen`, `SignedInAgain` and the stand-in pages are ready at once. `RequireSession`'s waiting view is not.
- `NotFoundPage` says "Sidan finns inte." at the address as it was typed, with "Till startsidan" (`homeHref`, default `/`); route it at `*`. `ErrorPage` is the router's error boundary: "Sidan kunde inte visas.", that the module may have been updated since the page was opened, "Ladda om sidan" and "Till startsidan"; the error goes to the console. It covers a page whose code cannot be fetched (a tab that was open across a release asks for files that are gone) and a page that threw. Nothing reloads by itself: a person may be in the middle of something, and a reload is theirs to choose. Both set their own title (`Sidan finns inte · <product>`), in the column of the sign-in screen.

## Leaving a page

`useLeaveQuestion(active, warning)` is for a page that holds work that leaving would lose (`active`). It imports no router; the template's `web/src/leave.ts` (`useLeaveGuard`) gives it React Router's blocker.

- While `active`, the browser's own question (`beforeunload`) covers what no navigation of the app reaches: a reload, a closed tab, another site.
- `leaveFirst(goOn, stay?)` asks in the page's own dialog, "Lämna sidan?" with `warning`, "Stanna kvar" (which has the focus) and "Lämna sidan": before an action that ends the work without a navigation (the template's account menu signs out through it), and for a navigation the router held (`leaveFirst(blocker.proceed, blocker.reset)`). Not `active`, it goes on at once.
- `holds()` says, when the router asks, whether a navigation must be held: `useBlocker(({ currentLocation, nextLocation }) => leaving.holds() && currentLocation.pathname !== nextLocation.pathname)`, so a page that writes `?run=` into its address is not held.
- An answered "Lämna sidan" lets its own way off through: neither the browser nor the router asks again while it goes on, and the hold is back if it did not leave (a sign-out that failed).
- Render `question` once on the page. It is a native modal dialog, not closed while the login has ended: asked while signed out, it stands above the sign-in dialog.

## Drafts

`createDrafts(prefix)` keeps what someone has typed but not sent, so a reload after a lost login, or a tab the browser put to sleep, gives it back. Create one per module (`createDrafts("min-modul")`) and share it.

- Per person, in the tab's `sessionStorage` under `<prefix>:<user id>:<name>`, not `localStorage`: a shared computer keeps nothing of it once the tab is closed. `read(ownerId, name, isDraft)`, `write(ownerId, name, value)` (JSON), `clear(ownerId, name)` once it is sent, saved or thrown away.
- Only to the same person: call `keepOnly(user.id)` from `RequireSession`'s `onIdentity`, which removes every other person's drafts under the prefix.
- `read` takes the reader's own check of the shape (`isDraft`): what an earlier page wrote may be of an older shape. A draft that fails it, or is not JSON, is removed and counts as none.
- A write the storage refuses (full, blocked) returns `false`, and `unstored()` says that typed work is kept nowhere but the page until it is stored, cleared or the page is gone (`forget()`): that is when leaving should ask first (`subscribe` for a re-render). Storage that is missing or throws is no error.

## Online status

- Two causes, told apart: the browser's `offline` event says the device has no network (`offline`); a request that did not reach the module while the browser says it has one says the module does not answer (`unreachable`). A request that reaches the module, an error status included, or the browser's `online` event, clears it. An answer to a request that left after the browser said "offline" outweighs it (Safari can go on saying so after a device wakes); one that was already on its way does not.
- The session client's requests report it: `fetchWithSession` and the status reads of `RequireSession`. The page's own abort says nothing.
- `OfflineBanner` says "Ingen anslutning." or "<productName> svarar inte just nu.", and after it the page's `message` (what waits, and when it goes on). It is Astryx's warning banner, an alert mounted when the connection goes, so a screen reader says it once; online it is nothing and takes no room. The template's `Frame` puts it in the shell's `banner`, above the bar.

## The shell

- A page renders no `<main>` and no skip link: `ModuleShell` has them.
- Cap a page's content with Astryx's `Layout contentWidth`: a stack stretches its children to the window's whole width.
- A page that must not be left (a recording, a sending) passes less in `end` and `heading`; the shell decides nothing.
- The bar scrolls away with the page (`base.css`): stuck to the top it would hide a focused control (WCAG 2.4.11).

## The session client

`@eneo-ai/module-kit/session` keeps the login of a page that can outlive its login. SSO only: it uses the BFF's `GET /api/auth/status`, `GET /api/auth/login?next=&renew=` and the `X-Auth-Required: session` mark on a 401 ([design.md](../design.md) section 5). A page's whole use of it, from the template's `web/src/App.tsx`: the route a login window ends at, and the pages that need a session under one layout route that is the gate:

```tsx
{ path: "inloggad", element: <SignedInAgain productName={PRODUCT_NAME} /> },   // where a login window ends
{
  Component: Private,    // <RequireSession productName={PRODUCT_NAME} signInTitle={PRODUCT_NAME} …><Outlet /></RequireSession>
  children: [{ path: "flows", lazy: page(async () => (await import("./pages/Flows")).Flows) }],
},
```

and every call to the backend through `fetchWithSession(path, init)` instead of `fetch` (the template's `getJson` in `web/src/session.ts`).

| Export | What it is |
|---|---|
| `RequireSession` | The gate. Signed out: the sign-in screen (`signIn` replaces it; `navigate` with `signInPath` sends the person to a route of the app's own). Signed in: `children`, the keepalive (the backend's `refresh_in`), a status read when the page is seen and when a login window says it is done, the warning five minutes before the end, and, when the login has ended, the cover and the sign-in dialog. `onIdentity(user)` is awaited before `children` are shown. `signedOutControls` and `signedOutNote` are for what stays reachable while signed out. |
| `useSessionUser()`, `useSignedOut()`, `useSignedOutSlot()` | The user; whether the login has ended; the place in the sign-in dialog to portal what must stay reachable into. |
| `fetchWithSession(path, init)` | `fetch` over the page's one session state. Signed out, nothing but `/api/auth/*` leaves the page: a GET or HEAD, or a request with an `Idempotency-Key`, waits for the new login and is sent once more; any other fails with `SessionExpiredError`. A write names the page's user in `X-Expected-User`; a 409 `user_changed` (someone else's session under the page) ends the login as a 401 does, reads the status again so that the cover says whom to sign in as, and fails with `SessionExpiredError`, never sent again. A request no answer has begun for within 90 s fails with `RequestTimeoutError`. Answers are returned as they came. |
| `RequestTimeoutError` | What `fetchWithSession` fails with when no answer has begun within 90 s (the backend waits 60 s for Eneo): `status` 408, and a Swedish `message` to show beside a way to try again. The page's own `signal` still aborts a request, as an abort. |
| `errorAdvice(error)`, `ErrorAdvice` | What a failed request says to the person: `{ message, retry }`, a Swedish sentence with the way on and whether trying again can help (offer "Försök igen" only then). It reads `SessionExpiredError` (try again: the new login is there by now), `RequestTimeoutError`, a dropped connection (a `TypeError` from `fetch`), and an error that carries the status the backend answered (`{ status }`: the module's own error class, or a `Response`): 401, 403, 404, 408, 413, 415, 429, 502, 503, 504, other 5xx and 4xx. Anything else is "Ett okänt fel uppstod. Försök igen." What the browser or the backend said in English is never shown. The template's flow list uses it. |
| `SignInScreen`, `SignedInAgain` | The sign-in screen (one button that starts Eneo's login; it says once when a callback failed, `?auth_error=`); the page a login in a window of its own lands on: it tells the module's tabs (`SESSION_CHANNEL`, `"eneo-module:session"`) and closes itself, or says why a renewal was refused (`?fel=annan-anvandare`, `?fel=utgangen`). Route it at `signedInAgainPath` (default `/inloggad`). |
| `createSessionState()`, `sessionState`, `createFetchWithSession(state)`, `SessionExpiredError`, `isSessionEndedAnswer`, `refusalOf`, `sessionUser`, `userDisplayName`, `userInitial` | The state (one per page, shared by the gate and `fetchWithSession`), for tests and for a transport that is not `fetch`; the error; the helpers. The package README lists them. For a transport that is not `fetch` (an upload by `XMLHttpRequest`): refuse while `sessionState.signedOut`, take `const question = sessionState.ask()` before sending, and on a 401 with `X-Auth-Required: session` (`isSessionEndedAnswer`) call `sessionState.ended(question)`. A refusal that arrives after a renewal belongs to the old login: `ended(question)` returns false and covers nothing. On a write send `X-Expected-User: sessionState.expectedUser`, and on a 409 `{"detail": "user_changed"}` call `sessionState.userChanged(question)`. |

When the login has ended the page is covered, not removed: it stays mounted with all it holds, hidden and out of reach (`inert`), under a native modal dialog with an opaque backdrop that nothing but the new login closes, opened in a window of its own. Only the page's own user signing in again lifts it; someone else's login keeps the page covered and says whom to sign in as. A native dialog of the page is the module's to close while signed out (`isOpen={open && !useSignedOut()}`): see [build a module](build-a-module.md#10-sessions-and-dialogs) and the [security checklist](security-checklist.md#the-cover-for-an-ended-login). The decision: [K15](../decisions/k15-cover-for-an-ended-login.md). The flow: [architecture](../architecture.md#how-a-page-learns-the-login-ended-and-gets-it-back). The Swedish words are in `packages/ui/src/session/messages.ts`.

## Fix a shortfall once

A design-system shortfall (a target under 44 px, a missing focus ring, a label that cannot be read in dark mode) is fixed once, in `packages/ui/src/theme/eneo.theme.ts`, then `npm run theme:build` in `packages/ui`, and the regenerated `src/theme/built/` is committed. Astryx is pinned to an exact version in the package and in the template ([K11](../decisions/k11-astryx-pinned.md)); an upgrade is its own change. No ejected Astryx component and no authored StyleX.

The shared theme gives fields one focus frame along their rounded edge, keeps supporting text at 14 px with the default root font size, and supplies error-text and control-edge colours that meet AA on the page, card and muted surface. An off switch's track is the control-edge colour (3:1 on the page and under its thumb), a text area is 44 px under a finger, a table that scrolls sideways shows shadows at the edge that has more and its header cells wrap, and a heading that wraps balances its lines. A dialog initially focuses its heading for announcement without drawing a control frame around it; its keyboard controls retain visible focus. Token contrast checks live in `packages/ui/tests/contrast.test.ts`, and the template's `theme.spec.ts` verifies these rendered states.

## Develop the package

From the repository root:

```bash
npm ci
npm run -w packages/ui lint       # tsc --noEmit
npm test -w packages/ui           # node:test with jsdom
npm run -w packages/ui build      # tsc to dist/, the stylesheets beside it, and a check that dist/index.js loads with its names
npm run -w packages/ui theme:build && git diff --exit-code -- packages/ui/src/theme/built    # what CI's `ui` job also runs
```

Tests are in `packages/ui/tests/`, one file per concern: colour mode, providers, which links are the router's (`links`), navigation and the stand-in pages under React Router's data router (`route-effects`), online status and its banner (`online-status`), drafts (`drafts`), the leave question with React Router's blocker (`leave-question`), waiting (`waiting`: `LoadingShell`, `SlowWait`), code fetched when needed (`lazy`), shell, branding, theme, the session client (`session-gate`, `session-state`, `session-keepalive`, `session-user`), what a failed request says (`errors`), the README's link example, and the package itself (no router import, no CSS import from code, exact pins, every export is built).
