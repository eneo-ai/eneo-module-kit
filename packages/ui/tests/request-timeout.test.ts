// Carried over from speech-to-text's request-timeout.test.ts, on `fetchWithSession`.
import assert from "node:assert/strict";
import test from "node:test";
import { createSessionState } from "../src/session/state.js";
import { createFetchWithSession, REQUEST_TIMEOUT_MS, RequestTimeoutError } from "../src/session/request.js";

const settle = () => new Promise((resolve) => setImmediate(resolve));

/** A backend that takes the request and never answers; the request ends only when the page ends it. */
function silentBackend(t: import("node:test").TestContext): AbortSignal[] {
  const signals: AbortSignal[] = [];
  t.mock.method(globalThis, "fetch", (_url: unknown, init?: RequestInit) => {
    const signal = init?.signal as AbortSignal;
    signals.push(signal);
    return new Promise((_resolve, reject) => {
      signal.addEventListener("abort", () => reject(signal.reason));
    });
  });
  return signals;
}

test("a request no answer has begun for in 90 s fails as a timeout, in words the page can show, which trying again can help", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  silentBackend(t);
  const reading = createFetchWithSession(createSessionState())("/api/eneo/flows/");
  const failed = assert.rejects(reading, (error: unknown) => {
    assert.ok(error instanceof RequestTimeoutError);
    assert.equal(error.status, 408);
    assert.equal(error.message, "Det tog för lång tid att få svar. Försök igen.");
    return true;
  });
  await settle();
  t.mock.timers.tick(REQUEST_TIMEOUT_MS - 1);
  await settle();
  t.mock.timers.tick(1);
  await failed;
  assert.equal(REQUEST_TIMEOUT_MS, 90_000, "longer than the backend's own 60 s wait for Eneo");
});

test("a request the page itself aborts is an abort, not a timeout", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const signals = silentBackend(t);
  const own = new AbortController();
  const starting = createFetchWithSession(createSessionState())("/api/eneo/runs/", { method: "POST", signal: own.signal });
  await settle();
  assert.equal(signals[0].aborted, false);
  own.abort();
  await assert.rejects(starting, (error: unknown) => !(error instanceof RequestTimeoutError) && (error as Error).name === "AbortError");
  t.mock.timers.tick(2 * REQUEST_TIMEOUT_MS);
  await settle();
});

test("a request that is answered leaves no timer behind", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const signals: AbortSignal[] = [];
  t.mock.method(globalThis, "fetch", async (_url: unknown, init?: RequestInit) => {
    signals.push(init?.signal as AbortSignal);
    return new Response("{}", { status: 200, headers: { "content-type": "application/json" } });
  });
  const answer = await createFetchWithSession(createSessionState())("/api/eneo/flows/");
  assert.equal(answer.status, 200);
  t.mock.timers.tick(REQUEST_TIMEOUT_MS);
  assert.equal(signals[0].aborted, false, "the answered request is not aborted afterwards");
});
