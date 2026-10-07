# K15. The cover for an ended login is a native modal dialog

Purpose: record the decision that a page whose login has ended stays mounted under a native modal dialog.
Read this when: you change what the page shows when the login ends, `RequireSession`, the sign-in dialog, or how a module's own dialogs behave then.
Related: [decisions](README.md), [UI package: the session client](../guides/ui-package.md#the-session-client), [security checklist](../guides/security-checklist.md#the-cover-for-an-ended-login), [architecture](../architecture.md#how-a-page-learns-the-login-ended-and-gets-it-back), [K4](k04-static-ui-served-by-the-bff.md).

Status: Accepted, 2026-10-01. Built: `packages/ui/src/session/` and the cover rules in `packages/ui/src/base.css`.

## Context

A login ends at a fixed time that only a new login can move, and a page can be open when it does: someone is typing, a dialog is open, a recording may be running in the browser. Sending the person to a sign-in page would unmount all of that.

## Decision

The page stays mounted, `inert` and hidden (`packages/ui/src/base.css`), under a native modal dialog with an opaque backdrop. Only the new login of the page's own user closes it: not Escape, not a click beside it. If something closes the dialog anyway, it is opened as a modal again. The dialog is mounted only while it is shown. The login is made in a window of its own (`/inloggad` is where it ends), so the page itself never navigates. Someone else's login keeps the page covered and says whom to sign in as.

The alternative was to unmount the page and navigate to a sign-in page. A recording in the browser would be lost, and so would typed work and open dialogs. The page must go on.

## Consequences

- A native dialog of a page sits in the browser's top layer and escapes an inert ancestor, so the module closes its own dialogs while signed out: `isOpen={open && !useSignedOut()}`, with its state above the dialog. This is a contract of the module, written in the [security checklist](../guides/security-checklist.md#the-cover-for-an-ended-login).
- In WebKit a dialog left open stays reachable by Tab behind the backdrop; the module's own check is the protection there.
- Page dialogs are rendered in place, inside the children of `RequireSession`: one portalled to `body` is outside the cover.
- Proof: `packages/ui/tests/session-gate.test.ts` and `template/web/tests/e2e/session-cover.spec.ts`.
