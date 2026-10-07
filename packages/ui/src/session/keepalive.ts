import type { SessionStatus } from "./types.js";

// After a network failure the page asks again after a while.
const RETRY_MS = 10_000;

/**
 * Asks for the session when the backend wants to renew Eneo's token (`refresh_in`), so that even a long recording
 * with no other request keeps its session. The next question is scheduled only once the answer has come, so two never
 * run at the same time. An answer that a later question has already replaced (null) schedules nothing.
 * Returns a function that stops asking.
 */
export function keepSessionAlive(first: SessionStatus, check: () => Promise<SessionStatus | null>): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const checkAfter = (delayMs: number) => {
    if (stopped) return;
    timer = setTimeout(() => {
      check().then(next, () => checkAfter(RETRY_MS));
    }, delayMs);
  };
  const next = (status: SessionStatus | null) => {
    // Without `refresh_in` there is no token to renew.
    if (status?.authenticated && status.refresh_in !== undefined) {
      checkAfter((status.refresh_in + 1) * 1000);
    }
  };

  next(first);
  return () => {
    stopped = true;
    clearTimeout(timer);
  };
}
