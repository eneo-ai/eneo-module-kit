// Carried over from speech-to-text's login-state.test.ts: the same cases, on `fetchWithSession` instead of that
// module's API functions.
import assert from "node:assert/strict";
import test from "node:test";
import { createSessionState } from "../src/session/state.js";
import { createFetchWithSession, isSessionEndedAnswer, SessionExpiredError } from "../src/session/request.js";
import type { SessionStatus } from "../src/session/types.js";

const sessionEnded = () =>
  new Response(JSON.stringify({ detail: "Not authenticated" }), {
    status: 401,
    headers: { "content-type": "application/json", "X-Auth-Required": "session" },
  });
const anna = { id: "user-1", email: "anna@example.se", username: "Anna Berg" };
const erik = { id: "user-2", email: "erik@example.se", username: "Erik Lund" };
const signedIn = (sessionEndsIn = 8 * 3600, user = anna): SessionStatus => ({ authenticated: true, user, session_ends_in: sessionEndsIn });
const signedOut: SessionStatus = { authenticated: false, user: null };
const ok = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
const is401 = (error: unknown) => error instanceof SessionExpiredError && error.status === 401;
const settle = () => new Promise((resolve) => setImmediate(resolve));

/** A signed-in page (the gate has begun it) whose requests the stub answers in turn. */
function signedInPage(t: import("node:test").TestContext, answers: Array<() => Response>) {
  const state = createSessionState();
  const calls: Array<{ url: string; method: string }> = [];
  const browserFetch = globalThis.fetch;
  globalThis.fetch = (async (url: string | URL | Request, init?: RequestInit) => {
    calls.push({ url: String(url), method: init?.method ?? "GET" });
    return (answers.shift() ?? (() => ok({})))();
  }) as typeof fetch;
  const end = state.begin(anna);
  t.after(() => {
    end();
    globalThis.fetch = browserFetch;
  });
  return { state, calls, fetchWithSession: createFetchWithSession(state) };
}

test("a session end never throws the page away: it stays signed out, and a read waits for the new login and goes again", async (t) => {
  const { state, calls, fetchWithSession } = signedInPage(t, [sessionEnded, () => ok({ status: "running" })]);
  const reading = fetchWithSession("/api/eneo/runs/run-1/");
  await settle();
  assert.equal(state.signedOut, true, "the sign-in dialog opens over the page");
  assert.equal(calls.length, 1, "the read waits");

  state.observe(signedIn());
  assert.deepEqual(await (await reading).json(), { status: "running" });
  assert.equal(state.signedOut, false);
  assert.equal(calls.length, 2, "sent again once");
});

test("a request sent again after the new login is sent again only once", async (t) => {
  const { state, calls, fetchWithSession } = signedInPage(t, [sessionEnded, sessionEnded]);
  const reading = fetchWithSession("/api/eneo/runs/run-1/");
  await settle();
  state.observe(signedIn());
  await assert.rejects(reading, is401);
  assert.equal(calls.length, 2);
});

test("a write with its Idempotency-Key goes again after the new login; a write without one is the user's to repeat", async (t) => {
  const { state, calls, fetchWithSession } = signedInPage(t, [sessionEnded, () => ok({ id: "run-1" }), sessionEnded]);
  const starting = fetchWithSession("/api/eneo/runs/", { method: "POST", headers: { "Idempotency-Key": "run:r1" }, body: "{}" });
  await settle();
  state.observe(signedIn());
  assert.equal(((await (await starting).json()) as { id: string }).id, "run-1");
  assert.deepEqual(calls.map((call) => call.method), ["POST", "POST"]);

  await assert.rejects(fetchWithSession("/api/eneo/runs/run-1/cancel/", { method: "POST" }), is401);
  assert.equal(state.signedOut, true, "and asks for the login");
  assert.equal(calls.length, 3, "not sent again by itself");
});

test("a wait ends when its request is cancelled", async (t) => {
  const { calls, fetchWithSession } = signedInPage(t, [sessionEnded]);
  const cancel = new AbortController();
  const starting = fetchWithSession("/api/eneo/runs/", { method: "POST", headers: { "Idempotency-Key": "run:r1" }, signal: cancel.signal });
  await settle();
  cancel.abort();
  await assert.rejects(starting, is401);
  assert.equal(calls.length, 1);
});

test("a page no gate holds never waits for a login", async (t) => {
  const state = createSessionState();
  const fetchWithSession = createFetchWithSession(state);
  const browserFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = (async () => {
    calls += 1;
    return sessionEnded();
  }) as typeof fetch;
  t.after(() => {
    globalThis.fetch = browserFetch;
  });
  await assert.rejects(fetchWithSession("/api/eneo/runs/run-1/"), is401);
  assert.equal(state.signedOut, false);
  assert.equal(calls, 1, "sent once");
});

test("the login's end time or a status that says signed out ends it too; a status that says signed in renews it", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const state = createSessionState();
  const end = state.begin(anna);
  t.after(end);
  state.observe(signedIn(60));
  t.mock.timers.tick(59_000);
  assert.equal(state.signedOut, false);
  t.mock.timers.tick(1_000);
  assert.equal(state.signedOut, true, "the end time passed");
  state.observe(signedIn());
  assert.equal(state.signedOut, false);
  state.observe(signedOut);
  assert.equal(state.signedOut, true);
});

test("someone else signing in here unlocks nothing: what waits is not sent as them, and goes once the page's own user is back", async (t) => {
  const { state, calls, fetchWithSession } = signedInPage(t, [sessionEnded, () => ok({ status: "running" })]);
  const reading = fetchWithSession("/api/eneo/runs/run-1/");
  await settle();
  state.observe(signedIn(8 * 3600, erik));
  await settle();
  assert.equal(state.signedOut, true, "the page stays covered");
  assert.deepEqual(state.otherUser, erik, "and says who is signed in instead");
  assert.equal(calls.length, 1, "nothing is sent again under Erik's login");

  state.observe(signedIn());
  assert.deepEqual(await (await reading).json(), { status: "running" });
  assert.equal(state.signedOut, false);
  assert.equal(state.otherUser, null);
  assert.equal(calls.length, 2);
});

test("while signed out nothing leaves the page but the login's own routes: a read waits for the page's user, a write is refused unsent", async (t) => {
  const { state, calls, fetchWithSession } = signedInPage(t, [() => ok({ status: "running" })]);
  state.observe(signedIn(8 * 3600, erik)); // someone else, whose login every request would carry
  await assert.rejects(fetchWithSession("/api/eneo/runs/run-1/cancel/", { method: "POST" }), is401);
  const reading = fetchWithSession("/api/eneo/runs/run-1/");
  await settle();
  assert.equal(calls.length, 0);
  state.observe(signedIn());
  assert.deepEqual(await (await reading).json(), { status: "running" });
  assert.deepEqual(calls.map((call) => call.method), ["GET"]);

  state.ended();
  const status = await fetchWithSession("/api/auth/status");
  assert.equal(status.status, 200, "the session's own routes always go: the new login is asked of them");
  assert.equal(calls.at(-1)?.url, "/api/auth/status");
});

test("only the backend's own mark says the login ended: Eneo's own 401 is an answer to show", async (t) => {
  const { state, fetchWithSession } = signedInPage(t, [() => new Response("{}", { status: 401 })]);
  const answer = await fetchWithSession("/api/eneo/flows/");
  assert.equal(answer.status, 401, "returned as it came");
  assert.equal(state.signedOut, false);
  assert.equal(isSessionEndedAnswer(401, "session"), true);
  assert.equal(isSessionEndedAnswer(401, null), false);
  assert.equal(isSessionEndedAnswer(403, "session"), false);
});
