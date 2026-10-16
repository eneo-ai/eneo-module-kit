import assert from "node:assert/strict";
import test from "node:test";
import type { DraftStorage } from "../src/drafts.js";

/** What a reader of names needs: a list of text. */
const isNames = (value: unknown): value is string[] => Array.isArray(value) && value.every((name) => typeof name === "string");
const isRecord = (value: unknown): value is Record<string, unknown> => typeof value === "object" && value !== null && !Array.isArray(value);

/** A tab's sessionStorage. */
function tabStorage(): DraftStorage & { data: Map<string, string> } {
  const data = new Map<string, string>();
  return {
    data,
    get length() {
      return data.size;
    },
    key: (index: number) => [...data.keys()][index] ?? null,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => void data.set(key, value),
    removeItem: (key: string) => void data.delete(key),
  };
}

test("a draft comes back to the same person only, and another person signing in here clears it", async () => {
  const { createDrafts } = await import("../src/drafts.js");
  const storage = tabStorage();
  const drafts = createDrafts("min-modul", storage);
  drafts.write("user-1", "flow:flow-1", { motesnamn: "KS" });
  assert.deepEqual(drafts.read("user-1", "flow:flow-1", isRecord), { motesnamn: "KS" });
  assert.equal(drafts.read("user-2", "flow:flow-1", isRecord), null, "never another person's");

  drafts.write("user-2", "flow:flow-1", { motesnamn: "BUN" });
  drafts.keepOnly("user-2");
  assert.equal(drafts.read("user-1", "flow:flow-1", isRecord), null, "user-1's goes when user-2 signs in");
  assert.deepEqual(drafts.read("user-2", "flow:flow-1", isRecord), { motesnamn: "BUN" });

  drafts.clear("user-2", "flow:flow-1");
  assert.equal(drafts.read("user-2", "flow:flow-1", isRecord), null);
  storage.setItem("not-a-draft", "kept");
  storage.setItem("en-annan-modul:user-1:x", "kept");
  drafts.keepOnly("user-3");
  assert.equal(storage.getItem("not-a-draft"), "kept", "only this module's drafts are touched");
  assert.equal(storage.getItem("en-annan-modul:user-1:x"), "kept", "not another prefix's");
});

test("a storage the browser refuses, or a draft that does not parse, is no draft and no error", async () => {
  const { createDrafts } = await import("../src/drafts.js");
  const refusing = {
    get length(): number {
      throw new DOMException("denied", "SecurityError");
    },
    key: () => null,
    getItem: () => "{not json",
    setItem: () => {
      throw new DOMException("full", "QuotaExceededError");
    },
    removeItem: () => undefined,
  } satisfies DraftStorage;
  const drafts = createDrafts("min-modul", refusing);
  assert.equal(drafts.read("user-1", "flow:flow-1", isRecord), null);
  assert.equal(drafts.write("user-1", "flow:flow-1", { a: 1 }), false);
  drafts.keepOnly("user-1");
  drafts.clear("user-1", "flow:flow-1");
  const none = createDrafts("min-modul", null);
  assert.equal(none.read("user-1", "flow:flow-1", isRecord), null);
  assert.equal(none.write("user-1", "flow:flow-1", { a: 1 }), false, "no storage keeps nothing");
});

test("typed work the storage refused is said to be unstored until it is stored, sent or thrown away, so leaving asks first", async () => {
  const { createDrafts } = await import("../src/drafts.js");
  let refuse = true;
  const storage = tabStorage();
  const flaky = {
    ...storage,
    get length() {
      return storage.length;
    },
    setItem: (key: string, value: string) => {
      if (refuse) throw new DOMException("full", "QuotaExceededError");
      storage.setItem(key, value);
    },
  };
  const drafts = createDrafts("min-modul", flaky);
  let told = 0;
  const stop = drafts.subscribe(() => (told += 1));
  assert.equal(drafts.unstored(), false);
  assert.equal(drafts.write("user-1", "flow:flow-1", { motesnamn: "KS" }), false);
  assert.equal(drafts.unstored(), true, "the page asks before leaving");
  assert.equal(drafts.write("user-1", "review:run-1", { text: "x" }), false);
  refuse = false;
  assert.equal(drafts.write("user-1", "flow:flow-1", { motesnamn: "KS" }), true);
  assert.equal(drafts.unstored(), true, "the review edit is still unstored");
  drafts.clear("user-1", "review:run-1"); // saved, or thrown away
  assert.equal(drafts.unstored(), false);
  assert.equal(told, 2, "told when it starts and when it ends");

  refuse = true;
  drafts.write("user-1", "flow:flow-1", { motesnamn: "BUN" });
  assert.equal(drafts.unstored(), true);
  drafts.forget();
  assert.equal(drafts.unstored(), false, "the page that held it is gone, and what it could not keep with it");
  assert.equal(told, 4);
  stop();
});

test("a draft is read only in the shape its reader needs: any other is dropped from the storage and counts as no draft", async () => {
  const { createDrafts } = await import("../src/drafts.js");
  const storage = tabStorage();
  const drafts = createDrafts("min-modul", storage);
  const key = "min-modul:user-1:names:run-1";
  const stored = (raw: string) => {
    storage.setItem(key, raw);
    return drafts.read("user-1", "names:run-1", isNames);
  };
  for (const [what, raw] of [
    ["an object where a list is read", "{}"],
    ["null", "null"],
    ["a list of the wrong things", '[1, {"label": 5}]'],
    ["a number", "3"],
    ["text that is not JSON", "{ not json"],
  ]) {
    assert.equal(stored(raw), null, `${what} is no draft`);
    assert.equal(storage.getItem(key), null, `${what} is removed, not left to fail again`);
  }
  assert.deepEqual(stored('["Anna", "Erik"]'), ["Anna", "Erik"], "a draft of the right shape comes back");
  assert.notEqual(storage.getItem(key), null, "and stays");
});

test("without a storage of its own a module's drafts are this tab's: sessionStorage", async () => {
  const { installDom } = await import("./test-dom.js");
  const dom = installDom();
  const { createDrafts } = await import("../src/drafts.js");
  const drafts = createDrafts("min-modul");
  drafts.write("user-1", "anteckning", "Hej");
  assert.equal(dom.window.sessionStorage.getItem("min-modul:user-1:anteckning"), '"Hej"');
  assert.equal(dom.window.localStorage.getItem("min-modul:user-1:anteckning"), null, "nothing outlives the tab");
});
