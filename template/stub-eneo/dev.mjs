// The module against the stub Eneo in one command, the same on macOS, Linux and Windows. From the module's folder:
//
//   node stub-eneo/dev.mjs                              the stub on 8411 and the module on 3001, until Ctrl+C
//   node stub-eneo/dev.mjs --check                      starts both, signs in as a browser would, says what it got, stops
//   node stub-eneo/dev.mjs --port 3002 --stub-port 8412 other ports, when those are taken
//
// Development only, with the stub's values of .env.example; it does not read .env. It needs the built UI (web/dist) and
// the module's virtual environment (.venv, or the interpreter PYTHON names) with eneo-module-bff installed.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { connect } from "node:net";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const { values } = parseArgs({ options: { check: { type: "boolean" }, port: { type: "string", default: "3001" }, "stub-port": { type: "string", default: "8411" } } });
const [appPort, stubPort] = [values.port, values["stub-port"]];
const python = process.env.PYTHON || join(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
const module = `http://localhost:${appPort}`;
const stub = `http://localhost:${stubPort}`;

function fail(message) {
  console.error(`\ndev: ${message}`);
  process.exit(1);
}

if (!/^\d+$/.test(appPort) || !/^\d+$/.test(stubPort)) fail("--port and --stub-port take a port number.");
if (!existsSync(python)) fail(`No Python at ${python}. Make the module's virtual environment first: see README.md ("Run it").`);
if (!existsSync(join(root, "web", "dist", "index.html"))) fail("The UI is not built. In web/: npm ci && npm run build");

// Something already listening would answer the checks below in this module's place.
for (const port of [appPort, stubPort]) {
  const taken = await new Promise((done) => {
    const socket = connect(Number(port), "127.0.0.1");
    socket.once("connect", () => done(true) || socket.destroy());
    socket.once("error", () => done(false));
  });
  if (taken) fail(`Port ${port} is taken. Stop what listens there, or choose others: --port 3002 --stub-port 8412`);
}

const children = [
  spawn(python, [join(root, "stub-eneo", "server.py"), stubPort], { stdio: "inherit" }),
  spawn(python, ["-c", `from eneo_module_bff import serve; serve('main:build_app', factory=True, host='127.0.0.1', port=${appPort})`], {
    cwd: join(root, "backend"),
    stdio: "inherit",
    env: {
      ...process.env,
      ENEO_BACKEND_URL: `http://127.0.0.1:${stubPort}`,
      ENEO_PUBLIC_URL: stub,
      MODULE_PUBLIC_URL: module,
      MODULE_KEY: "eneo-module",
      ENEO_API_KEY: "stub-service-key",
      SESSION_SECRET: "change-me-to-at-least-32-random-characters",
      COOKIE_SECURE: "false",
    },
  }),
];

let stopping = false;
// Both stop before the last word is said, so that it is the last line.
async function stop(code, lastWord) {
  if (stopping) return;
  stopping = true;
  for (const child of children) child.kill();
  await Promise.all(children.map((child) => child.exitCode !== null || child.signalCode !== null || new Promise((done) => child.once("exit", done))));
  if (lastWord) console.log(lastWord);
  process.exit(code);
}
for (const child of children) {
  child.on("exit", () => {
    if (!stopping) {
      console.error("\ndev: the stub or the module stopped: see above.");
      stop(1);
    }
  });
}
process.on("SIGINT", () => stop(0));
process.on("SIGTERM", () => stop(0));

async function healthy(url) {
  for (let attempt = 0; attempt < 100; attempt++) {
    try {
      if ((await fetch(`${url}/health`)).ok) return;
    } catch {
      // not listening yet
    }
    await new Promise((done) => setTimeout(done, 200));
  }
  throw new Error(`${url}/health did not answer within 20 s`);
}

// The login as a browser does it: the module sends it to Eneo, Eneo sends it back with a ticket, the callback sets the
// session cookie. Then the template's own route, which needs that session.
async function signIn() {
  const cookies = new Map();
  const get = async (url) => {
    const cookie = [...cookies].map(([name, value]) => `${name}=${value}`).join("; ");
    const response = await fetch(url, { redirect: "manual", headers: url.startsWith(module) && cookie ? { cookie } : {} });
    for (const line of response.headers.getSetCookie()) {
      const [pair] = line.split(";");
      cookies.set(pair.slice(0, pair.indexOf("=")), pair.slice(pair.indexOf("=") + 1));
    }
    return response;
  };
  const toEneo = (await get(`${module}/api/auth/login?next=/flows`)).headers.get("location");
  if (!toEneo?.startsWith(stub)) throw new Error(`/api/auth/login did not redirect to the stub: ${toEneo}`);
  const callback = (await get(toEneo)).headers.get("location");
  if (!callback?.startsWith(`${module}/api/auth/callback`)) throw new Error(`the stub did not send the browser back to the module's callback: ${callback}`);
  const landed = (await get(callback)).headers.get("location");
  if (landed !== "/flows") throw new Error(`the callback did not finish the login: it redirected to ${landed}`);
  const example = await get(`${module}/api/example`);
  const body = await example.text();
  if (example.status !== 200) throw new Error(`/api/example answered ${example.status} ${body}`);
  const page = await get(`${module}/flows`);
  if (page.status !== 200 || !(page.headers.get("content-type") || "").includes("text/html")) throw new Error(`/flows did not answer the built page: ${page.status}`);
  return body;
}

try {
  await Promise.all([healthy(stub), healthy(module)]);
  if (values.check) {
    const answer = await signIn();
    await stop(0, `\nOK: signed in through the stub Eneo, the page is served, and /api/example answered ${answer}`);
  }
  console.log(`\nThe module runs on ${module} against the stub Eneo on ${stub}.`);
  console.log("Open it and sign in: the stub signs everyone in as Erik Lund. Ctrl+C stops both.");
} catch (error) {
  console.error(`\ndev: ${error.message}`);
  await stop(1);
}
