import assert from "node:assert/strict";
import test from "node:test";
import { resolveThemeTokens } from "@astryxdesign/core/theme/tokens";

// WCAG relative luminance of the built theme's resolved tokens. Alpha fills are composited over their surface.
type RGBA = [number, number, number, number];

function hslToRgb(h: number, s: number, l: number): RGBA {
  s /= 100; l /= 100;
  const a = s * Math.min(l, 1 - l);
  const channel = (n: number) => { const k = (n + h / 30) % 12; return l - a * Math.max(-1, Math.min(k - 3, 9 - k, 1)); };
  return [channel(0), channel(8), channel(4), 1];
}
function parseColor(value: string): RGBA {
  const text = value.trim();
  const hex = /^#([0-9a-f]{6})([0-9a-f]{2})?$/i.exec(text);
  if (hex) return [0, 2, 4].map((i) => parseInt(hex[1].slice(i, i + 2), 16) / 255).concat(hex[2] ? parseInt(hex[2], 16) / 255 : 1) as RGBA;
  const rgb = /^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:[,\s/]+([\d.]+))?\s*\)$/.exec(text);
  if (rgb) return [Number(rgb[1]) / 255, Number(rgb[2]) / 255, Number(rgb[3]) / 255, rgb[4] === undefined ? 1 : Number(rgb[4])];
  const hsl = /^hsl\(\s*([\d.]+)(?:deg)?[,\s]+([\d.]+)%[,\s]+([\d.]+)%\s*\)$/.exec(text);
  if (hsl) return hslToRgb(Number(hsl[1]), Number(hsl[2]), Number(hsl[3]));
  assert.fail(`not a colour this test reads: ${value}`);
}
const over = (foreground: RGBA, background: RGBA): RGBA => {
  const alpha = foreground[3];
  return [0, 1, 2].map((i) => foreground[i] * alpha + background[i] * (1 - alpha)).concat(1) as RGBA;
};
function contrast(a: RGBA, b: RGBA) {
  const luminance = (rgb: RGBA) => rgb.slice(0, 3).map((v) => v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4)
    .reduce((sum, v, i) => sum + v * [.2126, .7152, .0722][i], 0);
  const [high, low] = [luminance(a), luminance(b)].sort((a, b) => b - a);
  return (high + .05) / (low + .05);
}

for (const mode of ["light", "dark"] as const) {
  async function palette() {
    const { eneoTheme } = await import("../src/theme/built/eneo.js");
    const tokens = resolveThemeTokens(eneoTheme, { mode });
    const token = (name: string) => parseColor(tokens[name]);
    const surface = token("--color-background-surface");
    const grounds = { surface, body: token("--color-background-body"), muted: over(token("--color-background-muted"), surface) };
    const atLeast = (minimum: number, foreground: RGBA, background: RGBA, what: string) => {
      const ratio = contrast(foreground, background);
      assert.ok(ratio >= minimum, `${mode} ${what}: ${ratio.toFixed(2)} < ${minimum}`);
    };
    return { token, grounds, atLeast };
  }

  test(`${mode}: primary, secondary, accent and error text meet AA on their surfaces`, async () => {
    const { token, grounds, atLeast } = await palette();
    for (const foreground of ["--color-text-primary", "--color-text-secondary", "--color-text-accent", "--color-error"]) {
      for (const [ground, background] of Object.entries(grounds)) atLeast(4.5, token(foreground), background, `${foreground} on ${ground}`);
    }
    atLeast(4.5, token("--color-on-accent"), token("--color-accent"), "on-accent on accent");
    atLeast(4.5, token("--color-on-error"), token("--color-error"), "on-error on error");
  });

  test(`${mode}: control edges and keyboard focus meet AA on their surfaces`, async () => {
    const { token, grounds, atLeast } = await palette();
    for (const [ground, background] of Object.entries(grounds)) atLeast(3, token("--color-border-emphasized"), background, `control edge on ${ground}`);
    for (const ground of ["surface", "body"] as const) atLeast(3, token("--focus-outline-color"), grounds[ground], `focus ring on ${ground}`);
  });
}
