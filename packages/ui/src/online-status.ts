import { useCallback, useSyncExternalStore } from "react";

/**
 * The one owner of "is the page online". The browser's online and offline events say when the device loses its network;
 * the page's own requests (`fetchWithSession`, `uploadWithProgress`, the session's status reads) say when a network that
 * looks connected does not reach the module. A request that reaches the module, or the browser coming back online,
 * clears an earlier failure. An answer from the module also outweighs a browser that says the device has no network
 * (Safari can go on saying so after a device wakes), when the request left after the browser said it: an answer that was
 * already on its way when the network went says nothing of the network now. The two causes are told apart
 * (`connection`): a page says "no connection" only of the device, and that the module does not answer of the rest.
 */

export type Connection = "online" | "offline" | "unreachable";

export interface OnlineStatus {
  readonly online: boolean;
  /** "offline": the device has no network. "unreachable": it has, and a request did not reach the module. */
  readonly connection: Connection;
  /** Heard when the connection changes, also from one cause to the other, with whether it is online now. */
  subscribe(listener: (online: boolean) => void): () => void;
  /** A request did not reach the module (`fetch` failed with a TypeError, an XMLHttpRequest with `error`). */
  reportNetworkFailure(): void;
  /** The moment a request leaves, to give back with its answer (`reportReachable`). */
  sending(): number;
  /** A request reached the module. `sent`: when it left; without it the answer clears only an earlier failure. */
  reportReachable(sent?: number): void;
}

/** What the status listens to: a window, or a test's stand-in for one. */
export interface OnlineTarget {
  navigator: { onLine: boolean };
  addEventListener(type: "online" | "offline", listener: () => void): void;
}

export function createOnlineStatus(target?: OnlineTarget, now: () => number = () => performance.now()): OnlineStatus {
  let browserOnline = target?.navigator.onLine ?? true;
  // When the browser last said there is no network: a page opened offline was told so before anything left it.
  let saidOffline = browserOnline ? null : -Infinity;
  let requestFailed = false;
  const listeners = new Set<(online: boolean) => void>();
  const connection = (): Connection => (!browserOnline ? "offline" : requestFailed ? "unreachable" : "online");
  const change = (apply: () => void) => {
    const before = connection();
    apply();
    if (connection() !== before) listeners.forEach((listener) => listener(connection() === "online"));
  };

  target?.addEventListener("online", () =>
    change(() => {
      browserOnline = true;
      requestFailed = false;
    }),
  );
  target?.addEventListener("offline", () =>
    change(() => {
      browserOnline = false;
      saidOffline = now();
    }),
  );

  return {
    get online() {
      return connection() === "online";
    },
    get connection() {
      return connection();
    },
    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    reportNetworkFailure: () => change(() => (requestFailed = true)),
    sending: now,
    reportReachable: (sent) =>
      change(() => {
        requestFailed = false;
        if (!browserOnline && sent !== undefined && saidOffline !== null && sent > saidOffline) browserOnline = true;
      }),
  };
}

/** The page's one status, which the session client's requests report to. */
export const onlineStatus: OnlineStatus = createOnlineStatus(typeof window === "undefined" ? undefined : window);

/** The connection now, and a new render when it changes: for what a page offers while it is gone. */
export function useConnection(status: OnlineStatus = onlineStatus): Connection {
  const subscribe = useCallback((onChange: () => void) => status.subscribe(onChange), [status]);
  return useSyncExternalStore(subscribe, () => status.connection, () => "online");
}

/** `fetch`, and what its answer or its failure says of the connection, told to `status`. An abort says nothing. */
export async function fetchReporting(status: OnlineStatus, input: string, init?: RequestInit): Promise<Response> {
  const sent = status.sending();
  let response: Response;
  try {
    response = await fetch(input, init);
  } catch (error) {
    // fetch fails with a TypeError when the network is down; the page's own abort is a DOMException.
    if (error instanceof TypeError) status.reportNetworkFailure();
    throw error;
  }
  status.reportReachable(sent);
  return response;
}
