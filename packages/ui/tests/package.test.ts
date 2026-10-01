import assert from "node:assert/strict";
import test from "node:test";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const sources = (dir: string): string[] =>
  readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return entry.name === "built" ? [] : sources(path);
    return /\.tsx?$/.test(entry.name) ? [path] : [];
  });

test("the package imports nothing from a router, a meta-framework, next-themes or the template", () => {
  const forbidden = /from "(?:react-router[^"]*|next(?:\/[^"]*)?|next-themes|@remix-run\/[^"]*|\.\.?\/(?:\.\.\/)*template[^"]*)"/;
  for (const file of sources("src")) assert.doesNotMatch(readFileSync(file, "utf8"), forbidden, file);
});

test("the package imports no stylesheet from its code: a tsc-built library cannot count on the consumer's bundler", () => {
  for (const file of sources("src")) assert.doesNotMatch(readFileSync(file, "utf8"), /import\s+(?:[\w{}\s*,]+\s+from\s+)?["'][^"']+\.css["']/, file);
});

test("Astryx and StyleX are pinned exactly, in the peers and in what the package builds against (K11)", () => {
  const manifest = JSON.parse(readFileSync("package.json", "utf8"));
  const exact = /^\d+\.\d+\.\d+$/;
  for (const section of ["peerDependencies", "devDependencies"] as const) {
    for (const name of ["@astryxdesign/core", "@stylexjs/stylex"]) assert.match(manifest[section][name], exact, `${section} ${name}`);
  }
  assert.match(manifest.devDependencies["@astryxdesign/cli"], exact);
  assert.equal(manifest.peerDependencies["@astryxdesign/core"], manifest.devDependencies["@astryxdesign/cli"], "the CLI is the core's own version");
});

test("every file the package exports is one the build writes", () => {
  const manifest = JSON.parse(readFileSync("package.json", "utf8"));
  const built = readFileSync("scripts/build.mjs", "utf8");
  for (const [name, target] of Object.entries<string | { default: string }>(manifest.exports)) {
    const file = (typeof target === "string" ? target : target.default).replace("./dist/", "");
    if (file.endsWith(".css")) assert.ok(built.includes(`"dist/${file}"`), `${name}: ${file} is copied by the build`);
    else assert.match(file, /^(?:session\/)?index\.js$/, `${name}: the code is tsc's`);
  }
});
