# K20. The login window knows itself by a mark in its own tab

Purpose: record how the sign-in dialog's login window tells itself from an ordinary tab, and what it shows when the sign-in in it fails.
Read this when: you change the login window (`SignedInAgain`, the sign-in dialog's button), the page on `/` (where a failed callback lands), or what a failed callback shows.
Related: [decisions](README.md), [K15](k15-cover-for-an-ended-login.md), [UI package: the session client](../guides/ui-package.md#the-session-client), [architecture](../architecture.md#how-a-page-learns-the-login-ended-and-gets-it-back), [security checklist](../guides/security-checklist.md#the-cover-for-an-ended-login).

Status: Accepted, 2026-11-18. Built: `packages/ui/src/session/` (`SignedInAgain.tsx`, `SignInScreen.tsx`, `RequireSession.tsx`, `SessionDialog.tsx`).

## Context

The sign-in dialog ([K15](k15-cover-for-an-ended-login.md)) makes the new login in a window of its own. When the sign-in there fails, the callback sends the window to `/?auth_error=<code>`, and the window showed the module's sign-in screen: a second way in, inside a window that was meant only to sign in and close. A sign-in from there ended in the window, and the page under the cover never heard of it.

## Decision

The dialog marks the window at the moment it opens it. A window opened with an opener starts with a copy of the opener's `sessionStorage` (HTML, "create a new top-level traversable": the opener's storage is cloned; not with `noopener`). So the dialog sets the mark in its own `sessionStorage`, opens the window straight on the login (`/api/auth/login?[renew=1&]next=<signedInAgainPath>`), and removes its own mark again, also when the window is blocked or the call throws; a page that was marked before stays marked. Every press opens a new window without a name, since a window reused by name takes no new copy. Once the new window is open, the dialog closes the one it opened before, if it can still reach it.

In a window with the mark (`isLoginWindow()`):

- where a failure lands (`/?auth_error=<code>`), the kit's `SignInScreen` and `RequireSession` show the failure view, `LoginWindowFailed`: the sign-in could not be finished; close the window and try again from the page. With `invalid_state` it says first that the sign-in took too long or was interrupted. It tells the page nothing, does not close, offers no sign-in, and is the same after a reload.
- `RequireSession` is the failure view and nothing else, whatever the path: it reads no status and shows no sign-in, no dialog and no `children`, whatever `signIn` or `navigate` the module gave. A session that is still live would otherwise show the module's page, or its warning, in the window.
- the window's page (`SignedInAgain`, routed outside the gate) after a completed sign-in removes the mark, tells the module's tabs and closes, as before. A refusal in its address (`fel=`) decides over the `refusal` prop, and the last one it recognises counts: the backend appends its own after the query of the return address (`with_query`, `packages/bff/src/eneo_module_bff/auth.py`). `fel` is the kit's on that page.

The alternatives:

- The window's name or opener, read where the failure lands. A page on the way that sets `Cross-Origin-Opener-Policy` (an identity provider's may) puts the window in a browsing context group of its own, and the browser drops both, seen in Chromium and WebKit; the copied `sessionStorage` stays.
- A start step on the module's page that marks the window and goes on to the login. The kit would build, read and clean an address on a page the module configures, and a start step that fails starts no login at all.
- A flag carried through the BFF to the callback's failure redirect: a new field in the signed state and a change of the callback's contract, for a fact the browser can carry.

## Consequences

- The window's page is routed outside `RequireSession` (required, as the template and the guides have it), on a path of its own with nothing else on it. A module that has it inside the gate sees the failure view after a completed sign-in in the window, and the page is told nothing, until the route moves out; one whose guarded `/` was the window's page gives the window a path of its own outside the gate and sets `signedInAgainPath` to it.
- The backend sends every failed callback to `/?auth_error=<code>`, so whatever is on `/` handles a failure in the login window:
  - the kit's `SignInScreen`: it shows the failure view in the login window itself;
  - a page inside `RequireSession`: the gate shows the failure view;
  - a page of the module's own outside the gate (a public home page, or a sign-in screen of its own): it must show `LoginWindowFailed` while `isLoginWindow()` is true (add the check);
  - the window's page (`SignedInAgain`, where a module's window's page already is `/` outside the gate with its sign-in elsewhere): rendered directly, with no check around it; it tells `/?auth_error=…` from a completed return itself.

  A sign-in screen of the module's own on another path outside the gate needs the same check only if a failure can reach it.
- Where the promise ends:
  - No mark: the copy was not taken, storage is denied, or the backend returns to another origin than the window started on (a module reached under another host name than its public URL). The login still starts, and a failure meets the module's ordinary handling at `/`.
  - No opener when the window is made (a wrapper of `window.open` that adds `noopener` or `noreferrer`): a window can open while `window.open` returns null, so the dialog says the window was blocked although an unmarked one is open.
  - An opener cut later (a page on the way with an opener policy): the copy stays, but the dialog can no longer close that window. After a new press, a reload of the page or with a second tab of the module, two windows can be open. Closing a window does not cancel a callback that has reached the backend.
- A return address the backend does not accept (too long, or not a plain path of the module) is replaced by the home path. When that is `/`, the rules above for what is on `/` decide what a marked window shows: with the kit's `SignInScreen`, a page inside the gate, or a page of the module's own that checks the mark, it is the failure view although the sign-in succeeded. A home path on another page inside `RequireSession` shows the failure view too.
- The window gets a copy of everything in the page's `sessionStorage`, as it did before this change. A duplicated login window copies the mark. The mark lives as long as the window's tab; storage that cannot be written gives no mark.
- The copy is the HTML standard's legacy clone step for a window opened with an opener: specified, and not to be extended. The browser test that proves it (`login-window.spec.ts`) has shown it in Chromium and WebKit. It is also selected for the desktop Firefox project, and the result there comes from CI. Should a browser drop it, a failure meets the module's ordinary handling at `/`, and a flag carried through the backend to the failure redirect would be the way on.
- `auth_error` on `/` is the backend's (its failure redirect): the window's page there (`signedInAgainPath="/"`) shows the failure view, marked or not, and never announces a login. So a module with the window's page on `/` gives an ordinary tab whose sign-in failed the window's advice too (close the window and try again from the page), not a sign-in. On any other path `auth_error` is the module's.
- Whether a window can close itself after a policy page took its opener is the browser's: the browser spec records it and the kit does not promise it.
- Proof: `packages/ui/tests/session-gate.test.ts` for each side alone (jsdom makes no copy), and `template/web/tests/e2e/login-window.spec.ts` through the dialog's own button, in Chromium and WebKit, and selected for desktop Firefox, whose result comes from CI; with the mark not set, its window cases fail at the failure view.
