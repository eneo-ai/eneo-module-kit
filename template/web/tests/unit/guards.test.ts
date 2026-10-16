/**
 * Rules the module's code keeps, checked on every `npm test`. A new rule of the module's own goes here too.
 */
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { PRODUCT_NAME } from "../../src/config";

// The web folder: this file runs compiled, from .test-build/tests/unit/.
const WEB = fileURLToPath(new URL("../../../", import.meta.url));

/** Every source file of the page under `dir`, as a path from the web folder. */
function sources(dir = "src"): string[] {
  return readdirSync(join(WEB, dir), { withFileTypes: true }).flatMap((entry) => {
    const path = `${dir}/${entry.name}`;
    if (entry.isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry.name) && !entry.name.endsWith(".d.ts") ? [path] : [];
  });
}

/** A file's code without its comments, which may name what the code must not do. */
const code = (file: string) =>
  readFileSync(join(WEB, file), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:"'`])\/\/.*$/gm, "$1");

// Every call to the backend goes through src/session.ts: getJson over fetchWithSession, which waits out an ended login
// and names the page's user on a write (the backend refuses a write that does not), and the sign-out. A network call
// anywhere else goes out without that: send it through session.ts, or review it and list its file here with the reason.
const ALLOWED: Record<string, string> = {
  "src/session.ts": "the page's one way to the backend",
};
const NETWORK_CALL = /\bfetch\(|\bXMLHttpRequest\b|\bsendBeacon\b|\bWebSocket\b|\bEventSource\b/;

test("no network call goes out of the page except through src/session.ts", () => {
  const found = sources().filter((file) => NETWORK_CALL.test(code(file)));

  assert.deepEqual(found.filter((file) => !(file in ALLOWED)), [], "a network call outside src/session.ts: send it through session.ts, or list the file with its reason");
  assert.deepEqual(Object.keys(ALLOWED).filter((file) => !found.includes(file)), [], "a listed file makes no network call any more: take it off the list");
});

test("a unit test reaches no network: fetch and WebSocket fail unless the test gives its own fake", async (t) => {
  await assert.rejects(fetch("http://127.0.0.1:9/"), /A unit test called fetch/);
  assert.throws(() => new WebSocket("ws://127.0.0.1:9/"), /A unit test opened a WebSocket/);

  t.mock.method(globalThis, "fetch", async () => Response.json({ ok: true }));
  assert.deepEqual(await (await fetch("/api/example")).json(), { ok: true });
});

test("the module's name is src/config.ts's, and the page's title before the app runs says it too", () => {
  const title = /<title>([^<]*)<\/title>/.exec(readFileSync(join(WEB, "index.html"), "utf8"))?.[1];

  assert.equal(title, PRODUCT_NAME, "rename the module in src/config.ts and in index.html's <title> together");
});
