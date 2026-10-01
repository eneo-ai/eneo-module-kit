# @eneo-ai/module-kit

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

createRoot(document.getElementById("root")!).render(
  <BrowserRouter>
    <ModuleProviders linkComponent={Link}>
      <BrandingProvider defaultLogo="/brand/logo.svg">
        <App />
      </BrandingProvider>
    </ModuleProviders>
  </BrowserRouter>,
);

// a page
<ModuleShell label="Tal till text" heading={<Brand productName="Tal till text" href="/flows" />} end={<AccountMenu />}>
  …
</ModuleShell>
```

`linkComponent` is given the props of an anchor, `href` first: the design system's links (a link button, the brand's
heading) call it with `href`, `children` and the usual anchor attributes, and with `to`, the same address, which Astryx adds
for routers that take their address as `to` (`useLinkComponent`, Astryx 0.6.3). So React Router's `Link` is passed as it is,
and a component that takes `href` needs nothing more. A router whose link wants something else needs a small adapter of its own.

| Export | What it is |
|---|---|
| `ModuleProviders` | Colour mode, the built Eneo theme, Astryx's words in Swedish, and (with `linkComponent`) the app's link component, taking `href`, for Astryx's links. |
| `ColorModeProvider`, `useColorMode()`, `readStoredColorMode()` | The mode is `localStorage["theme"]` (`light`, `dark`, `system`; the key and values next-themes used), read before the first render and written back by `setMode`. `useColorMode()` returns `{ mode, resolved, setMode }`. No inline script and no cookie. |
| `ModuleShell` | The page frame: top bar, skip link, one `role="main"` region. A page renders no `<main>` of its own. |
| `BrandingProvider`, `Brand` | The organisation beside the product's name, from `GET /api/branding`, asked once. Until it answers (or when it fails) the lockup is the product name alone. `defaultLogo` is the module's own copy of the bundled logo. |
| `eneoTheme` | The built theme object, for `<Theme>` outside `ModuleProviders`. |

Stylesheets: `layers.css`, `theme.css` (generated from `src/theme/eneo.theme.ts` by `npm run theme:build`, committed in
`src/theme/built/`, and checked for freshness in CI) and `base.css` (what the theme cannot say: the shell's bar, the
brand's mark, forced-colour edges, no ring on a programmatically focused heading, and the session cover that hides the
page while the login has ended).

A design-system shortfall is fixed once, in `src/theme/eneo.theme.ts`, then `npm run theme:build`. Astryx is pinned to an
exact version, here and in the peers.

## The session client: `@eneo-ai/module-kit/session`

The login of a page that can outlive its login. SSO only: it talks to the BFF's `GET /api/auth/status`
(`{authenticated, user, session_ends_in, refresh_in}`), `GET /api/auth/login?next=&renew=` and the
`X-Auth-Required: session` mark on a 401.

```tsx
<RequireSession
  productName="Tal till text"
  signInTitle="Gör samtal och filer till text"
  onIdentity={(user) => keepOnlyDraftsOf(user.id)}          // awaited before the page is shown
  signedOutControls={<RecordingControls />}                  // stays reachable in the sign-in dialog
  signedOutNote="en inspelning fortsätter och sparas på enheten."
>
  <Routes />   {/* and a route at /inloggad that renders <SignedInAgain productName="Tal till text" /> */}
</RequireSession>

const response = await fetchWithSession("/api/eneo/flows/");   // instead of fetch
```

| Export | What it is |
|---|---|
| `RequireSession` | The gate. Signed out: the sign-in screen (`signIn` replaces it; `navigate` with `signInPath` sends the person to a route of the app's own). Signed in: `children`, the keepalive (the backend's `refresh_in`), a status read when the page is seen and when a login window says it is done, the warning five minutes before the end, and, when the login has ended, the cover and the sign-in dialog. |
| `useSessionUser()`, `useSignedOut()`, `useSignedOutSlot()` | The user; whether the login has ended; the place in the sign-in dialog to portal what must stay reachable (a recording's Pausa and Stoppa) into. |
| `fetchWithSession(path, init)` | `fetch` over the page's one session state. Signed out, nothing but `/api/auth/*` leaves the page: a GET or HEAD, or a request with an `Idempotency-Key`, waits for the new login and is sent once more; any other fails with `SessionExpiredError`. Answers are returned as they came. |
| `createSessionState()`, `sessionState`, `createFetchWithSession(state)` | The state (one instance per page, shared by the gate and `fetchWithSession`), and a way to build both over another one (tests). |
| `SessionExpiredError`, `isSessionEndedAnswer(status, header)` | For a transport that is not `fetch` (an upload by XMLHttpRequest): refuse when `sessionState.signedOut`, call `sessionState.ended()` on a 401 with `X-Auth-Required: session`. |
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

Not in the package: the leave question (a native `AlertDialog` opened after the sign-in dialog stacks above it, so the
module's own works unchanged), anything about recordings or drafts, a second login mode. The Swedish words are in
`src/session/messages.ts`; the module's own sentence is `signedOutNote`.

## Node

Two different things, kept apart:

- **Using the package** (a module's build): Node `>=22.13.0`, the Astryx CLI's own minimum (`package.json` `engines`). The
  package is browser code and needs no Node at run time.
- **Developing the package** (this repository: `npm ci`, the tests, the build): Node `^22.22.2 || ^24.15.0 || >=26.0.0`, the
  root `package.json`'s `engines`. It is what the locked development tools require together (jsdom 30 and its dependencies
  need 22.22.2 or 24.15), checked by `npm ci --engine-strict` on 22.13.0 (refused) and 22.22.2 (installs; lint, tests and build
  pass), and by a test that fails when a bumped dependency asks for more.
