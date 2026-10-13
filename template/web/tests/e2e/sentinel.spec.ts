/**
 * The sentinel (fixtures.ts) fails a test for a policy violation, a redirect, and a console error or failed request that
 * was not declared, and for a declared one that did not happen. These tests cause each of them and look at what the
 * sentinel saw, then clear it: a sentinel that stopped seeing would make every other test pass for nothing. They run in
 * Chromium (the `chromium` project); the other engines' words for a failure are proved by the specs that run there.
 * Adapted from speech-to-text's (`eneo-ai/eneo-mod-speech-to-text` at commit `b8c3804`).
 */
import { expect, test } from "./fixtures";

test("a policy violation is seen: an inline style and an inline script", async ({ page, sentinel }) => {
  await page.goto("/");
  await page.evaluate(() => {
    document.head.append(Object.assign(document.createElement("style"), { textContent: "a { color: red }" }));
    document.body.append(Object.assign(document.createElement("script"), { textContent: "window.inlineRan = true" }));
  });
  await expect.poll(() => sentinel.violations.length).toBeGreaterThanOrEqual(2);
  expect(sentinel.violations.join("\n")).toMatch(/style-src-elem/);
  expect(sentinel.violations.join("\n")).toMatch(/script-src-elem/);
  expect(await page.evaluate(() => (window as unknown as { inlineRan?: boolean }).inlineRan), "and the policy stopped the script").toBeUndefined();
  sentinel.reset();
});

test("a redirect is seen, and the sign-in handshake's is not", async ({ page, sentinel }) => {
  await page.goto("/");
  await page.route("**/somewhere", (route) => route.fulfill({ status: 302, headers: { location: "/" } }));
  await page.evaluate(() => fetch("/somewhere"));
  await expect.poll(() => sentinel.redirects.length).toBe(1);
  expect(sentinel.redirects[0]).toMatch(/^302 GET .*\/somewhere to \/$/);
  await page.goto("/api/auth/login?next=%2Fflows");
  await expect(page).toHaveURL(/\/flows$/);
  expect(sentinel.redirects, "the handshake went through redirects of its own and added none").toHaveLength(1);
  sentinel.reset();
});

test("a console error and a failed request fail unless declared, a declared one that did not happen fails, and a cancelled request is none", async ({ page, sentinel }) => {
  await page.goto("/");
  await page.route("**/api/nope", (route) => route.abort());
  await page.route("**/api/cancelled", (route) => route.abort("aborted"));
  await page.evaluate(async () => {
    console.error("boom");
    await fetch("/api/nope").catch(() => undefined);
    await fetch("/api/cancelled").catch(() => undefined);
  });
  await expect.poll(() => sentinel.verify().unexpectedFailed.length).toBe(1);
  expect(sentinel.verify().unexpectedFailed[0], "the abort of the network is a failure; the browser's own cancel is not").toMatch(/GET .*\/api\/nope: net::ERR_FAILED/);
  expect(sentinel.verify().unexpectedConsole.some((line) => line.startsWith("boom"))).toBe(true);

  sentinel.expect({ console: /^boom/ }, { requestFailed: /GET .*\/api\/nope: net::ERR_FAILED/ }, { console: /may or may not/, optional: true });
  const declared = sentinel.verify();
  expect(declared.unexpectedFailed).toEqual([]);
  expect(declared.unexpectedConsole.filter((line) => line.startsWith("boom"))).toEqual([]);
  expect(declared.missing, "what was declared happened, and an optional one need not").toEqual([]);

  sentinel.expect({ console: /never happens/ });
  expect(sentinel.verify().missing).toEqual(["/never happens/"]);
  sentinel.reset();
});
