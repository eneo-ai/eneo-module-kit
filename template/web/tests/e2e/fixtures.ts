import { expect, test as base, type Page } from "@playwright/test";

/**
 * `test` with the two things every page of the module must stay clean of: a console error, and a Content Security
 * Policy violation (the backend's policy has no 'unsafe-inline': a style attribute or an inline script in the markup
 * would show here). Both are checked after every test.
 */
export const test = base.extend<{ clean: void; allowConsole: RegExp[] }>({
  // Messages a test expects (a browser reports a failed request, a 500 the test provoked): `test.use({ allowConsole: [/500/] })`.
  allowConsole: [[], { option: true }],
  clean: [
    async ({ page, allowConsole }, use) => {
      const problems: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") problems.push(`console error: ${message.text()}`);
      });
      page.on("pageerror", (error) => problems.push(`page error: ${error.message}`));
      await page.addInitScript(() => {
        document.addEventListener("securitypolicyviolation", (event) => {
          console.error(`CSP violation: ${event.violatedDirective} ${event.blockedURI}`);
        });
      });
      await use();
      expect(
        problems.filter((problem) => !allowConsole.some((allowed) => allowed.test(problem))),
        "nothing in the console that is an error or a CSP violation",
      ).toEqual([]);
    },
    { auto: true },
  ],
});

export { expect };

const STUB = Number(process.env.E2E_STUB_PORT ?? 8011);

/** What the stub Eneo answers for the flow list: two flows, none, or a failure. */
export async function stubFlows(page: Page, mode: "normal" | "empty" | "error") {
  const response = await page.request.post(`http://127.0.0.1:${STUB}/__stub/flows?mode=${mode}`);
  expect(response.ok()).toBe(true);
}

/** Signs in through the stub Eneo: the module's login, Eneo's, the callback, and back to the flows. */
export async function signIn(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Logga in med Eneo" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeVisible();
}

/** A control route of the stub Eneo (template/stub-eneo/server.py). */
export async function stubControl(page: Page, route: string) {
  const response = await page.request.post(`http://127.0.0.1:${STUB}/__stub/${route}`);
  expect(response.ok(), `stub ${route}`).toBe(true);
}

/** The logins made from now on are the stub's defaults again: a long session, Erik Lund. */
export async function stubDefaults(page: Page) {
  await stubControl(page, "session?ends_in=reset&token_seconds=reset");
  await stubControl(page, "login-as?user=erik");
}
