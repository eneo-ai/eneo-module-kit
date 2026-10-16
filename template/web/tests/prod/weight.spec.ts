/**
 * What a page costs to load: the JS and CSS it transfers (compressed bodies and headers), against its budget below.
 * Chromium alone (`@chromium`): it is the engine that reports each request's transfer size. Each budget is the measured
 * value rounded up to the next 5 KB; a change that raises one says why. A new page of the module adds its own.
 */
import type { Page } from "@playwright/test";
import { expect, test } from "../e2e/fixtures";

/** Each page: what it shows when it is whole (a page that failed is never measured), whether it needs a session, its budget. */
const PAGES = {
  "/": { heading: "Eneo-modul", signedIn: false, jsKB: 175, cssKB: 30 },
  "/flows": { heading: "Välj ett flöde", signedIn: true, jsKB: 175, cssKB: 30 },
};
type Address = keyof typeof PAGES;

/** The JS and CSS a load of `address` transfers, in KB, with nothing in the cache. */
async function transferredKB(page: Page, address: Address) {
  const kb = { script: 0, stylesheet: 0 };
  const measured: Promise<void>[] = [];
  page.on("response", (response) => {
    const request = response.request();
    const type = request.resourceType();
    if (type !== "script" && type !== "stylesheet") return;
    measured.push(request.sizes().then((sizes) => void (kb[type] += (sizes.responseBodySize + sizes.responseHeadersSize) / 1024)));
  });
  await page.goto(address, { waitUntil: "networkidle" });
  await expect(page.getByRole("heading", { level: 1, name: PAGES[address].heading })).toBeVisible();
  await Promise.all(measured);
  return { jsKB: kb.script, cssKB: kb.stylesheet };
}

for (const address of Object.keys(PAGES) as Address[]) {
  test(`${address} stays within its page-weight budget @chromium`, async ({ page }) => {
    // A session as a person gets one, the handshake through the stub Eneo, without the browser loading a page first.
    if (PAGES[address].signedIn) expect((await page.request.get(`/api/auth/login?next=${encodeURIComponent(address)}`)).ok()).toBe(true);
    const { jsKB, cssKB } = await transferredKB(page, address);
    console.log(`${address}: ${jsKB.toFixed(1)} KB of JS, ${cssKB.toFixed(1)} KB of CSS`);
    const rule = "Raise a budget only with the reason in the pull request.";
    expect.soft(jsKB, `${address} loads ${jsKB.toFixed(1)} KB of JS; the budget is ${PAGES[address].jsKB} KB. ${rule}`).toBeLessThanOrEqual(PAGES[address].jsKB);
    expect.soft(cssKB, `${address} loads ${cssKB.toFixed(1)} KB of CSS; the budget is ${PAGES[address].cssKB} KB. ${rule}`).toBeLessThanOrEqual(PAGES[address].cssKB);
  });
}
