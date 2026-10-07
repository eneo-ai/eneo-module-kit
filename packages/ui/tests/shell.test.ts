import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { createElement } from "react";
import { cleanup, installDom, mount } from "./test-dom.js";

installDom();
afterEach(cleanup);

test("the shell gives a page its skip link, a named navigation landmark and exactly one main region", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { ModuleShell } = await import("../src/ModuleShell.js");
  const view = await mount(
    createElement(ModuleProviders, { children: createElement(ModuleShell, { label: "Tal till text", heading: "Tal till text", end: "Konto", children: "Sidan" }) }),
  );
  assert.equal(view.container.querySelectorAll('[role="main"], main').length, 1, "one main region");
  assert.ok(view.container.querySelector('nav[aria-label="Tal till text"]'), "a navigation landmark named by `label`");
  assert.match(view.container.textContent ?? "", /Hoppa till innehåll/);
  assert.match(view.container.textContent ?? "", /Sidan/);
  assert.match(view.container.textContent ?? "", /Konto/, "what the page puts at the bar's end");
});

test("a notice for the whole page comes with the shell, and the bar can fill the window", async () => {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { ModuleShell } = await import("../src/ModuleShell.js");
  const view = await mount(
    createElement(ModuleProviders, {
      children: createElement(ModuleShell, { label: "Tal till text", heading: "Tal till text", banner: createElement("p", { role: "status" }, "Du är offline."), height: "fill", start: "Flödet", children: "Sidan" }),
    }),
  );
  assert.match(view.container.textContent ?? "", /Du är offline\./);
  assert.match(view.container.textContent ?? "", /Flödet/);
  assert.equal(view.container.querySelectorAll('[role="main"], main').length, 1);
});
