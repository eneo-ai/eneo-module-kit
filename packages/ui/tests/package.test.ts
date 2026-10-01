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

test("the development minimum the root names is one every locked tool accepts, and Node 22.13.0, the consumers' minimum, is not it", async () => {
  const semver = (await import("semver")).default;
  const root = JSON.parse(readFileSync("../../package.json", "utf8"));
  const lock = JSON.parse(readFileSync("../../package-lock.json", "utf8")) as { packages: Record<string, { engines?: { node?: string }; os?: string[]; cpu?: string[]; optional?: boolean }> };
  // What each package that is installed here asks of Node (the platform binaries of other systems are not installed).
  const asked = Object.entries(lock.packages)
    .filter(([name, entry]) => name !== "" && entry.engines?.node && !(entry.optional && (entry.os || entry.cpu)))
    .map(([name, entry]) => [name.replace(/^.*node_modules\//, ""), entry.engines!.node!] as const);
  assert.ok(asked.length > 100, "the lock was read");
  // The lowest release of each major the root allows must satisfy them all.
  const lowest = ["22.22.2", "24.15.0", "26.0.0"];
  for (const version of lowest) {
    assert.ok(semver.satisfies(version, root.engines.node), `${version} is allowed by the root's engines`);
    const refused = asked.filter(([, range]) => !semver.satisfies(version, range)).map(([name, range]) => `${name} ${range}`);
    assert.deepEqual(refused, [], `locked tools that refuse Node ${version}`);
  }
  // And the root does not allow what a tool refuses: 22.13.0 and 24.12.0 are out.
  for (const version of ["22.13.0", "22.22.1", "24.12.0", "25.0.0"]) assert.equal(semver.satisfies(version, root.engines.node), false, `${version} is not allowed`);
  const manifest = JSON.parse(readFileSync("package.json", "utf8"));
  assert.equal(manifest.engines.node, ">=22.13.0", "the package's own engines are the consumers' minimum, the Astryx CLI's");
  assert.match(readFileSync("README.md", "utf8"), new RegExp(`Node \`${root.engines.node.replace(/[\^|.]/g, "\\$&")}\``), "the README names the development minimum");
});
