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

test("a layer opened inside the providers writes no <style> of its own, which the strict policy refuses: base.css has its rules", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { Popover } = await import("@astryxdesign/core/Popover");
  const popover = createElement(Popover, { isOpen: true, onOpenChange() {}, content: "Mer", children: createElement("button", { type: "button" }, "Visa") });
  await mount(createElement(ModuleProviders, { children: popover }));
  assert.equal(document.querySelectorAll("style").length, 0, [...document.querySelectorAll("style")].map((style) => style.id || style.outerHTML.slice(0, 80)).join(", "));
});

test("the design system's words a page can show are Swedish, also those its Swedish catalog lacks", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { useTranslator } = await import("@astryxdesign/core/i18n");
  const { default: english } = (await import("@astryxdesign/core/locales/en.json", { with: { type: "json" } })) as { default: Record<string, { defaultMessage: string }> };
  // A scrolling region's name (a dialog's or a page's), a search field's clear button, a failed copy of a code block, a typed 30 February.
  const keys = ["@astryx.scrollRegion.label", "@astryx.inputClearButton.tooltip", "@astryx.codeBlock.copyFailed", "@astryx.dateInput.nonexistentDate"];
  const said = new Map<string, string>();
  function Probe() {
    const translate = useTranslator();
    for (const key of keys) said.set(key, translate(key, { calendar: "Gregorian Calendar" }));
    return null;
  }
  await mount(createElement(ModuleProviders, { children: createElement(Probe) }));
  for (const key of keys) assert.notEqual(said.get(key), english[key].defaultMessage.replace("{calendar}", "Gregorian Calendar"), key);
});
