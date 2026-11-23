import { useEffect, useState, type ReactNode } from "react";
import { AppShell } from "@astryxdesign/core/AppShell";
import { Heading } from "@astryxdesign/core/Heading";
import { Layout, LayoutContent } from "@astryxdesign/core/Layout";
import { Text } from "@astryxdesign/core/Text";
import { VStack } from "@astryxdesign/core/VStack";
import { useRouteReady } from "../routes.js";
import { messages, wrongUserText } from "./messages.js";
import type { SessionStatus } from "./types.js";
import { userDisplayName } from "./user.js";

/** Where a login that is shared between a module's windows and tabs is announced: every tab of the module listens. */
export const SESSION_CHANNEL = "eneo-module:session";

/** The mark of the sign-in dialog's login window, in that window's sessionStorage of the module's origin. */
const MARK = "eneo-module:login-window";

/**
 * Whether this window is the sign-in dialog's login window: the dialog marked it when it opened it (`openLoginWindow`).
 * A page of the module shown there after a sign-in failed shows the window's failure view (`LoginWindowFailed`), never a
 * sign-in of its own. Not the window's name or opener: a page on the way that sets `Cross-Origin-Opener-Policy` takes
 * both away, and the mark stays. The mark grants nothing; it only chooses a view. Storage that cannot be read: no mark.
 */
export function isLoginWindow(): boolean {
  try {
    return window.sessionStorage.getItem(MARK) === "1";
  } catch {
    return false;
  }
}

function removeMark(): void {
  try {
    window.sessionStorage.removeItem(MARK);
  } catch {
    // Storage that cannot be written: the mark stays as it is.
  }
}

/**
 * Opens the sign-in dialog's login window on `url`, marked. A window opened with an opener starts with a copy of the
 * opener's sessionStorage, so the mark is set here for the moment of the call and taken away after it, whatever the call
 * did; a page that was marked already stays marked. A window that gets no copy
 * (storage refused, an opener the browser drops) is unmarked, and a failed sign-in there meets the module's ordinary
 * handling at `/`. No window name: a name would let the browser reuse a window, which takes no new copy.
 */
export function openLoginWindow(url: string): Window | null {
  // A mark is this call's only when a missing one was written without an error; a read or a write that fails opens the
  // window unmarked and touches nothing.
  let own = false;
  try {
    const storage = window.sessionStorage;
    if (storage.getItem(MARK) === null) {
      storage.setItem(MARK, "1");
      own = true;
    }
  } catch {
    // Storage that cannot be used: the window opens without the mark.
  }
  try {
    return window.open(url, "_blank", "popup,width=520,height=700");
  } finally {
    if (own) removeMark();
  }
}

/** Why the backend refused a renewal (`?fel=`); the page's own login stays as it was. */
export type Refusal = "annan-anvandare" | "utgangen";

/**
 * The refusal an address carries (`?fel=annan-anvandare` or `?fel=utgangen`), or null. The last one it recognises: the
 * backend adds its own after the query of the return address, which may carry a `fel` of its own.
 */
export function refusalOf(search: string): Refusal | null {
  const refusals = new URLSearchParams(search).getAll("fel").filter((fel): fel is Refusal => fel === "annan-anvandare" || fel === "utgangen");
  return refusals.at(-1) ?? null;
}

const TITLE: Record<Refusal | "ok", string> = {
  ok: messages.signedInAgainTitle,
  "annan-anvandare": messages.wrongUserTitle,
  utgangen: messages.endedAlreadyTitle,
};

/**
 * Where the login window the sign-in dialog opens lands: it tells the module's tabs, which read the new end, and closes
 * itself. A refused renewal says why and stays: `annan-anvandare` when it signed in someone else, `utgangen` when the
 * login had already ended, so there was no user left to renew. The backend's refusal in the address decides; `refusal`
 * counts only where the address has none, so a refusal is never announced as a login. A failed sign-in lands on the
 * backend's own failure address, `/?auth_error=`: there this page is the failure view, marked or not, also where the
 * window's page is `/`. A popup window: no top bar and no account menu, so the page's own main region and one readable
 * column. Route it at the `signedInAgainPath` that `RequireSession` is given, outside the gate.
 */
export function SignedInAgain({ productName, refusal = null }: { productName: string; refusal?: Refusal | null }) {
  const failed = window.location.pathname === "/" && new URLSearchParams(window.location.search).has("auth_error");
  if (failed) return <LoginWindowFailed productName={productName} />;
  return <Done productName={productName} refusal={refusalOf(window.location.search) ?? refusal} />;
}

function Done({ productName, refusal }: { productName: string; refusal: Refusal | null }) {
  const [name, setName] = useState<string | null>(null);
  useRouteReady(true);

  useEffect(() => {
    document.title = `${TITLE[refusal ?? "ok"]} · ${productName}`;
  }, [refusal, productName]);

  useEffect(() => {
    if (refusal === "annan-anvandare") {
      // The page's own login is still the one in the cookie: its user is the one to sign in as.
      fetch("/api/auth/status", { credentials: "include" })
        .then((res) => res.json() as Promise<SessionStatus>)
        .then((s) => s.user && setName(userDisplayName(s.user)), () => undefined);
      return;
    }
    if (refusal) return;
    // Signed in: no longer a login window, should it stay open.
    removeMark();
    if (typeof BroadcastChannel !== "undefined") {
      const channel = new BroadcastChannel(SESSION_CHANNEL);
      channel.postMessage("signed-in");
      channel.close();
    }
    window.close();
  }, [refusal]);

  return (
    <WindowPage title={TITLE[refusal ?? "ok"]}>
      {refusal === "annan-anvandare" ? wrongUserText(name) : refusal === "utgangen" ? messages.endedAlreadyHint : messages.signedInAgainHint}
    </WindowPage>
  );
}

/**
 * The window's own page: a heading and a line, drawn on the theme's surface to the window's edges in either colour mode.
 * Without it the accessibility check failed the contrast of the failure view's heading and line in dark mode.
 */
function WindowPage({ title, children }: { title: string; children: ReactNode }) {
  return (
    <AppShell height="auto" variant="surface" mobileNav={false} contentPadding={0}>
      <Layout height="auto" contentWidth={640}>
        <LayoutContent padding={6} isScrollable={false}>
          <VStack gap={3} hAlign="start">
            <Heading level={1}>{title}</Heading>
            <Text as="p" color="secondary">
              {children}
            </Text>
          </VStack>
        </LayoutContent>
      </Layout>
    </AppShell>
  );
}

/**
 * A login window whose sign-in failed: it says so and stays. It tells no tab that anyone signed in and offers no sign-in
 * of its own; the page that opened it still has its own way to sign in. With `?auth_error=invalid_state` (the sign-in
 * took too long, or its start was gone) it says that first; no code is shown. A module's own sign-in screen shows this in
 * a login window (`isLoginWindow()`), as `SignInScreen` does.
 */
export function LoginWindowFailed({ productName }: { productName: string }) {
  const late = new URLSearchParams(window.location.search).get("auth_error") === "invalid_state";
  useRouteReady(true);

  useEffect(() => {
    document.title = `${messages.windowFailedTitle} · ${productName}`;
  }, [productName]);

  return <WindowPage title={messages.windowFailedTitle}>{late ? `${messages.signInLate} ${messages.windowFailedHint}` : messages.windowFailedHint}</WindowPage>;
}
