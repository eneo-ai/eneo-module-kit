import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";

const built = readFileSync("src/theme/built/eneo.css", "utf8");

test("the built theme is the Eneo theme", async () => {
  const { eneoTheme } = await import("../src/theme/built/eneo.js");
  assert.equal(eneoTheme.name, "eneo");
  assert.match(built, /data-astryx-theme="eneo"/);
});

test("under a finger the design system's controls are 44 px, and a large one is 48 px at every pointer (the house bar, K11)", () => {
  // The coarse-pointer rule of the built theme is where the size tokens turn into 44 px.
  const coarse = built.match(/@media \(pointer: coarse\) \{[\s\S]*?:scope \{([^}]*)\}/);
  assert.ok(coarse, "the built theme has a coarse-pointer rule");
  for (const token of ["--size-element-sm", "--size-element-md"]) assert.match(coarse[1], new RegExp(`${token}: 44px`), token);
  assert.match(coarse[1], /--size-element-lg: 48px/);
  assert.match(built, /--size-element-lg: 48px/, "also with a mouse");
});

test("a text button's label wraps and the button grows, so a long Swedish word never reaches past a 320 px screen", () => {
  assert.match(built, /\.astryx-button \{[^}]*white-space: normal/);
});
