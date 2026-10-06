import { useEffect, useRef, useState, type ReactNode } from "react";
import type { SessionState } from "./state.js";

/**
 * While the login has ended the page stays mounted, so nothing on it is lost and a recording goes on, but it is
 * neither shown nor within reach until the new login: `inert` takes it out of the focus order and the accessibility
 * tree, and base.css hides it. A native dialog of the page escapes an inert ancestor, so the module closes its page
 * dialogs while `useSignedOut()` says so; what one had open is hidden by the sign-in dialog's opaque backdrop.
 */
export function SignedOutCover({
  signedOut,
  focusBack,
  state,
  children,
}: {
  signedOut: boolean;
  /** Set here: gives the focus back once the sign-in dialog has closed after a new login. */
  focusBack?: { current: ((before: HTMLElement | null) => void) | null };
  /** The session state, to see where the focus was at the moment the login ended. */
  state?: SessionState;
  children: ReactNode;
}) {
  const [container, setContainer] = useState<HTMLElement | null>(null);
  // Where on the page the focus was when the login ended, taken before the cover's inert moves it away.
  const lost = useRef<{ from: HTMLElement | null } | null>(null);
  useEffect(
    () =>
      state?.subscribe(() => {
        if (!state.signedOut || lost.current) return;
        const active = document.activeElement;
        lost.current = { from: active instanceof HTMLElement && container?.contains(active) ? active : null };
      }),
    [container, state],
  );
  // Back where it was on the page when the login ended, or before the warning that was open then (`before`), or on
  // the page's heading when neither is on the page any more.
  if (focusBack) {
    focusBack.current = (before) => {
      const from = lost.current?.from ?? null;
      lost.current = null;
      const onPage = (element: HTMLElement | null) => !!element?.isConnected && !!container?.contains(element);
      const heading = container?.querySelector<HTMLElement>("[data-phase-heading], h1[tabindex]") ?? null;
      (onPage(from) ? from : onPage(before) ? before : heading)?.focus();
    };
  }
  return (
    <div ref={setContainer} className="eneo-session-cover" data-signed-out={signedOut ? "" : undefined} inert={signedOut}>
      {children}
    </div>
  );
}
