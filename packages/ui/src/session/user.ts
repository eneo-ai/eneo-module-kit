import type { SessionStatus, SessionUser } from "./types.js";

/** The identity of an authenticated session, or null when there is none. */
export function sessionUser(status: SessionStatus): SessionUser | null {
  return status.authenticated ? status.user : null;
}

export function userDisplayName(user: SessionUser): string {
  const username = user.username?.trim();
  return username || user.email.trim();
}

export function userInitial(user: SessionUser): string {
  const [firstCharacter] = Array.from(userDisplayName(user));
  return firstCharacter?.toLocaleUpperCase("sv-SE") || "?";
}
