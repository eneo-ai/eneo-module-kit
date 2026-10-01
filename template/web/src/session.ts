import { fetchWithSession } from "@eneo-ai/module-kit/session";

/** Ends the session (a same-origin POST), then starts over from the sign-in page. */
export async function signOut(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.assign("/");
}

/** The error of a call the backend answered with a status. A login that ended is not one: `fetchWithSession` waits for the new login. */
export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`The backend answered ${status}`);
  }
}

/** A GET of JSON, over the page's session: while the login has ended it waits for the new login and goes again. */
export async function getJson<T>(path: string): Promise<T> {
  const response = await fetchWithSession(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}
