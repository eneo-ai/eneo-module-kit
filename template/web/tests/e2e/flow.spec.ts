import { expect, signIn, stubFlows, test } from "./fixtures";

test.beforeEach(async ({ page }) => {
  await stubFlows(page, "normal");
});

test("sign in through the stub Eneo, see the shell and the flows, call the module's own route, sign out", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Eneo-modul" })).toBeVisible();
  await expect(page).toHaveTitle("Eneo-modul");
  await page.getByRole("link", { name: "Logga in med Eneo" }).click();

  // The page behind the login: the flows Eneo lists, through the backend's proxy.
  await expect(page).toHaveURL(/\/flows$/);
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeVisible();
  const flows = page.getByRole("list", { name: "Flöden" });
  await expect(flows.getByText("Nämndmöte till rapport")).toBeVisible();
  await expect(flows.getByText("Intervju till sammanfattning")).toBeVisible();
  // The module's own route, /api/example, greeted the signed-in user.
  await expect(page.getByText("Hej Erik Lund")).toBeVisible();

  // The shell: a skip link, a named navigation landmark and exactly one main region.
  await expect(page.getByRole("navigation", { name: "Eneo-modul" })).toBeVisible();
  await expect(page.locator('[role="main"], main')).toHaveCount(1);
  await expect(page.getByRole("link", { name: "Hoppa till innehåll" })).toBeAttached();

  await page.getByRole("button", { name: "Öppna konto för Erik Lund" }).click();
  await page.getByRole("menuitem", { name: "Logga ut" }).click();
  await expect(page.getByRole("link", { name: "Logga in med Eneo" })).toBeVisible();
  const status = await page.request.get("/api/auth/status");
  expect(await status.json()).toMatchObject({ authenticated: false });
  expect((await page.request.get("/api/eneo/flows/")).status(), "the session is gone").toBe(401);
});

test("a deep link without a session shows the sign-in page, and signing in lands back on the page", async ({ page }) => {
  await page.goto("/flows");
  await expect(page.getByRole("link", { name: "Logga in med Eneo" })).toBeVisible();
  await page.getByRole("link", { name: "Logga in med Eneo" }).click();
  await expect(page).toHaveURL(/\/flows$/);
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeVisible();
  // A reload of a deep link is the page again, not a 404.
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeVisible();
});

test("the backend answers what it should: no session is 401, an Eneo route not on the allowlist is 403, an unknown API path 404", async ({ page }) => {
  expect((await page.request.get("/api/example")).status()).toBe(401);
  expect((await page.request.get("/api/eneo/flows/")).status()).toBe(401);
  expect((await page.request.get("/api/nope")).status()).toBe(404);
  expect((await page.request.get("/health")).ok()).toBe(true);
  await signIn(page);
  expect((await page.request.get("/api/eneo/flows/")).status()).toBe(200);
  expect((await page.request.get("/api/eneo/users/")).status(), "denied by default").toBe(403);
});

test("the page's strict Content Security Policy is the backend's, on the page and its files", async ({ page }) => {
  const response = await page.goto("/");
  const policy = response?.headers()["content-security-policy"] ?? "";
  expect(policy).toContain("script-src 'self'");
  expect(policy).toContain("style-src 'self'");
  expect(policy).not.toContain("unsafe-inline");
  expect(response?.headers()["referrer-policy"]).toBe("no-referrer");
});

test.describe("the organisation's mark", () => {
  test("a logo for each colour mode: the light one in light, the dark one in dark, never both", async ({ page }) => {
    await page.goto("/");
    const light = page.locator('img[data-brand-logo="light"]');
    const dark = page.locator('img[data-brand-logo="dark"]');
    await expect(light).toBeVisible();
    await expect(light).toHaveAttribute("alt", "Exempelkommunen");
    await expect(light).toHaveAttribute("src", "/api/branding/logo/light");
    await expect(dark).toBeHidden();
    await page.evaluate(() => localStorage.setItem("theme", "dark"));
    await page.reload();
    await expect(dark).toBeVisible();
    await expect(light).toBeHidden();
  });
});

test("the account menu chooses the colour mode, which is stored for the next visit", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Öppna konto för Erik Lund" }).click();
  await page.getByRole("menuitemradio", { name: "Mörkt" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => localStorage.getItem("theme"))).toBe("dark");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test.describe("colour mode", () => {
  test("a stored dark is applied on the first render, whatever the system says", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("theme", "dark"));
    await page.goto("/");
    await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
    const background = await page.evaluate(() => getComputedStyle(document.querySelector("[data-astryx-theme]")!).colorScheme);
    expect(background).toBe("dark");
  });

  test("with nothing stored the system decides, here dark", async ({ page }) => {
    await page.emulateMedia({ colorScheme: "dark" });
    await page.goto("/");
    await expect(page.getByRole("heading", { level: 1, name: "Eneo-modul" })).toBeVisible();
    expect(await page.evaluate(() => matchMedia("(prefers-color-scheme: dark)").matches)).toBe(true);
    const scheme = await page.evaluate(() => getComputedStyle(document.querySelector("[data-astryx-theme]")!).colorScheme);
    expect(scheme).toContain("dark");
  });
});

test.describe("when Eneo cannot list the flows", () => {
  // The browser reports the 500 the stub was told to answer.
  test.use({ allowConsole: [/status of 500/] });

  test("the page says so and offers to try again", async ({ page }) => {
    await signIn(page);
    await stubFlows(page, "error");
    await page.reload();
    await expect(page.getByText("Flödena kunde inte visas.")).toBeVisible();
    await stubFlows(page, "normal");
    await page.getByRole("button", { name: "Försök igen" }).click();
    await expect(page.getByRole("list", { name: "Flöden" })).toBeVisible();
  });
});
