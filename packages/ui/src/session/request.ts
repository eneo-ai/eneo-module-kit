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

/**
 * `fetch` for a page whose login can end. Signed out (or someone else signed in here), nothing but `/api/auth/*`
 * leaves the page: a request that is safe to send twice waits for the new login and is sent once more, any other
 * fails with `SessionExpiredError`. A 401 with `X-Auth-Required: session` ends the login and is handled the same way.
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
      const res = await fetch(path, { ...init, credentials: "include" });
      if (isSessionEndedAnswer(res.status, res.headers.get("X-Auth-Required")) && !path.startsWith("/api/auth/")) {
        state.ended();
        if (!again && replayable(init) && (await state.whenRenewed(init.signal))) return send(true);
        throw new SessionExpiredError();
      }
      return res;
    };
    return send(false);
  };
}

/** `fetch` over the page's one session state (`sessionState`), the one `RequireSession` keeps. */
export const fetchWithSession = createFetchWithSession(sessionState);
