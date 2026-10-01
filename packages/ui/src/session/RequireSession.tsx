import { createContext, useContext, useEffect, useRef, useState, useSyncExternalStore, type ReactNode } from "react";
import { Center } from "@astryxdesign/core/Center";
import { Spinner } from "@astryxdesign/core/Spinner";
import { VisuallyHidden } from "@astryxdesign/core/VisuallyHidden";
import { Brand } from "../branding.js";
import { ModuleShell } from "../ModuleShell.js";
import { keepSessionAlive } from "./keepalive.js";
import { messages } from "./messages.js";
import { SessionDialog } from "./SessionDialog.js";
import { SignedOutCover } from "./SignedOutCover.js";
import { SESSION_CHANNEL } from "./SignedInAgain.js";
import { SignInScreen } from "./SignInScreen.js";
import { sessionState, type SessionState } from "./state.js";
import type { SessionStatus, SessionUser } from "./types.js";
import { sessionUser } from "./user.js";

interface SessionContextValue {
  user: SessionUser;
  state: SessionState;
  /** While the page is covered for a new login: the place in the sign-in dialog for what stays reachable. */
  slot: HTMLElement | null;
}

const SessionContext = createContext<SessionContextValue | null>(null);

/** The signed-in user; throws outside `RequireSession`. */
export function useSessionUser(): SessionUser {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSessionUser must be used inside RequireSession");
  return session.user;
}

/**
 * Whether the page's login has ended. A page dialog that is a native one must be closed meanwhile (`isOpen && !signedOut`):
 * the cover hides and disables the page, but a native dialog in the top layer escapes both. Its state lives above the
 * dialog, so it is back as it was after the new login.
 */
export function useSignedOut(): boolean {
  const state = useContext(SessionContext)?.state ?? sessionState;
  return useSyncExternalStore(state.subscribe, () => state.signedOut, () => false);
}

/**
 * Where the sign-in dialog keeps what must stay reachable while signed out, which needs no login (a recording's Pausa
 * and Stoppa): portal into it (`createPortal(controls, slot)`). Null while signed in.
 */
export function useSignedOutSlot(): HTMLElement | null {
  return useContext(SessionContext)?.slot ?? null;
}

async function readStatus(): Promise<SessionStatus> {
  const res = await fetch("/api/auth/status", { credentials: "include", cache: "no-store" });
  if (!res.ok) throw new Error(`status ${res.status}`);
  return (await res.json()) as SessionStatus;
}

/**
 * The gate of a module's pages. Signed out it shows the sign-in screen; signed in it shows `children` and keeps the
 * login: it asks the backend for the session when the page becomes visible, when a login in a window of its own says
 * it is done, and when the backend wants Eneo's token renewed; it warns five minutes before the end; and when the login
 * has ended it covers the page (kept mounted, hidden and out of reach) with a modal dialog that asks for a new login in
 * place, so nothing on the page is lost. Only the page's own user signing in again lifts it.
 */
export function RequireSession({
  children,
  productName,
  signInTitle,
  signInDescription,
  signIn,
  navigate,
  signInPath = "/",
  signedInAgainPath = "/inloggad",
  onIdentity,
  signedOutControls,
  signedOutNote,
  loading,
  state = sessionState,
}: {
  children: ReactNode;
  /** The module's name, for the bar and the landmark of what the gate shows itself. */
  productName: string;
  /** The default sign-in screen's heading: what the module does. */
  signInTitle?: ReactNode;
  signInDescription?: ReactNode;
  /** Replaces the default sign-in screen. */
  signIn?: ReactNode;
  /** With `signInPath`: where an app with a route of its own for signing in sends the person, in place of the screen. */
  navigate?: (path: string) => void;
  signInPath?: string;
  /** The route of the page that tells the module's tabs a login window is done (`SignedInAgain`). */
  signedInAgainPath?: string;
  /** Called with the signed-in user, and awaited, before `children` are shown (clear what belongs to someone else). */
  onIdentity?: (user: SessionUser) => void | Promise<void>;
  /** Shown in the sign-in dialog while signed out: what stays reachable. */
  signedOutControls?: ReactNode;
  /** What the module promises while signed out, finishing "Allt på den här sidan finns kvar, och …". */
  signedOutNote?: string;
  /** Replaces the loading view. */
  loading?: ReactNode;
  /** For tests; the page's own is shared with `fetchWithSession`. */
  state?: SessionState;
}) {
  const [phase, setPhase] = useState<"loading" | "out" | "failed" | "in">("loading");
  const [user, setUser] = useState<SessionUser | null>(null);
  // When the login ends, and how a new login moves that.
  const [endsAt, setEndsAt] = useState<number | null>(null);
  const [controls, setControls] = useState<HTMLElement | null>(null);
  const focusBack = useRef<((before: HTMLElement | null) => void) | null>(null);
  const onIdentityRef = useRef(onIdentity);
  onIdentityRef.current = onIdentity;
  const signedOut = useSyncExternalStore(state.subscribe, () => state.signedOut, () => false);
  const otherUser = useSyncExternalStore(state.subscribe, () => state.otherUser, () => null);

  useEffect(() => {
    let cancelled = false;
    let stopKeepalive: (() => void) | undefined;
    let channel: BroadcastChannel | null = null;
    let endPage: (() => void) | undefined;

    const observe = (s: SessionStatus) => {
      // Signed in, until when, or signed out: the page asks for a new login in place, never navigates.
      state.observe(s);
      if (s.authenticated && s.session_ends_in !== undefined) {
        const next = Date.now() + s.session_ends_in * 1000;
        // The same end read again moves by the request's second or so; only a new login moves it far.
        setEndsAt((current) => (current !== null && Math.abs(next - current) < 60_000 ? current : next));
      }
    };
    // Answers can come back out of order (a slow check, then a renewal's): only an answer to a later question than the
    // last one used moves the end or the keepalive. A stopped keepalive's answers count the same way.
    let asked = 0;
    let used = 0;
    const read = async (): Promise<SessionStatus | null> => {
      const question = ++asked;
      const s = await readStatus();
      if (cancelled || question <= used) return null;
      used = question;
      observe(s);
      return s;
    };
    // The token keepalive follows the latest status: a renewed login brings a token of its own to refresh, after the
    // old one's keepalive stopped at the old end.
    const keepAlive = (s: SessionStatus) => {
      stopKeepalive?.();
      stopKeepalive = keepSessionAlive(s, read);
    };
    const recheck = () =>
      void read().then(
        (s) => s && keepAlive(s),
        () => undefined,
      );
    const onVisible = () => document.visibilityState === "visible" && recheck();

    read()
      .then(async (s) => {
        if (!s) return;
        const identity = sessionUser(s);
        if (!identity) {
          setPhase("out");
          return;
        }
        await onIdentityRef.current?.(identity);
        if (cancelled) return;
        endPage = state.begin(identity);
        setUser(identity);
        setPhase("in");
        keepAlive(s);
        // From here a login renewed in its own window (or another tab) moves the end for this page too.
        channel = typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(SESSION_CHANNEL);
        channel?.addEventListener("message", recheck);
        document.addEventListener("visibilitychange", onVisible);
      })
      .catch(() => {
        if (!cancelled) setPhase("failed");
      });

    return () => {
      cancelled = true;
      endPage?.();
      stopKeepalive?.();
      channel?.close();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [state]);

  // An app with a route of its own for signing in goes there instead of showing the screen.
  const goesToSignIn = phase === "out" && navigate !== undefined;
  useEffect(() => {
    if (goesToSignIn) navigate(signInPath);
  }, [goesToSignIn, navigate, signInPath]);

  const waiting = loading ?? (
    <ModuleShell label={productName} heading={<Brand productName={productName} />}>
      <VisuallyHidden as="h1">{productName}</VisuallyHidden>
      <Center minHeight="60dvh">
        <Spinner size="lg" aria-label={messages.loading} />
      </Center>
    </ModuleShell>
  );
  if (phase === "loading" || goesToSignIn) return <>{waiting}</>;
  if (phase === "out") return <>{signIn ?? <SignInScreen productName={productName} title={signInTitle ?? productName} description={signInDescription} />}</>;
  if (phase === "failed") return <SignInScreen productName={productName} title={signInTitle ?? productName} description={signInDescription} unreachable />;

  return (
    <SessionContext.Provider value={{ user: user!, state, slot: controls }}>
      <SignedOutCover signedOut={signedOut} focusBack={focusBack} state={state}>
        {children}
      </SignedOutCover>
      <SessionDialog
        endsAt={endsAt}
        signedOut={signedOut}
        owner={user}
        otherUser={otherUser}
        controlsRef={setControls}
        signedOutControls={signedOutControls}
        signedOutNote={signedOutNote}
        signedInAgainPath={signedInAgainPath}
        onFocusBack={(before) => focusBack.current?.(before)}
      />
    </SessionContext.Provider>
  );
}
