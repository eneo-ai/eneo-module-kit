/**
 * A release replaces the files under /assets: a tab that loaded the page before it names files the release took away.
 * The test sends the page's script request to a name no build has, so the backend answers it as it answers such a file,
 * and checks what that answer is and that the page comes back at the next visit, once the release's files are there.
 * Nothing in the page can do more: without its script it shows nothing at all.
 */
import { declare, expect, test } from "../e2e/fixtures";

const SCRIPT = /\/assets\/index-[\w-]+\.js$/;

test("a page whose script the release took away gets a 404 that no cache keeps, and the next visit starts the release that runs", async ({ page, browserName }) => {
  // The browser reports the script it could not load; Firefox also refuses the 404's JSON as a script of the wrong type.
  declare(page, [{ console: /status of 404.*\/assets\/index-[\w-]+\.js/ }]);
  if (browserName === "firefox") declare(page, [{ requestFailed: /GET .*\/assets\/index-[\w-]+\.js: NS_ERROR_CORRUPTED_CONTENT/ }]);
  // WebKit on Linux (CI) refuses it too and reports the request as cancelled; WebKit on macOS reports nothing.
  if (browserName === "webkit" && process.platform === "linux") declare(page, [{ requestFailed: /GET .*\/assets\/index-[\w-]+\.js: Load request cancelled/ }]);
  await page.route(SCRIPT, (route) => route.continue({ url: new URL("/assets/index-0ldbui1d.js", route.request().url()).href }));
  const gone = page.waitForResponse(SCRIPT);
  await page.goto("/");
  const answer = await gone;

  expect(answer.status()).toBe(404);
  expect(answer.headers()["content-type"], "not the page, which would run as the script").not.toContain("text/html");
  expect(answer.headers()["cache-control"] ?? "", "not kept as the file would be: the next visit asks again").not.toMatch(/max-age|immutable/);
  await expect(page.locator("#root")).toBeEmpty();

  await page.unroute(SCRIPT);
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Logga in med Eneo" })).toBeVisible();
});
