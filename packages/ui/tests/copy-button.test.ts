import assert from "node:assert/strict";
import test, { afterEach } from "node:test";
import { createElement } from "react";
import { cleanup, installDom, mount, useClipboard } from "./test-dom.js";

installDom();
afterEach(cleanup);

async function copyButton(props: { name?: string } = {}) {
  const { CopyButton } = await import("../src/CopyButton.js");
  const view = await mount(createElement(CopyButton, { text: "Texten", label: "Kopiera", ...props }));
  const control = () => view.container.querySelector("button")!;
  const press = () =>
    view.act(async () => {
      control().click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  const announced = () => document.querySelector('[data-astryx-live-region="polite"]')?.textContent ?? "";
  return { ...view, control, press, announced };
}

test("a copy keeps the button's words and its name, which starts with them, and says Kopierat once", async (t) => {
  const written: string[] = [];
  useClipboard(t, { writeText: async (text) => void written.push(text) });
  const { control, press, announced } = await copyButton({ name: "Kopiera supportinformationen" });
  assert.equal(control().textContent, "Kopiera");
  assert.equal(control().getAttribute("aria-label"), "Kopiera supportinformationen");

  await press();
  await new Promise(requestAnimationFrame);
  assert.deepEqual(written, ["Texten"]);
  assert.equal(control().textContent, "Kopiera", "the words stay, so the button keeps its width");
  assert.equal(control().getAttribute("aria-label"), "Kopiera supportinformationen", "and its name");
  assert.equal(announced(), "Kopierat");
});

test("a clipboard that refuses, or is not there, says so in words, and the next press tries again", async (t) => {
  useClipboard(t, undefined);
  const { control, press, announced } = await copyButton();

  await press();
  await new Promise(requestAnimationFrame);
  assert.equal(control().textContent, "Kunde inte kopiera");
  assert.equal(announced(), "Det gick inte att kopiera.");

  const written: string[] = [];
  Object.defineProperty(navigator, "clipboard", { value: { writeText: async (text: string) => void written.push(text) }, configurable: true });
  await press();
  assert.deepEqual(written, ["Texten"]);
  assert.equal(control().textContent, "Kopiera");
});
