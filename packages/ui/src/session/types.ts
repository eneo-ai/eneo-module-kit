/** Who is signed in: what the module's backend answers under `user` (Eneo's identity, `username` when Eneo has one). */
export interface SessionUser {
  id: string;
  email: string;
  username?: string;
}

/** What GET /api/auth/status answers (design.md section 5). */
export interface SessionStatus {
  authenticated: boolean;
  user: SessionUser | null;
  /** Seconds until the login ends (Eneo's ceiling or the module's own); a new login moves it. Absent when signed out. */
  session_ends_in?: number;
  /** Seconds until the backend wants to renew Eneo's token; absent when there is nothing to renew. */
  refresh_in?: number;
}
