// Before the kit's first release: regenerates package-lock.json against the packed UI package, so `npm ci` has a lock to
// install from (see vendor/README.md). After the release the package is in the registry, and `npm install` does this.
//
//   node scripts/relock.mjs /path/to/eneo-ai-module-kit-0.1.0.tgz
import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename } from "node:path";
import { spawnSync } from "node:child_process";

const NAME = "@eneo-ai/module-kit";
const pack = process.argv[2];
if (!pack) {
  console.error("usage: node scripts/relock.mjs <the packed @eneo-ai/module-kit tarball>");
  process.exit(2);
}
const file = `vendor/${basename(pack)}`;
mkdirSync("vendor", { recursive: true });
copyFileSync(pack, file);

const read = (path) => JSON.parse(readFileSync(path, "utf8"));
const write = (path, value) => writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);

// Resolve with the dependency as the tarball, then put package.json back: it keeps the version the module will have.
const manifest = read("package.json");
const version = manifest.dependencies[NAME];
write("package.json", { ...manifest, dependencies: { ...manifest.dependencies, [NAME]: `file:${file}` } });
const resolved = spawnSync("npm", ["install", "--package-lock-only", "--ignore-scripts", "--no-audit", "--no-fund"], { stdio: "inherit" });
write("package.json", manifest);
if (resolved.status !== 0) process.exit(resolved.status ?? 1);

// The lock then says the package is `version`, found in vendor/. No integrity: it is the kit's own build, which changes
// with every commit of the UI package; every other package keeps its hash.
const lock = read("package-lock.json");
lock.packages[""].dependencies[NAME] = version;
delete lock.packages[`node_modules/${NAME}`].integrity;
write("package-lock.json", lock);
