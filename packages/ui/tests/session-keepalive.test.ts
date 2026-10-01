// Carried over from speech-to-text's session-keepalive.test.ts.
import assert from "node:assert/strict";
import { mock, test } from "node:test";
import { keepSessionAlive } from "../src/session/keepalive.js";
import type { SessionStatus } from "../src/session/types.js";

const signedIn = (refresh_in?: number): SessionStatus => ({
  authenticated: true,
  user: { id: "user-id", email: "user@example.test" },
  ...(refresh_in === undefined ? {} : { refresh_in }),
});

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("a one-minute token is checked inside its refresh window, one check at a time", async () => {
  mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  const answers: Array<(status: SessionStatus) => void> = [];
  const stop = keepSessionAlive(signedIn(30), () => new Promise((resolve) => answers.push(resolve)));
  try {
    mock.timers.tick(30_000);
    assert.equal(answers.length, 0);
    mock.timers.tick(1_000);
    assert.equal(answers.length, 1, "checked at 31 s, before the token ends at 60 s");

    mock.timers.tick(5 * 60_000);
    assert.equal(answers.length, 1, "no second check while the first is unanswered");

    answers[0](signedIn(30));
    await settle();
    mock.timers.tick(31_000);
    assert.equal(answers.length, 2);
  } finally {
    stop();
    mock.timers.reset();
  }
});

test("nothing is polled without a token to renew, and a failed check is retried", async () => {
  mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  let idleChecks = 0;
  const stopIdle = keepSessionAlive(signedIn(), async () => {
    idleChecks += 1;
    return signedIn();
  });
  let checks = 0;
  const stop = keepSessionAlive(signedIn(30), async () => {
    checks += 1;
    throw new Error("offline");
  });
  try {
    mock.timers.tick(31_000);
    await settle();
    assert.equal(checks, 1);
    mock.timers.tick(10_000);
    await settle();
    assert.equal(checks, 2, "retried soon after the network failed");

    mock.timers.tick(60 * 60_000);
    assert.equal(idleChecks, 0);
  } finally {
    stopIdle();
    stop();
    mock.timers.reset();
  }
});

test("a stopped keepalive asks no more, and an answer a later question replaced (null) schedules nothing", async () => {
  mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  let checks = 0;
  const stop = keepSessionAlive(signedIn(30), async () => {
    checks += 1;
    return null;
  });
  try {
    mock.timers.tick(31_000);
    await settle();
    assert.equal(checks, 1);
    mock.timers.tick(60 * 60_000);
    assert.equal(checks, 1, "null: replaced by a later question, which schedules for itself");
  } finally {
    stop();
    mock.timers.reset();
  }
  const stopped = keepSessionAlive(signedIn(30), async () => {
    checks += 1;
    return signedIn(30);
  });
  mock.timers.enable({ apis: ["setTimeout", "setInterval"] });
  stopped();
  mock.timers.tick(60 * 60_000);
  assert.equal(checks, 1);
  mock.timers.reset();
});
