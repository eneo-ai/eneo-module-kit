import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import { cleanup, installDom, mount } from "./test-dom.js";

const frames = (count: number) => new Promise<void>((resolve) => (function next(left: number) { left === 0 ? resolve() : requestAnimationFrame(() => next(left - 1)); })(count));

installDom();
afterEach(async () => {
  await cleanup();
  localStorage.clear();
  // A switch of the mode marks <html> until two animation frames have passed: the next test must not start with this
  // one's mark, nor have its own cleared by this one's frames.
  await frames(2);
});

/** The operating system's choice, as a test controls it: `matches` now, and `change` events to whoever listens. */
function operatingSystem(dark: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    get matches() {
      return dark;
    },
    media: "(prefers-color-scheme: dark)",
    addEventListener: (_: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
  };
  const matchMedia = (media: string) => (media.includes("prefers-color-scheme") ? query : { matches: false, media, addEventListener() {}, removeEventListener() {} });
  Object.defineProperty(window, "matchMedia", { value: matchMedia, configurable: true, writable: true });
  Object.defineProperty(globalThis, "matchMedia", { value: matchMedia, configurable: true, writable: true });
  return {
    choose(next: boolean) {
      dark = next;
      listeners.forEach((listener) => listener());
    },
    listening: () => listeners.size,
  };
}

async function load() {
  return import("../src/color-mode.js");
}

test("a stored light, dark or system is read as it is, and anything else is system", async () => {
  const { readStoredColorMode } = await load();
  const storage = (value: string | null) => ({ getItem: () => value }) as unknown as Storage;
  for (const mode of ["light", "dark", "system"] as const) assert.equal(readStoredColorMode(storage(mode)), mode);
  for (const value of [null, "", "Dark", "auto", "dark "]) assert.equal(readStoredColorMode(storage(value)), "system", String(value));
  const blocked = {
    getItem() {
      throw new Error("blocked");
    },
  } as unknown as Storage;
  assert.equal(readStoredColorMode(blocked), "system", "storage that throws (a private window, blocked site data) is no choice");
});

test("the stored mode is the one on the first render, so no frame is drawn in the other", async () => {
  const { ColorModeProvider, useColorMode } = await load();
  operatingSystem(false);
  localStorage.setItem("theme", "dark");
  const seen: string[] = [];
  function Probe() {
    seen.push(useColorMode().mode);
    return null;
  }
  await mount(createElement(ColorModeProvider, { children: createElement(Probe) }));
  assert.ok(seen.length > 0);
  assert.deepEqual([...new Set(seen)], ["dark"], "every render, the first included, had the stored mode");
});

test("with nothing stored the mode is system, which follows the operating system, and its changes", async () => {
  const { ColorModeProvider, useColorMode } = await load();
  const system = operatingSystem(true);
  let current: ReturnType<typeof useColorMode> | undefined;
  function Probe() {
    current = useColorMode();
    return null;
  }
  const view = await mount(createElement(ColorModeProvider, { children: createElement(Probe) }));
  assert.equal(current?.mode, "system");
  assert.equal(current?.resolved, "dark");
  await view.act(async () => system.choose(false));
  assert.equal(current?.resolved, "light", "the system's change reaches the page");
  await view.unmount();
  assert.equal(system.listening(), 0, "and the listener goes with the provider");
});

test("a chosen mode ignores the operating system, and is written back for the next visit", async () => {
  const { ColorModeProvider, useColorMode } = await load();
  operatingSystem(true);
  let current: ReturnType<typeof useColorMode> | undefined;
  function Probe() {
    current = useColorMode();
    return null;
  }
  const view = await mount(createElement(ColorModeProvider, { children: createElement(Probe) }));
  await view.act(async () => current?.setMode("light"));
  assert.deepEqual([current?.mode, current?.resolved], ["light", "light"]);
  assert.equal(localStorage.getItem("theme"), "light");
  await view.act(async () => current?.setMode("system"));
  assert.deepEqual([current?.mode, current?.resolved, localStorage.getItem("theme")], ["system", "dark", "system"]);
});

test("a choice that cannot be stored still applies for the visit", async () => {
  const { ColorModeProvider, useColorMode } = await load();
  operatingSystem(false);
  const setItem = Storage.prototype.setItem;
  Storage.prototype.setItem = () => {
    throw new Error("quota");
  };
  try {
    let current: ReturnType<typeof useColorMode> | undefined;
    function Probe() {
      current = useColorMode();
      return null;
    }
    const view = await mount(createElement(ColorModeProvider, { children: createElement(Probe) }));
    await view.act(async () => current?.setMode("dark"));
    assert.equal(current?.mode, "dark");
  } finally {
    Storage.prototype.setItem = setItem;
  }
});

test("another tab's choice reaches this one", async () => {
  const { ColorModeProvider, useColorMode } = await load();
  operatingSystem(false);
  let current: ReturnType<typeof useColorMode> | undefined;
  function Probe() {
    current = useColorMode();
    return null;
  }
  const view = await mount(createElement(ColorModeProvider, { children: createElement(Probe) }));
  assert.equal(current?.mode, "system");
  localStorage.setItem("theme", "dark");
  await view.act(async () => void window.dispatchEvent(new window.StorageEvent("storage", { key: "theme", newValue: "dark" })));
  assert.equal(current?.mode, "dark");
  await view.act(async () => void window.dispatchEvent(new window.StorageEvent("storage", { key: "other", newValue: "light" })));
  assert.equal(current?.mode, "dark", "another key is none of its business");
});

test("the hook says so when there is no provider above it", async () => {
  const { useColorMode } = await load();
  function Probe() {
    useColorMode();
    return null;
  }
  await assert.rejects(() => mount(createElement(Probe)), /ColorModeProvider/);
});

// A switch of the mode must not animate: the surfaces and the text change at once, so controls that fade over 175 ms
// (the design system's transitions) would lag behind them. For the frames that apply the new mode, `<html>` carries
// `data-theme-switching`, which one static rule in base.css answers with `transition: none`.
const switching = () => document.documentElement.hasAttribute("data-theme-switching");

test("a chosen mode marks the document as switching for the frames that apply it, and no longer", async () => {
  const { ColorModeProvider, useColorMode } = await load();
  operatingSystem(false);
  let current: ReturnType<typeof useColorMode> | undefined;
  function Probe() {
    current = useColorMode();
    return null;
  }
  const view = await mount(createElement(ColorModeProvider, { children: createElement(Probe) }));
  assert.equal(switching(), false, "not on the first render");
  await view.act(async () => current?.setMode("dark"));
  assert.equal(switching(), true, "from the choice, before the page shows the new mode");
  await view.act(async () => frames(4));
  assert.equal(switching(), false, "and over a frame or two later");
});

test("the operating system's change and another tab's choice mark it too, from the event, before React has rendered", async () => {
  const { ColorModeProvider, useColorMode } = await load();
  const system = operatingSystem(false);
  let current: ReturnType<typeof useColorMode> | undefined;
  function Probe() {
    current = useColorMode();
    return null;
  }
  const view = await mount(createElement(ColorModeProvider, { children: createElement(Probe) }));
  system.choose(true); // outside act: the event itself, no render yet
  assert.equal(switching(), true, "the system's change");
  await view.act(async () => frames(4));
  assert.equal(switching(), false);
  localStorage.setItem("theme", "dark");
  window.dispatchEvent(new window.StorageEvent("storage", { key: "theme", newValue: "dark" }));
  assert.equal(switching(), true, "another tab's choice");
  await view.act(async () => frames(4));
  assert.equal(current?.mode, "dark");
  assert.equal(switching(), false);
});

test("an event that changes nothing marks nothing: the same mode again, the same system answer, another key", async () => {
  const { ColorModeProvider, useColorMode } = await load();
  const system = operatingSystem(true);
  localStorage.setItem("theme", "dark");
  let current: ReturnType<typeof useColorMode> | undefined;
  function Probe() {
    current = useColorMode();
    return null;
  }
  const view = await mount(createElement(ColorModeProvider, { children: createElement(Probe) }));
  await view.act(async () => current?.setMode("dark"));
  assert.equal(switching(), false, "dark chosen while dark");
  system.choose(true);
  assert.equal(switching(), false, "the system says what it said");
  window.dispatchEvent(new window.StorageEvent("storage", { key: "other", newValue: "x" }));
  assert.equal(switching(), false, "another key");
});

test("one static rule of base.css turns every transition off while the document is switching", () => {
  assert.match(readFileSync("src/base.css", "utf8"), /\[data-theme-switching\] \*[^{]*\{[^}]*transition:\s*none\s*!important/);
});
