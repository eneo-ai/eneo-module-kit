// Loaded before every unit test file (scripts/test.mjs).
import { register } from "node:module";

// The sources import each other as the bundler resolves them, without an extension: ./hooks.mjs finds the compiled file.
register("./hooks.mjs", import.meta.url);

// A unit test reaches no network. One that would is given a fake by the test, `t.mock.method(globalThis, "fetch", …)`,
// which node:test takes away again when the test ends.
globalThis.fetch = async (input) => {
  throw new Error(`A unit test called fetch(${String(input)}): give the test a fake of its own.`);
};
globalThis.WebSocket = class {
  constructor(url) {
    throw new Error(`A unit test opened a WebSocket to ${url}: give the test a fake of its own.`);
  }
};
