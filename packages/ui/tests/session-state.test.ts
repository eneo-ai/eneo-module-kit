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
function signedInPage(t: import("node:test").TestContext, answers: Array<() => Response | Promise<Response>>) {
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

test("a status read before any page holds the login leaves no timer; the page that begins later is told the end that passed", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  const state = createSessionState();
  state.observe(signedIn(60)); // a gate that read the status, and failed before it began
  t.mock.timers.tick(61_000);
  assert.equal(state.signedOut, false, "nobody is there to have signed out");
  const end = state.begin(anna);
  t.after(end);
  t.mock.timers.tick(1);
  assert.equal(state.signedOut, true, "a page that begins after the end has passed is signed out at once");
});

/** A request's answer held back until the test lets it arrive. */
const held = () => {
  let release: (response: Response) => void = () => {};
  const answer = () => new Promise<Response>((resolve) => (release = resolve));
  return { answer, arrive: (response: Response) => release(response) };
};

test("a refusal meant for the login before a renewal covers nothing: a read goes again under the new login, once", async (t) => {
  const late = held();
  const { state, calls, fetchWithSession } = signedInPage(t, [late.answer, () => ok({ status: "running" })]);
  const reading = fetchWithSession("/api/eneo/runs/run-1/");
  await settle();
  state.observe(signedOut); // the login ended while the request was out
  state.observe(signedIn()); // and a new one began
  late.arrive(sessionEnded()); // the old login's refusal, late
  await settle();
  assert.equal(state.signedOut, false, "the renewed page is not covered again");
  assert.deepEqual(await (await reading).json(), { status: "running" }, "the read went again under the new login");
  assert.equal(calls.length, 2);
});

test("a late refusal after a renewal made before the end, which only the login window announced, covers nothing either", async (t) => {
  const late = held();
  const { state, fetchWithSession } = signedInPage(t, [late.answer]);
  const writing = fetchWithSession("/api/eneo/runs/run-1/cancel/", { method: "POST" });
  await settle();
  state.loginWindowDone();
  state.observe(signedIn(30)); // the end moves by under a minute: only the window's word says it is a new login
  late.arrive(sessionEnded());
  await assert.rejects(writing, is401);
  assert.equal(state.signedOut, false, "a write is the user's to repeat, and the page stays usable");
});

test("a late refusal is not replayed twice: the second refusal, which is about the login now, covers the page", async (t) => {
  const late = held();
  const { state, calls, fetchWithSession } = signedInPage(t, [late.answer, sessionEnded]);
  const reading = fetchWithSession("/api/eneo/runs/run-1/");
  await settle();
  state.observe(signedOut);
  state.observe(signedIn());
  late.arrive(sessionEnded());
  await assert.rejects(reading, is401);
  assert.equal(calls.length, 2, "sent again once");
  assert.equal(state.signedOut, true, "the refusal to the new login is the login's end");
});

test("an answer to a status question asked before the login ended cannot uncover the page; one asked after can", () => {
  const state = createSessionState();
  const end = state.begin(anna);
  const before = state.ask();
  assert.equal(state.ended(), true, "a request found the login ended");
  assert.equal(state.observe(signedIn(), before), false, "the late answer is about a login that is gone");
  assert.equal(state.signedOut, true);
  assert.equal(state.observe(signedIn(), state.ask()), true);
  assert.equal(state.signedOut, false);
  end();
});

test("an answer to an earlier question than one already answered is dropped, as the state's one order", () => {
  const state = createSessionState();
  const end = state.begin(anna);
  const first = state.ask();
  const second = state.ask();
  assert.equal(state.observe(signedIn(), second), true);
  assert.equal(state.observe(signedOut, first), false, "the earlier question's answer comes last and changes nothing");
  assert.equal(state.signedOut, false);
  end();
});

test("a wait that is cancelled, renewed or torn down leaves nothing behind: not in the queue, not on its signal", async () => {
  const state = createSessionState();
  const end = state.begin(anna);
  state.observe(signedOut);
  /** A signal that counts the listeners it holds. */
  const counted = () => {
    const controller = new AbortController();
    const held = new Set<unknown>();
    const { addEventListener, removeEventListener } = controller.signal;
    controller.signal.addEventListener = ((type: string, listener: EventListener, options?: AddEventListenerOptions) => {
      held.add(listener);
      addEventListener.call(controller.signal, type, listener, options);
    }) as typeof addEventListener;
    controller.signal.removeEventListener = ((type: string, listener: EventListener) => {
      held.delete(listener);
      removeEventListener.call(controller.signal, type, listener);
    }) as typeof removeEventListener;
    return { controller, held };
  };

  const cancelled = counted();
  const cancelling = state.whenRenewed(cancelled.controller.signal);
  assert.equal(state.waiting, 1);
  cancelled.controller.abort();
  assert.equal(await cancelling, false);
  assert.equal(state.waiting, 0, "a cancelled wait is out of the queue at once");
  assert.equal(cancelled.held.size, 0);

  const many = Array.from({ length: 50 }, () => counted());
  const waits = many.map(({ controller }) => state.whenRenewed(controller.signal));
  many.forEach(({ controller }) => controller.abort());
  await Promise.all(waits);
  assert.equal(state.waiting, 0, "many cancelled waits do not pile up while signed out");

  const renewed = counted();
  const renewing = state.whenRenewed(renewed.controller.signal);
  state.observe(signedIn());
  assert.equal(await renewing, true);
  assert.equal(state.waiting, 0);
  assert.equal(renewed.held.size, 0, "a renewal takes the abort listener off a signal that goes on living");

  state.observe(signedOut);
  const torn = counted();
  const tearing = state.whenRenewed(torn.controller.signal);
  end();
  assert.equal(await tearing, false);
  assert.equal(state.waiting, 0);
  assert.equal(torn.held.size, 0, "and so does the page going away");
});

// A renewal replaces the cookie and deletes the old session on the backend before the login window says it is done: from
// that word on, everything asked earlier is about a login that is gone, though the status read that confirms the renewal
// has not come back yet.
test("an old signed-out status that arrives between the login window's word and the confirmation is dropped; the fresh one recovers the page", () => {
  const state = createSessionState();
  const end = state.begin(anna);
  const old = state.ask();
  state.loginWindowDone();
  const fresh = state.ask();
  assert.equal(state.observe(signedOut, old), false, "asked before the word");
  assert.equal(state.signedOut, false);
  assert.equal(state.observe(signedIn(), fresh), true, "the confirmation is still taken");
  assert.equal(state.signedOut, false);
  assert.equal(state.renewals, 1, "and it confirms the renewal");
  end();
});

test("an old marked 401 that arrives between the login window's word and the confirmation covers nothing", () => {
  const state = createSessionState();
  const end = state.begin(anna);
  const old = state.ask();
  state.loginWindowDone();
  const fresh = state.ask();
  assert.equal(state.ended(old), false);
  assert.equal(state.signedOut, false);
  assert.equal(state.observe(signedIn(), fresh), true);
  assert.equal(state.signedOut, false);
  end();
});

test("the old deadline that passes between the login window's word and the confirmation does not cover the page or spoil the confirmation", (t) => {
  t.mock.timers.enable({ apis: ["setTimeout", "Date"] });
  const state = createSessionState();
  const end = state.begin(anna);
  t.after(end);
  state.observe(signedIn(60));
  state.loginWindowDone();
  const fresh = state.ask();
  t.mock.timers.tick(61_000);
  assert.equal(state.signedOut, false, "the old login's deadline is not the new login's");
  assert.equal(state.observe(signedIn(8 * 3600), fresh), true);
  assert.equal(state.signedOut, false);
  t.mock.timers.tick(61_000);
  assert.equal(state.signedOut, false, "and the new end is the one that counts now");
});
