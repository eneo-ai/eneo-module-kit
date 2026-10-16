import assert from "node:assert/strict";
import test, { afterEach, type TestContext } from "node:test";
import { createElement } from "react";
import { button, cleanup, installDom, mount, useClipboard } from "./test-dom.js";

installDom();
afterEach(cleanup);

const REVISION = "c5d54608d5833737677157bde44b95b969e67bbb";
const SOURCE = "https://github.com/eneo-ai/eneo-mod-example";
// Built at 10:04 on the reader's own clock, whatever the time zone of the machine that runs the test.
const BUILT = new Date(2026, 9, 8, 10, 4, 12).toISOString().replace(/\.\d{3}Z$/, "Z");
const RELEASE = { ok: true, release: "v1.2.3", revision: REVISION, build_date: BUILT, source: SOURCE };
const UNKNOWN = { ok: true, release: null, revision: null, build_date: null, source: null };
const settle = () => new Promise((resolve) => setTimeout(resolve, 20));
const json = (body: object, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

/** The page's fetch, answering with what `answer` gives; what was asked of it. */
function useFetch(t: TestContext, answer: () => Promise<Response>) {
  const asked: string[] = [];
  const original = globalThis.fetch;
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    asked.push(`${init?.method ?? "GET"} ${url} ${init?.cache}`);
    return answer();
  }) as typeof fetch;
  t.after(() => {
    globalThis.fetch = original;
  });
  return asked;
}

async function versionInfo() {
  const { ModuleProviders } = await import("../src/ModuleProviders.js");
  const { VersionInfo } = await import("../src/VersionInfo.js");
  const view = await mount(createElement(ModuleProviders, { children: createElement(VersionInfo, { productName: "Exempelmodulen" }) }));
  await view.act(settle);
  /** Each term of the list and what it says. */
  const rows = () => [...view.container.querySelectorAll("dt")].map((term) => [term.textContent, term.nextElementSibling?.textContent]);
  const link = (words: string) => [...view.container.querySelectorAll<HTMLAnchorElement>("a[href]")].find((a) => a.textContent?.trim() === words);
  const press = (element: HTMLElement) =>
    view.act(async () => {
      element.click();
      await settle();
    });
  const announced = () => document.querySelector('[data-astryx-live-region="polite"]')?.textContent ?? "";
  return { ...view, rows, link, press, announced };
}

test("it reads the build when it is shown, and says the release, the commit's first seven characters and when it was built", async (t) => {
  let answer!: (response: Response) => void;
  const asked = useFetch(t, () => new Promise((resolve) => (answer = resolve)));
  const { rows, container, act } = await versionInfo();
  assert.deepEqual(asked, ["GET /api/healthz no-store"]);
  assert.match(container.textContent ?? "", /Hämtar versionen…/, "it says that it is on its way");

  await act(async () => {
    answer(json(RELEASE));
    await settle();
  });
  // When it was built, on the reader's clock and in Swedish; the machine-readable time beside it.
  assert.deepEqual(rows(), [["Utgåva", "v1.2.3"], ["Commit", "c5d5460"], ["Byggd", "8 okt. 2026 10:04"]]);
  assert.equal(container.querySelector("time")?.getAttribute("datetime"), new Date(BUILT).toISOString());
});

test("the release and the commit open their pages in a new tab, and Kopiera supportinformation copies the build as plain lines", async (t) => {
  useFetch(t, async () => json(RELEASE));
  const written: string[] = [];
  useClipboard(t, { writeText: async (text) => void written.push(text) });
  const { link, press, announced, container } = await versionInfo();

  const release = link("Visa utgåvan på GitHub");
  const commit = link("Visa commiten på GitHub");
  assert.equal(release?.getAttribute("href"), `${SOURCE}/releases/tag/v1.2.3`);
  assert.equal(commit?.getAttribute("href"), `${SOURCE}/commit/${REVISION}`);
  for (const page of [release!, commit!]) {
    assert.equal(page.getAttribute("target"), "_blank");
    assert.match(page.getAttribute("rel") ?? "", /noopener/);
    assert.equal(page.getAttribute("aria-label"), `${page.textContent?.trim()} i en ny flik`, "its name starts with the words it shows");
  }

  await press(button(container, "Kopiera supportinformation")!);
  await new Promise(requestAnimationFrame);
  assert.deepEqual(written, [
    ["Exempelmodulen", "Utgåva: v1.2.3", `Commit: ${REVISION}`, `Byggd: ${BUILT}`, `Källkod: ${SOURCE}`, "Adress: http://localhost"].join("\n"),
  ]);
  assert.equal(announced(), "Kopierat");
});

test("a build that knows nothing of itself says Okänd, links nowhere, and still copies what support needs", async (t) => {
  useFetch(t, async () => json(UNKNOWN));
  const written: string[] = [];
  useClipboard(t, { writeText: async (text) => void written.push(text) });
  const { rows, container, press } = await versionInfo();

  assert.deepEqual(rows(), [["Utgåva", "Okänd"], ["Commit", "Okänd"], ["Byggd", "Okänd"]]);
  assert.equal(container.querySelector("a[href]"), null);
  await press(button(container, "Kopiera supportinformation")!);
  assert.deepEqual(written, [["Exempelmodulen", "Utgåva: okänd", "Commit: okänd", "Byggd: okänd", "Källkod: okänd", "Adress: http://localhost"].join("\n")]);
});

test("without its repository a build is still known by its release and commit, and links nowhere", async (t) => {
  useFetch(t, async () => json({ ...RELEASE, source: null }));
  const { rows, container } = await versionInfo();

  assert.deepEqual(rows().slice(0, 2), [["Utgåva", "v1.2.3"], ["Commit", "c5d5460"]]);
  assert.equal(container.querySelector("a[href]"), null);
});

test("a read that fails says so, and Försök igen reads again", async (t) => {
  let answer = async () => json({ detail: "unavailable" }, 503);
  const asked = useFetch(t, () => answer());
  const { rows, container, press } = await versionInfo();
  assert.match(container.textContent ?? "", /Versionen kunde inte visas\./);
  assert.deepEqual(rows(), []);

  answer = async () => json(RELEASE);
  await press(button(container, "Försök igen")!);
  assert.equal(asked.length, 2);
  assert.deepEqual(rows()[0], ["Utgåva", "v1.2.3"]);
});
