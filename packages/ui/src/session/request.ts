import { fetchReporting, onlineStatus, type OnlineStatus } from "../online-status.js";
import { messages } from "./messages.js";
import { sessionState, type SessionState } from "./state.js";

/** How long a request waits for its answer to begin. The backend waits 60 s for Eneo, so this ends only what it never answers. */
export const REQUEST_TIMEOUT_MS = 90_000;

/** What a request that the login's end refused fails with: the same whether the backend or the page refused it. */
export class SessionExpiredError extends Error {
  readonly status = 401;
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

/** What a request fails with when no answer has begun within `REQUEST_TIMEOUT_MS`. Its message is for the page to show: trying again can help. */
export class RequestTimeoutError extends Error {
  readonly status = 408;
  constructor() {
    super(messages.requestTimedOut);
    this.name = "RequestTimeoutError";
  }
}

/** Only the backend's own mark says OUR login ended; Eneo's 401 (a wrong API key, say) is an error to show. */
export function isSessionEndedAnswer(status: number, requiredHeader: string | null): boolean {
  return status === 401 && requiredHeader === "session";
}

/** Safe to send twice: a read, or a request Eneo answers once per Idempotency-Key. */
function replayable(init: RequestInit): boolean {
  const method = (init.method ?? "GET").toUpperCase();
  return method === "GET" || method === "HEAD" || new Headers(init.headers).has("Idempotency-Key");
}

/** Changes something: the backend refuses it (409 user_changed) unless the page names its user in `X-Expected-User`. */
function writes(init: RequestInit): boolean {
  return !["GET", "HEAD", "OPTIONS"].includes((init.method ?? "GET").toUpperCase());
}

/** The backend's own 409: the session under the page is someone else's, signed in from another tab. */
export async function isUserChanged(res: Response): Promise<boolean> {
  if (res.status !== 409) return false;
  const body = (await res.clone().json().catch(() => null)) as { detail?: unknown } | null;
  return body?.detail === "user_changed";
}

/** `fetch`, ended when no answer has begun within REQUEST_TIMEOUT_MS: a wait that would never end is a timeout to say. The
 * page's own signal still aborts it. Whether the answer came is told to `online`. */
async function fetchWithin(online: OnlineStatus, path: string, init: RequestInit): Promise<Response> {
  const limit = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    limit.abort();
  }, REQUEST_TIMEOUT_MS);
  const cancel = () => limit.abort(init.signal?.reason);
  if (init.signal?.aborted) cancel();
  else init.signal?.addEventListener("abort", cancel, { once: true });
  try {
    return await fetchReporting(online, path, { ...init, signal: limit.signal });
  } catch (error) {
    throw timedOut ? new RequestTimeoutError() : error;
  } finally {
    clearTimeout(timer);
    init.signal?.removeEventListener("abort", cancel);
  }
}

/**
 * `fetch` for a page whose login can end. Signed out (or someone else signed in here), nothing but `/api/auth/*`
 * leaves the page: a request that is safe to send twice waits for the new login and is sent once more, any other
 * fails with `SessionExpiredError`. A 401 with `X-Auth-Required: session` ends the login and is handled the same way, unless
 * a renewal came between the request and its refusal.
 * A write names the page's user (`X-Expected-User`): a browser has one cookie for every tab, and the backend answers 409
 * `user_changed` when the session is someone else's. That ends the login too, and the write is never sent as them.
 * A request no answer has begun for within REQUEST_TIMEOUT_MS fails with `RequestTimeoutError`.
 * Whether the module answered is told to `online` (`OfflineBanner` says what it hears).
 * Any other answer is returned as it came: parsing it is the module's.
 */
export function createFetchWithSession(state: SessionState, online: OnlineStatus = onlineStatus) {
  return async function fetchWithSession(path: string, init: RequestInit = {}): Promise<Response> {
    const send = async (again: boolean): Promise<Response> => {
      // Signed out, or someone else signed in here: nothing leaves the page until its own user is back.
      if (state.signedOut && !path.startsWith("/api/auth/")) {
        if (replayable(init) && (await state.whenRenewed(init.signal))) return send(again);
        throw new SessionExpiredError();
      }
      const question = state.ask();
      const headers = new Headers(init.headers);
      const user = state.expectedUser;
      if (user && writes(init)) headers.set("X-Expected-User", user);
      const res = await fetchWithin(online, path, { ...init, headers, credentials: "include" });
      if (isSessionEndedAnswer(res.status, res.headers.get("X-Auth-Required")) && !path.startsWith("/api/auth/")) {
        // A refusal that comes after a renewal belongs to the login before it: it covers nothing, and a request that is
        // safe to send twice goes once under the login now (which waits, if that one has ended too).
        state.ended(question);
        if (!again && replayable(init) && (await state.whenRenewed(init.signal))) return send(true);
        throw new SessionExpiredError();
      }
      if (await isUserChanged(res)) {
        state.userChanged(question);
        throw new SessionExpiredError();
      }
      return res;
    };
    return send(false);
  };
}

/** `fetch` over the page's one session state (`sessionState`), the one `RequireSession` keeps. */
export const fetchWithSession = createFetchWithSession(sessionState);
