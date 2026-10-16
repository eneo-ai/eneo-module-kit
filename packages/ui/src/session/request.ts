import { sessionState, type SessionState } from "./state.js";

/** What a request that the login's end refused fails with: the same whether the backend or the page refused it. */
export class SessionExpiredError extends Error {
  readonly status = 401;
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
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
async function isUserChanged(res: Response): Promise<boolean> {
  if (res.status !== 409) return false;
  const body = (await res.clone().json().catch(() => null)) as { detail?: unknown } | null;
  return body?.detail === "user_changed";
}

/**
 * `fetch` for a page whose login can end. Signed out (or someone else signed in here), nothing but `/api/auth/*`
 * leaves the page: a request that is safe to send twice waits for the new login and is sent once more, any other
 * fails with `SessionExpiredError`. A 401 with `X-Auth-Required: session` ends the login and is handled the same way, unless
 * a renewal came between the request and its refusal.
 * A write names the page's user (`X-Expected-User`): a browser has one cookie for every tab, and the backend answers 409
 * `user_changed` when the session is someone else's. That ends the login too, and the write is never sent as them.
 * Any other answer is returned as it came: parsing it is the module's.
 */
export function createFetchWithSession(state: SessionState) {
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
      const res = await fetch(path, { ...init, headers, credentials: "include" });
      if (isSessionEndedAnswer(res.status, res.headers.get("X-Auth-Required")) && !path.startsWith("/api/auth/")) {
        // A refusal that comes after a renewal belongs to the login before it: it covers nothing, and a request that is
        // safe to send twice goes once under the login now (which waits, if that one has ended too).
        state.ended(question);
        if (!again && replayable(init) && (await state.whenRenewed(init.signal))) return send(true);
        throw new SessionExpiredError();
      }
      if (await isUserChanged(res)) {
        state.ended(question);
        throw new SessionExpiredError();
      }
      return res;
    };
    return send(false);
  };
}

/** `fetch` over the page's one session state (`sessionState`), the one `RequireSession` keeps. */
export const fetchWithSession = createFetchWithSession(sessionState);
