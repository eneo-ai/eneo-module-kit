import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { createElement } from "react";
import { cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(cleanup);

/** A browser window whose connection the test switches (jsdom's EventTarget, for jsdom's Event). */
function fakeBrowser(onLine: boolean) {
  const target = Object.assign(new window.EventTarget(), { navigator: { onLine } });
  return {
    target: target as import("../src/online-status.js").OnlineTarget,
    go(online: boolean) {
      target.navigator.onLine = online;
      target.dispatchEvent(new Event(online ? "online" : "offline"));
    },
  };
}

test("the browser's online events and the page's own requests decide whether it is online", async () => {
  const { createOnlineStatus } = await import("../src/online-status.js");
  const browser = fakeBrowser(true);
  const status = createOnlineStatus(browser.target);
  const heard: boolean[] = [];
  status.subscribe((online) => heard.push(online));
  assert.equal(status.online, true);

  browser.go(false);
  assert.equal(status.online, false);
  browser.go(true);
  assert.equal(status.online, true);

  // Connected to a network that does not reach the module.
  status.reportNetworkFailure();
  assert.equal(status.online, false);
  status.reportNetworkFailure();
  status.reportReachable();
  assert.equal(status.online, true);

  status.reportNetworkFailure();
  browser.go(false);
  browser.go(true);
  assert.equal(status.online, true, "the connection coming back clears an earlier failure");

  // The last change of cause, from a module that does not answer to a device with no network, is heard too.
  assert.deepEqual(heard, [false, true, false, true, false, false, true], "each change is heard once");
  assert.equal(createOnlineStatus(fakeBrowser(false).target).online, false, "a page opened offline starts offline");
});

test("a device with no network and a module that does not answer are told apart", async () => {
  const { createOnlineStatus } = await import("../src/online-status.js");
  const browser = fakeBrowser(true);
  const status = createOnlineStatus(browser.target);
  assert.equal(status.connection, "online");

  browser.go(false);
  assert.equal(status.connection, "offline", "the browser says there is no network");
  browser.go(true);
  assert.equal(status.connection, "online");

  status.reportNetworkFailure();
  assert.equal(status.connection, "unreachable", "the browser has a network, and the request did not reach the module");
  status.reportReachable();
  assert.equal(status.connection, "online");

  // A failure while the device has no network is the device's loss, not the module's.
  browser.go(false);
  status.reportNetworkFailure();
  assert.equal(status.connection, "offline");
  browser.go(true);
  assert.equal(status.connection, "online", "the network coming back clears it");
  assert.equal(createOnlineStatus(fakeBrowser(false).target).connection, "offline");
});

test("an answer from the module outweighs a browser that says there is no network", async () => {
  const { createOnlineStatus } = await import("../src/online-status.js");
  // Safari can go on saying offline after a device wakes, while every request reaches the module.
  const browser = fakeBrowser(false);
  const status = createOnlineStatus(browser.target);
  const heard: boolean[] = [];
  status.subscribe((online) => heard.push(online));
  assert.equal(status.connection, "offline", "a page opened offline starts offline");

  status.reportReachable(status.sending());
  assert.equal(status.connection, "online", "the module answered, so the device has a network");
  assert.deepEqual(heard, [true], "and what waits for the connection hears it");

  browser.go(false);
  assert.equal(status.connection, "offline", "a network lost after that is still the browser's to say");
});

test("an answer to a request that left before the network went does not bring it back", async () => {
  const { createOnlineStatus } = await import("../src/online-status.js");
  let now = 0;
  const browser = fakeBrowser(true);
  const status = createOnlineStatus(browser.target, () => now);
  now = 100;
  const early = status.sending();
  now = 200;
  browser.go(false);
  now = 300;
  status.reportReachable(early);
  assert.equal(status.connection, "offline", "the answer was already on its way: it says nothing of the network now");

  // The page's own failure meanwhile is the device's loss, and an early answer clears nothing but that.
  status.reportNetworkFailure();
  status.reportReachable(early);
  assert.equal(status.connection, "offline");

  now = 400;
  status.reportReachable(status.sending());
  assert.equal(status.connection, "online", "a request that left after the browser said so, and was answered, says the browser is wrong");
});

test("a request through fetchWithSession says whether the module can be reached: a failed fetch is no answer, an error status is one", async (t) => {
  const { createOnlineStatus } = await import("../src/online-status.js");
  const { createSessionState } = await import("../src/session/state.js");
  const { createFetchWithSession } = await import("../src/session/request.js");
  const online = createOnlineStatus(fakeBrowser(true).target);
  const fetchWithSession = createFetchWithSession(createSessionState(), online);
  const browserFetch = globalThis.fetch;
  t.after(() => {
    globalThis.fetch = browserFetch;
  });

  globalThis.fetch = (async () => {
    throw new TypeError("Failed to fetch");
  }) as typeof fetch;
  await assert.rejects(fetchWithSession("/api/eneo/flows/"), TypeError);
  assert.equal(online.connection, "unreachable");

  globalThis.fetch = (async () => new Response("upstream down", { status: 502 })) as typeof fetch;
  assert.equal((await fetchWithSession("/api/eneo/flows/")).status, 502);
  assert.equal(online.connection, "online", "an error answer still means the module answered");

  // The page's own abort says nothing of the network.
  globalThis.fetch = (async () => {
    throw new DOMException("The operation was aborted.", "AbortError");
  }) as typeof fetch;
  await assert.rejects(fetchWithSession("/api/eneo/flows/"));
  assert.equal(online.connection, "online");
});

test("the page's one status follows the browser's own online and offline events", async () => {
  const { onlineStatus } = await import("../src/online-status.js");
  assert.equal(onlineStatus.connection, "online");
  window.dispatchEvent(new window.Event("offline"));
  assert.equal(onlineStatus.connection, "offline");
  window.dispatchEvent(new window.Event("online"));
  assert.equal(onlineStatus.connection, "online");
});

/** The banner over a status the test controls, inside the providers (the design system's banner needs its theme). */
async function banner(props: Record<string, unknown> = {}) {
  const { createOnlineStatus } = await import("../src/online-status.js");
  const { OfflineBanner } = await import("../src/OfflineBanner.js");
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const browser = fakeBrowser(true);
  const status = createOnlineStatus(browser.target);
  const view = await mount(createElement(ModuleProviders, { children: createElement(OfflineBanner, { productName: "Testmodul", status, ...props }) }));
  const alert = () => view.container.querySelector('[role="alert"]');
  return { ...view, browser, status, alert };
}

test("online the banner is nothing; without a network it says so as an alert, and that the module does not answer when the network does not reach it", async () => {
  const { container, act, browser, status, alert } = await banner();
  assert.equal(container.textContent, "", "nothing, and no room taken, while online");

  await act(async () => browser.go(false));
  assert.equal(alert()?.textContent?.includes("Ingen anslutning."), true);

  await act(async () => browser.go(true));
  assert.equal(alert(), null, "gone when the network is back");

  await act(async () => status.reportNetworkFailure());
  assert.equal(alert()?.textContent?.includes("Testmodul svarar inte just nu."), true, "the module's own name, not the network's fault");

  await act(async () => status.reportReachable());
  assert.equal(container.textContent, "");
});

test("a page says after the cause what waits for the connection", async () => {
  const { act, browser, status, alert } = await banner({ message: "Det du har skrivit finns kvar." });
  await act(async () => browser.go(false));
  assert.equal(alert()?.textContent?.includes("Ingen anslutning. Det du har skrivit finns kvar."), true);
  await act(async () => browser.go(true));
  await act(async () => status.reportNetworkFailure());
  assert.equal(alert()?.textContent?.includes("Testmodul svarar inte just nu. Det du har skrivit finns kvar."), true);
});

test("useConnection gives a page the cause, for what it offers while the connection is gone", async () => {
  const { createOnlineStatus, useConnection } = await import("../src/online-status.js");
  const browser = fakeBrowser(true);
  const status = createOnlineStatus(browser.target);
  const seen: string[] = [];
  function Probe() {
    seen.push(useConnection(status));
    return null;
  }
  const { act } = await mount(createElement(Probe));
  await act(async () => browser.go(false));
  await act(async () => browser.go(true));
  assert.deepEqual(seen, ["online", "offline", "online"]);
});
