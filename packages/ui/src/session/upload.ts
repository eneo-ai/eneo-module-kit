import { onlineStatus, type OnlineStatus } from "../online-status.js";
import { isSessionEndedAnswer, isUserChanged, REQUEST_TIMEOUT_MS, RequestTimeoutError, SessionExpiredError } from "./request.js";
import { sessionState, type SessionState } from "./state.js";

/** How much of the body has gone up; `total` is null when the browser cannot tell the size. */
export interface UploadProgress {
  loaded: number;
  total: number | null;
}

export interface UploadOptions {
  /** "POST" unless said. */
  method?: string;
  headers?: HeadersInit;
  signal?: AbortSignal;
  /** Heard each time more of the body has gone up. */
  onProgress?: (progress: UploadProgress) => void;
  /** How long nothing may go up, before the first byte and between bytes. */
  idleTimeoutMs?: number;
  /**
   * Once every byte is up, how long the answer may take to begin. The backend is told (`X-Upload-Timeout-Seconds`, which
   * `forward_upload` reads), so it waits for Eneo no longer than the page waits for it.
   */
  answerTimeoutMs?: number;
}

/** The answer as `fetch` gives it: its status, its headers and its body, which 204, 205 and 304 do not have. */
function responseOf(xhr: XMLHttpRequest): Response {
  const headers = new Headers();
  for (const line of xhr.getAllResponseHeaders().split("\r\n")) {
    const colon = line.indexOf(":");
    if (colon > 0) headers.append(line.slice(0, colon).trim(), line.slice(colon + 1).trim());
  }
  const body = [204, 205, 304].includes(xhr.status) ? null : (xhr.response as Blob);
  return new Response(body, { status: xhr.status, statusText: xhr.statusText, headers });
}

/**
 * An upload that says how far it has come (XMLHttpRequest: `fetch` cannot tell), under the same rules as
 * `fetchWithSession` and failing with the same errors. Signed out (or someone else signed in here), it fails with
 * `SessionExpiredError` and nothing leaves the page: an upload is never sent twice, it is the person's to send again once
 * signed in. It names the page's user (`X-Expected-User`); a 401 with `X-Auth-Required: session` and a 409 `user_changed`
 * end the login and fail with `SessionExpiredError`. Nothing moving for `idleTimeoutMs`, or no answer begun within
 * `answerTimeoutMs` of the last byte, fails with `RequestTimeoutError`. Not reaching the module fails with a TypeError, as
 * `fetch` does, and is told to `online`; an answer is too. The page's own `signal` aborts it. Any other answer is returned
 * as a `Response`: parsing it is the module's.
 */
export function createUploadWithProgress(state: SessionState, online: OnlineStatus = onlineStatus) {
  return function uploadWithProgress(path: string, body: XMLHttpRequestBodyInit, options: UploadOptions = {}): Promise<Response> {
    const { method = "POST", headers, signal, onProgress, idleTimeoutMs = REQUEST_TIMEOUT_MS, answerTimeoutMs = REQUEST_TIMEOUT_MS } = options;
    if (signal?.aborted) return Promise.reject(signal.reason);
    if (state.signedOut) return Promise.reject(new SessionExpiredError());
    const question = state.ask();
    return new Promise<Response>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      let timer: ReturnType<typeof setTimeout> | undefined;
      let settled = false;
      let loaded = 0;
      let sent: number | undefined;
      const finish = (end: () => void) => {
        if (settled) return;
        settled = true;
        clearTimeout(timer);
        signal?.removeEventListener("abort", cancel);
        end();
      };
      // Settled first: abort() fires the abort event before it returns, which would read as the page's own abort.
      const cancel = () => {
        finish(() => reject(signal?.reason));
        xhr.abort();
      };
      const wait = (ms: number) => {
        clearTimeout(timer);
        // Once the answer has begun (HEADERS_RECEIVED) it is read as `fetch` reads it: untimed.
        if (xhr.readyState >= 2) return;
        timer = setTimeout(() => {
          finish(() => reject(new RequestTimeoutError()));
          xhr.abort();
        }, ms);
      };

      xhr.upload.onprogress = (event) => {
        if (event.loaded <= loaded) return;
        loaded = event.loaded;
        onProgress?.({ loaded, total: event.lengthComputable ? event.total : null });
        wait(idleTimeoutMs);
      };
      xhr.upload.onload = () => wait(answerTimeoutMs);
      xhr.onreadystatechange = () => {
        if (xhr.readyState >= 2) clearTimeout(timer);
      };
      xhr.onload = async () => {
        online.reportReachable(sent);
        if (isSessionEndedAnswer(xhr.status, xhr.getResponseHeader("X-Auth-Required"))) {
          state.ended(question);
          finish(() => reject(new SessionExpiredError()));
          return;
        }
        const answer = responseOf(xhr);
        if (await isUserChanged(answer)) {
          state.userChanged(question);
          finish(() => reject(new SessionExpiredError()));
          return;
        }
        finish(() => resolve(answer));
      };
      xhr.onerror = () => {
        online.reportNetworkFailure();
        finish(() => reject(new TypeError("Network request failed")));
      };
      xhr.onabort = () => finish(() => reject(new DOMException("The upload was aborted.", "AbortError")));

      xhr.open(method, path);
      xhr.withCredentials = true;
      xhr.responseType = "blob";
      new Headers(headers).forEach((value, name) => xhr.setRequestHeader(name, value));
      // An upload is a write: the backend refuses it (409 user_changed) under someone else's session.
      if (state.expectedUser) xhr.setRequestHeader("X-Expected-User", state.expectedUser);
      xhr.setRequestHeader("X-Upload-Timeout-Seconds", String(Math.ceil(answerTimeoutMs / 1000)));
      // After the headers, which can throw (a header the page gave that is no header): nothing is left on the signal.
      signal?.addEventListener("abort", cancel, { once: true });
      wait(idleTimeoutMs);
      sent = online.sending();
      xhr.send(body);
    });
  };
}

/** An upload over the page's one session state (`sessionState`), the one `RequireSession` keeps. */
export const uploadWithProgress = createUploadWithProgress(sessionState);
