/**
 * Whether this page's login holds. Its end never navigates away: the page stays with all it holds, a recording keeps
 * capturing, and the gate asks for a new login in place. Only the page's own user signing in again ends that:
 * someone else's login keeps the page covered. Until then nothing is sent from it (`fetchWithSession`): a request
 * that is safe to send twice (a GET, or one with an Idempotency-Key) waits for the new login and goes; any other
 * fails, for the user to press again once signed in.
 *
 * Answers come back in any order: a request sent under a login that a renewal has since replaced may be refused late, and
 * a status read asked before the end may say "signed in" after it. The state is the one owner of the login's revision, so
 * neither moves it (`Question`).
 */

import type { SessionStatus, SessionUser } from "./types.js";
import { sessionUser } from "./user.js";

/**
 * What a question to the backend (a status read, a request) remembers of the login when it was asked, to tell when its
 * answer comes whether it is still about the login the page has: the login's revision, and the question's place among
 * the questions.
 */
export interface Question {
  readonly revision: number;
  readonly order: number;
}

export interface SessionState {
  readonly signedOut: boolean;
  /** Who is signed in instead of the page's user, while the page stays covered for them. */
  readonly otherUser: SessionUser | null;
  /** How many times a new login of the page's user has been confirmed; a page that shows the login's end starts over on each. */
  readonly renewals: number;
  /** How many requests wait for the new login. */
  readonly waiting: number;
  subscribe(listener: () => void): () => void;
  /** A page signed in as `owner` from here on (the gate); the returned function ends it. */
  begin(owner: SessionUser): () => void;
  /** Starts a question to the backend: ask before sending, and give the question back with its answer. */
  ask(): Question;
  /**
   * What the module's backend says of the login: signed in and until when, or signed out. False, and nothing changes,
   * when the answer belongs to a question asked before the login changed or before one already answered: it is about a
   * login that is gone. Without a question, it is taken as asked now.
   */
  observe(status: SessionStatus, question?: Question): boolean;
  /**
   * A request found the login ended (401 with X-Auth-Required: session). False, and nothing changes, when the request
   * was sent before the login changed: the refusal is about the old login, not the page's. Without a question, the
   * login is ended.
   */
  ended(question?: Question): boolean;
  /**
   * A login window of the module says it is done. The backend has replaced the cookie and deleted the old session by then,
   * so from this word on everything asked before it, and the deadline of the old login, is about a login that is gone: the
   * revision moves now, not when the status read that confirms the renewal is back. That read, the first one asked from now,
   * is the one that confirms it.
   */
  loginWindowDone(): void;
  /** True once signed in again; false at once where no signed-in page waits, or when `signal` ends the wait. */
  whenRenewed(signal?: AbortSignal | null): Promise<boolean>;
}

/** A request that waits for the new login, and the abort listener it put on its signal. */
interface Waiter {
  resolve: (renewed: boolean) => void;
  signal?: AbortSignal | null;
  onAbort?: () => void;
}

export function createSessionState(): SessionState {
  let pages = 0;
  let owner: SessionUser | null = null;
  let signedOut = false;
  let otherUser: SessionUser | null = null;
  let endTimer: ReturnType<typeof setTimeout> | undefined;
  // When the last answer said the login ends (ms), once one has; the timer for it runs while a page holds the login.
  let endsAtMs: number | null = null;
  // The one revision of the login: it changes whenever the login does (ended, signed in again, someone else's, a login
  // window's word that a renewal has replaced it). A question's answer counts only under the revision it was asked in, and
  // only if no later question has been answered: so a late answer never undoes what a newer one, or the end itself, has
  // settled. A page beginning or ending is no change of the login: a first read must still count.
  let revision = 0;
  let asked = 0;
  let answered = 0;
  let renewals = 0;
  // The question number a login window's word came after: the first answer to a question asked past it confirms a renewal.
  let windowDoneAt: number | null = null;
  const waiters = new Set<Waiter>();
  const listeners = new Set<() => void>();

  // The one way a wait ends, whether it is renewed, cancelled or torn down: out of the queue, off its signal.
  const finish = (waiter: Waiter, renewed: boolean) => {
    if (!waiters.delete(waiter)) return;
    if (waiter.signal && waiter.onAbort) waiter.signal.removeEventListener("abort", waiter.onAbort);
    waiter.resolve(renewed);
  };
  const settle = (renewed: boolean) => [...waiters].forEach((waiter) => finish(waiter, renewed));
  const setSignedOut = (next: boolean, other: SessionUser | null = null) => {
    if (signedOut === next && otherUser?.id === other?.id) return;
    signedOut = next;
    otherUser = other;
    revision += 1;
    if (!next) settle(true);
    listeners.forEach((listener) => listener());
  };
  const endedUnder = (since?: number) => {
    if (since !== undefined && since !== revision) return false;
    if (pages > 0) setSignedOut(true);
    return true;
  };
  const ended = (question?: Question) => endedUnder(question?.revision);
  // The login ends at its time whatever the page does; only a new login moves it. No page, no timer to leak. The deadline
  // is the login's as it was when the timer was set: once the login has changed, the old deadline ends nothing.
  const arm = () => {
    clearTimeout(endTimer);
    const armed = revision;
    if (pages > 0 && endsAtMs !== null) endTimer = setTimeout(() => endedUnder(armed), Math.max(0, endsAtMs - Date.now()));
  };
  const ask = (): Question => ({ revision, order: ++asked });

  return {
    get signedOut() {
      return signedOut;
    },
    get otherUser() {
      return otherUser;
    },
    get renewals() {
      return renewals;
    },
    get waiting() {
      return waiters.size;
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    begin(user) {
      owner = user;
      pages += 1;
      arm();
      let open = true;
      return () => {
        if (!open) return;
        open = false;
        pages -= 1;
        if (pages > 0) return;
        clearTimeout(endTimer);
        settle(false);
        setSignedOut(false);
      };
    },
    ask,
    observe(status, question = ask()) {
      if (question.revision !== revision || question.order <= answered) return false;
      answered = question.order;
      clearTimeout(endTimer);
      const user = sessionUser(status);
      if (!user) {
        windowDoneAt = null;
        ended();
        return true;
      }
      // Someone else's login is not this page's: it stays covered, and nothing waiting goes out as them.
      if (pages > 0 && owner && user.id !== owner.id) {
        setSignedOut(true, user);
        return true;
      }
      const confirmed = windowDoneAt !== null && question.order > windowDoneAt;
      if (confirmed) windowDoneAt = null;
      const back = signedOut;
      setSignedOut(false);
      // A new login of the page's user: one that follows the end, or that a login window announced (whose word has already
      // moved the revision, so what was asked since is still taken).
      if (back || confirmed) renewals += 1;
      endsAtMs = status.session_ends_in === undefined ? null : Date.now() + status.session_ends_in * 1000;
      arm();
      return true;
    },
    ended,
    loginWindowDone() {
      windowDoneAt = asked;
      revision += 1;
    },
    whenRenewed(signal) {
      if (pages === 0 || signal?.aborted) return Promise.resolve(false);
      if (!signedOut) return Promise.resolve(true);
      return new Promise((resolve) => {
        const waiter: Waiter = { resolve, signal };
        if (signal) {
          waiter.onAbort = () => finish(waiter, false);
          signal.addEventListener("abort", waiter.onAbort, { once: true });
        }
        waiters.add(waiter);
      });
    },
  };
}

/** The page's one session state, shared by the gate (`RequireSession`) and `fetchWithSession`. */
export const sessionState: SessionState = createSessionState();
