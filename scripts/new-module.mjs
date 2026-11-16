// A module from template/, with the packages of this checkout, ready to start. The same on macOS, Linux and Windows:
//
//   node scripts/new-module.mjs ../eneo-mod-<name>
//
// A folder that does not exist yet becomes a new module. A folder that already holds one (a module made before, a fresh
// clone of a module's repository) is installed in place.
//
// It runs the steps of docs/guides/new-module.md ("By hand"): builds and packs the UI package, copies the template, installs
// and builds its web app, and makes its virtual environment with the locked packages and this checkout's BFF.
// CI runs it on Linux, Windows and macOS (the quick-path job).
import { spawnSync } from "node:child_process";
import { copyFileSync, cpSync, existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import { basename, dirname, isAbsolute, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const kit = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const windows = process.platform === "win32";

function fail(message) {
  console.error(`\nnew-module: ${message}`);
  process.exit(1);
}

function run(command, args, cwd) {
  console.log(`\n> ${command} ${args.join(" ")}   (in ${cwd})`);
  // npm is a .cmd file on Windows, which only a shell starts. A shell does not quote arguments, so npm is only ever
  // given arguments without spaces: a path reaches it as cwd.
  const done = spawnSync(command, args, { cwd, stdio: "inherit", shell: windows && command === "npm" });
  if (done.status !== 0) fail(`"${command} ${args.join(" ")}" failed: see above. Fix it and run the same command again.`);
}

// Python 3.12 when it is there, else a newer one. PYTHON names another.
function findPython() {
  const candidates = [["py", "-3.12"], ["python3.12"], ["python3"], ["python"], ["py"]];
  if (process.env.PYTHON) candidates.unshift([process.env.PYTHON]);
  for (const [command, ...args] of candidates) {
    const seen = spawnSync(command, [...args, "-c", "import sys; print(sys.version_info >= (3, 12))"], { encoding: "utf8" });
    if (seen.status === 0 && seen.stdout.trim() === "True") return [command, ...args];
  }
  fail("Python 3.12 or newer was not found. Install it, or set the environment variable PYTHON to its path.");
}

const [major, minor] = process.versions.node.split(".").map(Number);
if (major < 22 || (major === 22 && minor < 22)) fail(`Node 22.22.2 or newer is needed; this is ${process.versions.node}.`);

if (!process.argv[2]) fail("Name the new module's folder: node scripts/new-module.mjs ../eneo-mod-<name>");
const target = resolve(process.argv[2]);
const fromKit = relative(kit, target);
if (!fromKit.startsWith("..") && !isAbsolute(fromKit)) fail("The new module's folder must be outside this repository, for example ../eneo-mod-<name>.");
// A folder that already holds a module (a copy of the template, a clone of a module's repository) is installed in place.
const inPlace = existsSync(join(target, "web", "package.json")) && existsSync(join(target, "backend", "requirements.lock"));
if (!inPlace && existsSync(target) && readdirSync(target).length > 0) fail(`${target} exists and is not a module made from the template.`);

const python = findPython();

// The UI package of this checkout, packed where the template's lock looks for it (web/vendor/, not committed).
run("npm", ["ci"], kit);
run("npm", ["run", "-w", "packages/ui", "build"], kit);
run("npm", ["pack", "-w", "packages/ui", "--pack-destination", "template/web/vendor"], kit);

if (inPlace) {
  console.log(`\n${target} holds a module: installing it in place`);
} else {
  // The template, dotfiles included, without what an earlier build or test run left in it.
  const LEFTOVERS = new Set(["node_modules", "dist", "test-results", ".test-build", ".venv", ".env", "__pycache__"]);
  cpSync(join(kit, "template"), target, { recursive: true, filter: (source) => !LEFTOVERS.has(basename(source)) });
  console.log(`\nCopied the template to ${target}`);
}
const pack = `eneo-ai-module-kit-${JSON.parse(readFileSync(join(kit, "packages", "ui", "package.json"), "utf8")).version}.tgz`;
mkdirSync(join(target, "web", "vendor"), { recursive: true });
copyFileSync(join(kit, "template", "web", "vendor", pack), join(target, "web", "vendor", pack));

run("npm", ["ci"], join(target, "web"));
run("npm", ["run", "build"], join(target, "web"));

// The backend: the locked third-party packages with their hashes, then the BFF of this checkout.
run(python[0], [...python.slice(1), "-m", "venv", ".venv"], target);
const venvPython = join(target, ".venv", windows ? "Scripts/python.exe" : "bin/python");
run(venvPython, ["-m", "pip", "install", "--quiet", "--require-hashes", "--no-deps", "-r", "backend/requirements.lock"], target);
run(venvPython, ["-m", "pip", "install", "--quiet", "--no-deps", join(kit, "packages", "bff")], target);

console.log(`
The module is in ${target}. Check it, then start it against the stub Eneo:

  cd "${target}"
  node stub-eneo/dev.mjs --check     signs in through the stub and stops: it should end with "OK"
  node stub-eneo/dev.mjs             then open http://localhost:3001 and sign in (the stub signs everyone in as Erik Lund)
`);
