# @eneo-ai/module-kit

Purpose: the UI of an Eneo module: the Eneo theme for Astryx, colour mode, providers, page shell and brand.
Read this when: you build a module's pages on it, or change the package.
Related: [guide: the UI package](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/ui-package.md) (install, wiring, every name, colour mode, links, branding), [new module](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/new-module.md), [architecture](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/architecture.md#the-ui-app-and-its-layers), [decisions K9, K10, K11](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/decisions/README.md), [BFF README](https://github.com/eneo-ai/eneo-module-kit/blob/main/packages/bff/README.md).

The UI of an Eneo module, for a static Vite + React app: the Eneo theme for [Astryx](https://astryx.atmeta.com), the
colour mode, the providers a page needs, the page shell and the brand lockup. It imports nothing from a router or a
meta-framework. Version 0.x: the API may change until a second module has used it.

```tsx
// main.tsx
import "@eneo-ai/module-kit/layers.css"; // first: the order of the cascade layers
import "@astryxdesign/core/reset.css";
import "@astryxdesign/core/astryx.css";
import "@eneo-ai/module-kit/theme.css";
import "@eneo-ai/module-kit/base.css";
import { Link } from "react-router"; // the app's own router, if it has one
import { BrandingProvider, ModuleProviders } from "@eneo-ai/module-kit";

// the root route's component: inside the router, around every page
<ModuleProviders linkComponent={Link}>
  <BrandingProvider defaultLogo="/brand/logo.svg">
    <RouteEffects path={pathname} entry={key} type={navigationType} title={routeTitle}>
      <Outlet />
    </RouteEffects>
  </BrandingProvider>
</ModuleProviders>

// a page
<ModuleShell label="Min modul" heading={<Brand productName="Min modul" href="/" />} end={<AccountMenu />}>
  …
</ModuleShell>
```

`linkComponent` is given the props of an anchor, `href` first: the design system's links (a link button, the brand's
heading) call it with `href`, `children` and the usual anchor attributes, and with `to`, the same address, which Astryx adds
for routers that take their address as `to` (`useLinkComponent`, Astryx 0.6.3). So React Router's `Link` is passed as it is,
and a component that takes `href` needs nothing more. A router whose link wants something else needs a small adapter of its own.
Only a link to a page of the app by its absolute path (`/flows`), opened in the same tab, goes to it: a relative address
(`flows`, `?run=1`), one under `/api` (a file, the login), to another origin, with a `target` other than `_self` or with
`download` stays a plain anchor, so the router never takes a file for a page. Write links to the module's pages as absolute paths.

| Export | What it is |
|---|---|
| `ModuleProviders` | Colour mode, the built Eneo theme, Astryx's words in Swedish, the place its toasts (`useToast`) appear, and (with `linkComponent`) the app's link component, taking `href`, for Astryx's links to a page of the app; every other link stays a plain anchor. |
| `ColorModeProvider`, `useColorMode()`, `readStoredColorMode()` | The mode is `localStorage["theme"]` (`light`, `dark`, `system`; the key and values next-themes used), read before the first render and written back by `setMode`. `useColorMode()` returns `{ mode, resolved, setMode }`. No inline script and no cookie; a module's first-paint script (the template's `public/color-mode.js`) applies the same key before the page's code runs. A switch marks `<html>` with `data-theme-switching` for the frames that apply it. |
| `ModuleShell` | The page frame: top bar, skip link, one `role="main"` region. A page renders no `<main>` of its own. |
| `BrandingProvider`, `Brand` | The organisation beside the product's name, from `GET /api/branding`, asked once. Until it answers (or when it fails) the lockup is the product name alone. `defaultLogo` is the module's own copy of the bundled logo. |
| `VersionInfo` | Which build runs, from `GET /api/healthz`, read when shown: the release, the commit and the build time ("Okänd" when not known), a button that copies them as support details, and the release's and commit's pages when the repository is known. |
| `CopyButton` | Copies a text; a check and "Kopierat" to a screen reader confirm it, and a failure says so in words. |
| `eneoTheme` | The built theme object, for `<Theme>` outside `ModuleProviders`. |
| `LoadingShell`, `SlowWait` | The page while it waits (the bar and a spinner that shows only after 300 ms), and, beside a wait with no end in sight, after 15 seconds "Det tar längre tid än vanligt." with "Försök igen" (`onRetry`) and the page's other ways on. |
| `lazyLoader()`, `useLoaded()`, `LoadFailure` | Code fetched when a page first needs it, once and kept; a failed fetch is kept too (a browser will not fetch it again), and `LoadFailure` offers the person's own reload, "Ladda om sidan". |
| `RouteEffects`, `useRouteReady()` | What a navigation gives the person, router-free: the route's title at once; once the page says it has its content, its title said, the focus on its heading and the scroll (the top for a link, where the person left it for Back). |
| `NotFoundPage`, `ErrorPage` | The pages that stand in for one that cannot be shown: "Sidan finns inte." (route it at `*`), and the router's error boundary, "Sidan kunde inte visas." with "Ladda om sidan" (a page whose code is gone after a release, or that threw). |
| `useLeaveQuestion(active, warning, isActive?)` | Leaving a page that holds work asks first: the browser's own question for a reload or a closed tab, and "Lämna sidan?" in the page (`question`) before an action that ends the work or a navigation the app's router held (`leaveFirst`, `holds`). `isActive` is read when they ask, so a handler that stores the work and leaves at once is let through. Router-free. |
| `createDrafts(prefix)` | What someone has typed but not sent, kept per person in the tab's `sessionStorage` (`read`, `write`, `clear`), only for the same person (`keepOnly(user.id)` from `onIdentity`), and whether something could not be kept (`unstored()`), for a leave question. |
| `OfflineBanner`, `useConnection()`, `onlineStatus`, `createOnlineStatus()` | Whether the page reaches the module: the browser's online events and the session client's requests decide it, telling a device without a network (`offline`) from a module that does not answer (`unreachable`). `OfflineBanner({ productName, message? })` says so above the shell's bar (`banner`): "Ingen anslutning." or "<productName> svarar inte just nu.", then the page's `message`. |

Stylesheets: `layers.css`, `theme.css` (generated from `src/theme/eneo.theme.ts` by `npm run theme:build`, committed in
`src/theme/built/`, and checked for freshness in CI) and `base.css` (what the theme cannot say: the shell's bar, the
brand's mark, no transition while the colour mode switches, the text size set in iOS, reduced motion, a wait's spinner held back for 300 ms, forced-colour edges, no ring on a programmatically focused heading, the session cover that hides the
page while the login has ended, and a menu's height past Astryx's 300 px cap, up to the window below the top bar).

A design-system shortfall is fixed once, in `src/theme/eneo.theme.ts`, then `npm run theme:build`. Astryx is pinned to an
exact version, here and in the peers.

Install it from a packed tarball, not a `file:` folder (two copies of React): see the [guide](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/ui-package.md#install).

## Astryx integration

The installed package contributes `eneo-module-page` and `eneo-signin` reference TSX templates, the `eneo-module` documentation topic and eight agent guidance lines. Read or materialize them with the pinned CLI; the module owns their routing, data and states. Commands and package discovery: [UI guide](https://github.com/eneo-ai/eneo-module-kit/blob/main/docs/guides/ui-package.md#astryx-integration).

## The session client: `@eneo-ai/module-kit/session`

The login of a page that can outlive its login. SSO only: it talks to the BFF's `GET /api/auth/status`
(`{authenticated, user, session_ends_in, refresh_in}`), `GET /api/auth/login?next=&renew=`, the
`X-Auth-Required: session` mark on a 401, and the 409 `user_changed` of a write that names its user (`X-Expected-User`).

```tsx
<RequireSession
  productName="Min modul"
  signInTitle="Logga in i modulen"
>
  <Outlet />   {/* the pages that need a session; and a route at /inloggad that renders <SignedInAgain productName="Min modul" /> */}
</RequireSession>

const response = await fetchWithSession("/api/eneo/flows/");
```

For module-owned state, `onIdentity(user)` is awaited before children are shown. `signedOutControls` and
`signedOutNote` let a module keep selected actions reachable and explain what happens to its work while signed out.
The module owns which state to keep or remove when the identity changes.

| Export | What it is |
|---|---|
| `RequireSession` | The gate. Signed out: the sign-in screen (`signIn` replaces it; `navigate` with `signInPath` sends the person to a route of the app's own). Signed in: `children`, the keepalive (the backend's `refresh_in`), a status read when the page is seen and when a login window says it is done, the warning five minutes before the end, and, when the login has ended, the cover and the sign-in dialog. |
| `useSessionUser()`, `useSignedOut()`, `useSignedOutSlot()` | The user; whether the login has ended; the place in the sign-in dialog to portal what must stay reachable (module-owned actions) into. |
| `fetchWithSession(path, init)` | `fetch` over the page's one session state. Signed out, nothing but `/api/auth/*` leaves the page: a GET or HEAD, or a request with an `Idempotency-Key`, waits for the new login and is sent once more; any other fails with `SessionExpiredError`. A write names the page's user in `X-Expected-User`; a 409 `user_changed` (someone else's session under the page) ends the login as a 401 does, reads the status again so that the cover says whom to sign in as, and fails with `SessionExpiredError`, never sent again. A request no answer has begun for within 90 s fails with `RequestTimeoutError`. Answers are returned as they came. |
| `createSessionState()`, `sessionState`, `createFetchWithSession(state)`, `createUploadWithProgress(state)` | The state (one instance per page, shared by the gate, `fetchWithSession` and `uploadWithProgress`), and a way to build them over another one (tests). |
| `RequestTimeoutError` | What `fetchWithSession` fails with when no answer has begun within 90 s (the backend waits 60 s for Eneo): `status` 408, and a Swedish `message` to show beside a way to try again. The page's own `signal` still aborts a request, as an abort. |
| `uploadWithProgress(path, body, options)` | An upload that says how far it has come (`onProgress({ loaded, total })`; XMLHttpRequest, as `fetch` cannot tell), under `fetchWithSession`'s rules and with its errors. Signed out it fails with `SessionExpiredError` and nothing leaves the page: an upload is never sent twice. It names the page's user in `X-Expected-User`; a 401 with `X-Auth-Required: session` and a 409 `user_changed` end the login. Nothing going up for `idleTimeoutMs`, or no answer begun within `answerTimeoutMs` of the last byte (90 s each unless said; the backend is told the second, `X-Upload-Timeout-Seconds`, so it waits for Eneo no longer), fails with `RequestTimeoutError`; not reaching the module, with a `TypeError`. `method` (`POST`), `headers` and `signal` as for `fetch`. The answer is a `Response`. |
| `errorAdvice(error)` | What a failed request says to the person: `{ message, retry }`, a Swedish sentence and whether "Försök igen" can help, for `SessionExpiredError`, `RequestTimeoutError`, a dropped connection and an error that carries the backend's `status`. No English reaches the page. |
| `SessionExpiredError`, `isSessionEndedAnswer(status, header)` | What a request the login's end refused fails with (`status` 401); whether an answer is the backend's mark that the login ended (a 401 with `X-Auth-Required: session`), not Eneo's own 401. |
| `SignInScreen`, `SignedInAgain`, `refusalOf`, `SESSION_CHANNEL` | The sign-in screen; the page the login window lands on (it tells the module's tabs through `SESSION_CHANNEL` and closes itself, or says why a renewal was refused: `?fel=annan-anvandare`, `?fel=utgangen`); route it at `signedInAgainPath` (default `/inloggad`). |
| `sessionUser`, `userDisplayName`, `userInitial` | The identity of a status; the name and the initial an account menu shows. |

What the cover promises, proved in a browser (Chromium and Firefox; WebKit with the exception below): while the login has
ended the page stays mounted with all it holds, hidden and out of reach (`inert`, and out of the accessibility tree),
under a native modal dialog with an opaque backdrop that nothing but the new login closes (not Escape, not a click beside
it; opened as a modal again if something closes it); only the page's own user signing in again lifts it (someone else's
login says so, and whom to sign in as); a screen of 320 x 200 scrolls the dialog as a whole; the focus goes back to where it
was.

**A native dialog of the page is the module's to close while signed out**: `isOpen={open && !useSignedOut()}`, with its state
above the dialog, so it is back as it was after the new login. A native dialog escapes an inert ancestor; the opaque
backdrop hides one that is left open, but in WebKit a dialog left open stays reachable by Tab. Render page dialogs in place,
inside the children of `RequireSession`: one portalled to `body` is outside the cover and stays in the accessibility tree.

Not in the package: anything about recordings, a second login mode. The leave question (`useLeaveQuestion`, in the main
export) is a native `AlertDialog` opened after the sign-in dialog, so it stacks above it while signed out. The Swedish words are in
`src/session/messages.ts`; the module's own sentence is `signedOutNote`.

## Node

Two different things, kept apart:

- **Using the package** (a module's build): Node `>=22.13.0`, the Astryx CLI's own minimum (`package.json` `engines`). The
  package is browser code and needs no Node at run time.
- **Developing the package** (this repository: `npm ci`, the tests, the build): Node `^22.22.2 || ^24.15.0 || >=26.0.0`, the
  root `package.json`'s `engines`. It is what the locked development tools require together (jsdom 30 and its dependencies
  need 22.22.2 or 24.15), checked by `npm ci --engine-strict` on 22.13.0 (refused) and 22.22.2 (installs; lint, tests and build
  pass), and by a test that fails when a bumped dependency asks for more.
