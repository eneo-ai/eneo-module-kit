import { useEffect, useState } from "react";

export interface User {
  id: string;
  email: string;
  username?: string;
}

export type Session = { state: "loading" } | { state: "signed-out" } | { state: "signed-in"; user: User };

/** Who is signed in, from the backend's /api/auth/status. The kit's session client (a later version) replaces this. */
export function useSession(): Session {
  const [session, setSession] = useState<Session>({ state: "loading" });
  useEffect(() => {
    let current = true;
    fetch("/api/auth/status", { cache: "no-store" })
      .then((response) => response.json() as Promise<{ authenticated: boolean; user: User | null }>)
      .then((body) => current && setSession(body.authenticated && body.user ? { state: "signed-in", user: body.user } : { state: "signed-out" }))
      .catch(() => current && setSession({ state: "signed-out" }));
    return () => {
      current = false;
    };
  }, []);
  return session;
}

/** Ends the session (a same-origin POST), then starts over from the sign-in page. */
export async function signOut(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST" });
  window.location.assign("/");
}

/** The error of a call the backend answered with a status. A 401 is the session having ended. */
export class ApiError extends Error {
  constructor(readonly status: number) {
    super(`The backend answered ${status}`);
  }
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new ApiError(response.status);
  return (await response.json()) as T;
}
