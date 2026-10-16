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

/** The declarations of one class in the built theme (the first rule for it, outside or inside the coarse-pointer rule). */
const rule = (css: string, selector: string) => css.match(new RegExp(`\\.${selector} \\{([^}]*)\\}`))?.[1] ?? "";

test("an off switch's track is a control's edge (3:1 on the page and under its surface-coloured thumb, contrast.test.ts), not the design system's 1.5:1 grey", () => {
  assert.match(rule(built, "astryx-switch"), /--color-background-gray: var\(--color-border-emphasized\)/);
});

test("under a finger a text area is a 44 px target too, however few lines it has", () => {
  const coarse = built.slice(built.indexOf("@media (pointer: coarse)"));
  assert.match(rule(coarse, "astryx-text-area-control"), /min-block-size: 44px/);
});

test("a table too wide for its column shows that it scrolls, with shadows at the edge that has more, and a header cell wraps instead of losing its words", () => {
  const scroll = rule(built, "astryx-table-scroll-wrapper");
  assert.match(scroll, /background-image: linear-gradient/);
  assert.match(scroll, /background-attachment: local, local, scroll, scroll/);
  const header = rule(built, "astryx-table-header-cell");
  assert.match(header, /white-space: normal/);
  assert.match(header, /text-overflow: clip/);
});

test("a heading that wraps balances its lines, so a phone does not leave one word alone on the last", () => {
  assert.match(rule(built, "astryx-heading"), /text-wrap: balance/);
});

const base = readFileSync("src/base.css", "utf8");
const block = (css: string, opening: string) => {
  const at = css.indexOf(opening);
  assert.ok(at >= 0, `base.css has ${opening}`);
  let depth = 0;
  for (let end = css.indexOf("{", at); end < css.length; end++) {
    if (css[end] === "{") depth++;
    if (css[end] === "}" && --depth === 0) return css.slice(at, end + 1);
  }
  return "";
};

test("with reduced motion nothing scrolls smoothly and the spinner and the progress bar stand still: the words beside them say what goes on", () => {
  const reduced = block(base, "@media (prefers-reduced-motion: reduce)");
  assert.match(reduced, /scroll-behavior: auto !important/);
  assert.match(reduced, /\.astryx-spinner circle,\s*\.astryx-progress-bar-fill \{ animation: none; \}/);
});

test("in forced colours a progress bar keeps its track and its filled part, which are backgrounds only", () => {
  const forced = base.split("@media (forced-colors: active)").slice(1).join("");
  assert.match(forced, /\.astryx-progress-bar-track \{[^}]*outline: [^}]*ButtonText/);
  assert.match(forced, /\.astryx-progress-bar-fill \{[^}]*background: Highlight/);
});

test("on an iPhone or iPad the text follows the size set in iOS, in the reset layer, where the theme still wins", () => {
  const dynamicType = block(base, "@supports (font: -apple-system-body) and (-webkit-touch-callout: none)");
  assert.match(dynamicType, /html \{[^}]*font: -apple-system-body/);
  assert.ok(base.lastIndexOf("@layer reset {", base.indexOf("@supports (font: -apple-system-body)")) >= 0, "inside @layer reset");
});
