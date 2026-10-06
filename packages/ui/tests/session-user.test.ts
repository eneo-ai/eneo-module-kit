// Carried over from speech-to-text's user-identity.test.ts, without the access-code cases (the kit is SSO only).
import assert from "node:assert/strict";
import test from "node:test";
import { sessionUser, userDisplayName, userInitial } from "../src/session/user.js";

test("uses the trimmed Eneo username as display name and avatar initial", () => {
  const user = { id: "user-id", email: "asa@example.test", username: "  Åsa Öberg  " };
  assert.equal(userDisplayName(user), "Åsa Öberg");
  assert.equal(userInitial(user), "Å");
});

test("falls back to the email address when Eneo has no username", () => {
  const user = { id: "user-id", email: "anna@example.test", username: "   " };
  assert.equal(userDisplayName(user), "anna@example.test");
  assert.equal(userInitial(user), "A");
});

test("uses a safe fallback for an invalid empty identity", () => {
  const user = { id: "user-id", email: "" };
  assert.equal(userDisplayName(user), "");
  assert.equal(userInitial(user), "?");
});

test("an unauthenticated or user-less session has no identity", () => {
  assert.equal(sessionUser({ authenticated: false, user: null }), null);
  assert.equal(sessionUser({ authenticated: true, user: null }), null);
  const eneoUser = { id: "u1", email: "anna@example.test" };
  assert.equal(sessionUser({ authenticated: true, user: eneoUser }), eneoUser);
});
