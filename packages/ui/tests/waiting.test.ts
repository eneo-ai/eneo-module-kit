import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { button, cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(cleanup);

const SLOW = "Det tar längre tid än vanligt.";

test("the page while it waits: the bar, a heading that names the module, and a spinner that says so", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { LoadingShell } = await import("../src/LoadingShell.js");
  const { container } = await mount(createElement(ModuleProviders, { children: createElement(LoadingShell, { productName: "Testmodul" }) }));
  assert.ok(container.querySelector('nav[aria-label="Testmodul"]'), "the bar");
  assert.deepEqual([...container.querySelectorAll("h1")].map((heading) => heading.textContent), ["Testmodul"]);
  assert.equal(container.querySelectorAll('main, [role="main"]').length, 1);
  assert.ok(container.querySelector('[aria-label="Laddar"]'), "a spinner named in Swedish");
});

test("the spinner shows only once the wait has lasted a moment: an answer within it leaves no blink of a spinner", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { LoadingShell } = await import("../src/LoadingShell.js");
  const { container } = await mount(createElement(ModuleProviders, { children: createElement(LoadingShell, { productName: "Testmodul" }) }));
  assert.ok(container.querySelector('.eneo-wait [aria-label="Laddar"]'), "the spinner is inside what base.css holds back");
  const base = readFileSync("src/base.css", "utf8");
  assert.match(base, /\.eneo-wait \{[^}]*animation: eneo-wait-hidden 0s \d+ms backwards/);
  assert.match(base, /@keyframes eneo-wait-hidden \{\s*from \{\s*visibility: hidden;/);
});

test("the session's gate waits in the same shell", async (t) => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { RequireSession } = await import("../src/session/RequireSession.js");
  const { createSessionState } = await import("../src/session/state.js");
  const browserFetch = globalThis.fetch;
  globalThis.fetch = (() => new Promise(() => undefined)) as typeof fetch;
  t.after(() => {
    globalThis.fetch = browserFetch;
  });
  const { container } = await mount(
    createElement(ModuleProviders, { children: createElement(RequireSession, { productName: "Testmodul", state: createSessionState(), children: "Sidan" }) }),
  );
  assert.ok(container.querySelector('.eneo-wait [aria-label="Laddar"]'));
  assert.doesNotMatch(container.textContent ?? "", /Sidan/);
});

async function slowWait(children?: unknown) {
  const { SlowWait } = await import("../src/SlowWait.js");
  let retries = 0;
  const view = await mount(createElement(SlowWait, { onRetry: () => (retries += 1), children: children as never }));
  const status = () => [...view.container.querySelectorAll('[role="status"]')].map((region) => region.textContent).filter(Boolean);
  return { ...view, status, retries: () => retries };
}

test("a wait that goes on says so after 15 seconds, with a way on; before that it says nothing", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { container, act, status } = await slowWait(createElement("a", { href: "/" }, "Till startsidan"));
  assert.equal(container.textContent, "", "nothing before the wait is long");
  const region = container.querySelector('[role="status"]');
  assert.ok(region, "the status region is there before its words, so they are read out when they come");

  await act(async () => t.mock.timers.tick(15_000 - 1));
  assert.equal(container.textContent, "");

  await act(async () => t.mock.timers.tick(1));
  assert.deepEqual(status(), [SLOW], "said once, in a status region");
  assert.equal(region.textContent, SLOW, "in the region that was there from the start");
  assert.ok(button(container, "Försök igen"));
  assert.equal(container.querySelector('a[href="/"]')?.textContent, "Till startsidan", "and the page's other ways on beside it");
});

test("Försök igen tries again, keeps focus where it was, says so, and the wait is judged again from there", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { container, act, status, retries } = await slowWait();
  await act(async () => t.mock.timers.tick(15_000));
  const retry = button(container, "Försök igen")!;
  retry.focus();

  await act(async () => retry.click());
  assert.equal(retries(), 1);
  assert.deepEqual(status(), ["Försöker igen."]);
  assert.equal(document.activeElement === button(container, "Försök igen"), true, "the press does not take the focus away");

  await act(async () => t.mock.timers.tick(15_000));
  assert.deepEqual(status(), [SLOW], "still no answer: said again");
});
