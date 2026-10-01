import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { createElement } from "react";
import { cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(async () => {
  await cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-astryx-theme");
});

async function shell(extra: Record<string, unknown> = {}) {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { ModuleShell } = await import("../src/ModuleShell.js");
  return mount(
    createElement(ModuleProviders, { ...extra, children: createElement(ModuleShell, { label: "Tal till text", heading: "Tal till text", end: "Konto", children: "Sidan" }) }),
  );
}

test("a page is themed with the Eneo theme and speaks Swedish where the design system speaks", async () => {
  const view = await shell();
  assert.ok(view.container.querySelector('[data-astryx-theme="eneo"]'), "the built Eneo theme is the page's");
  assert.match(view.container.textContent ?? "", /Hoppa till innehåll/, "the skip link is in the Swedish catalog");
});

test("the stored colour mode is the Theme's mode from the first render; with none, system", async () => {
  const system = await shell();
  const root = system.container.querySelector<HTMLElement>("[data-astryx-theme]")!;
  assert.equal(root.getAttribute("data-theme"), null, "system leaves the choice to the browser");
  await system.unmount();

  localStorage.setItem("theme", "dark");
  const dark = await shell();
  assert.equal(dark.container.querySelector("[data-astryx-theme]")?.getAttribute("data-theme"), "dark");
  assert.equal(document.documentElement.getAttribute("data-theme"), "dark", "and the design system tells the document, for the browser's own controls");
  await dark.unmount();

  localStorage.setItem("theme", "light");
  const light = await shell();
  assert.equal(light.container.querySelector("[data-astryx-theme]")?.getAttribute("data-theme"), "light");
});

test("a link component given to the providers is the one the design system's links use", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { Link } = await import("@astryxdesign/core/Link");
  const Custom = ({ href, children, ...rest }: { href: string; children?: unknown }) =>
    createElement("a", { ...rest, href, "data-custom-link": "" }, children as never);
  const view = await mount(createElement(ModuleProviders, { linkComponent: Custom as never, children: createElement(Link, { href: "/flows", children: "Flöden" }) }));
  assert.ok(view.container.querySelector('a[data-custom-link][href="/flows"]'), "the app's own router link");
});

test("a toast is hosted inside the providers, so its words are Swedish, not in a root of its own that speaks English", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { useToast } = await import("@astryxdesign/core/Toast");
  const { useEffect } = await import("react");
  function Notifier() {
    const toast = useToast();
    useEffect(() => toast({ type: "error", body: "Det gick inte att logga ut. Försök igen." }), [toast]);
    return null;
  }
  await mount(createElement(ModuleProviders, { children: createElement(Notifier) }));
  assert.ok(!document.querySelector("[data-astryx-toast-fallback]"), "no fallback viewport outside the providers");
  assert.ok(document.querySelector('[aria-label="Aviseringar"]'), "the viewport is named in Swedish");
  assert.match(document.body.textContent ?? "", /Det gick inte att logga ut/);
});
