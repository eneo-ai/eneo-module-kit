/**
 * The backend's routing of the built UI (eneo_module_bff/web.py) and the app's routes (src/App.tsx), met in a browser:
 * every address of the app is the page, an address that is none of the app's is the page too, which takes it to the
 * start, and a missing file or API path is a 404 that is not the page.
 */
import { expect, test } from "../e2e/fixtures";

test("a direct visit to an address of the app is that page, in Swedish, with no redirect", async ({ page }) => {
  const visits: [string, string, string][] = [
    ["/", "Eneo-modul", "Eneo-modul"],
    // Signed out, the page behind the login shows the sign-in at its own address.
    ["/flows", "Eneo-modul", "Eneo-modul"],
    ["/inloggad?fel=utgangen", "Inloggningen har redan gått ut", "Inloggningen har redan gått ut · Eneo-modul"],
  ];
  for (const [path, heading, title] of visits) {
    const response = await page.goto(path);

    expect(response?.status(), path).toBe(200);
    await expect(page.getByRole("heading", { level: 1, name: heading }), path).toBeVisible();
    await expect(page, path).toHaveTitle(title);
    await expect(page.locator("html"), path).toHaveAttribute("lang", "sv");
    expect(new URL(page.url()).pathname + new URL(page.url()).search, "no redirect").toBe(path);
  }
});

test("an address that is none of the app's is the page, and the app takes it to the start", async ({ page }) => {
  const response = await page.goto("/finns/inte");

  expect(response?.status()).toBe(200);
  expect(response?.headers()["content-type"]).toContain("text/html");
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("link", { name: "Logga in med Eneo" })).toBeVisible();
});

test("a missing file or API path is a 404 that is not the page, and HEAD is answered like GET", async ({ request }) => {
  for (const path of ["/assets/index-0ldbui1d.js", "/assets/no-name", "/missing.png", "/openapi.json", "/api", "/api/nope"]) {
    const response = await request.get(path);

    expect(response.status(), path).toBe(404);
    expect(response.headers()["content-type"] ?? "", path).not.toContain("text/html");
  }
  const head = await request.head("/");
  expect(head.status()).toBe(200);
  expect(head.headers()["content-type"]).toContain("text/html");
});
