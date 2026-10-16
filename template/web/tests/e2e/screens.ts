/**
 * How to reach every state of the module for the accessibility gate: each is a name and the steps a person takes to
 * get there, against the stub Eneo. A new page of the module adds its states here. A state that causes a failure on
 * purpose (an error answer, an aborted request) declares it in its `go` with `declare`: the sentinel of fixtures.ts
 * fails every other one, and a declared one that does not happen.
 */
import { expect, type Page } from "@playwright/test";
import { declare, signIn, stubControl, stubDefaults, stubFlows } from "./fixtures";

export interface State {
  name: string;
  go: (page: Page) => Promise<void>;
}

export const STATES: State[] = [
  {
    name: "signin",
    go: async (page) => {
      await stubFlows(page, "normal");
      await page.goto("/");
      await expect(page.getByRole("link", { name: "Logga in med Eneo" })).toBeVisible();
    },
  },
  {
    name: "flows",
    go: async (page) => {
      await stubFlows(page, "normal");
      await signIn(page);
      await expect(page.getByRole("list", { name: "Flöden" })).toBeVisible();
    },
  },
  {
    name: "account-menu",
    go: async (page) => {
      await stubFlows(page, "normal");
      await signIn(page);
      await page.getByRole("button", { name: "Öppna konto för Erik Lund" }).click();
      await expect(page.getByRole("menuitem", { name: "Logga ut" })).toBeVisible();
    },
  },
  {
    // Which version runs: the dialog the account menu opens, with what the backend says of its build.
    name: "version",
    go: async (page) => {
      await stubFlows(page, "normal");
      await signIn(page);
      await page.getByRole("button", { name: "Öppna konto för Erik Lund" }).click();
      await page.getByRole("menuitem", { name: "Version" }).click();
      await expect(page.getByRole("dialog", { name: "Version" }).getByRole("button", { name: "Kopiera supportinformation" })).toBeVisible();
    },
  },
  {
    name: "flows-empty",
    go: async (page) => {
      await stubFlows(page, "empty");
      await signIn(page);
      await expect(page.getByRole("heading", { level: 2, name: /Det finns inga publicerade flöden/ })).toBeVisible();
    },
  },
  {
    name: "flows-error",
    go: async (page) => {
      // The browser reports the 500 the stub was told to answer.
      declare(page, [{ console: /status of 500.*\/api\/eneo\/flows\// }]);
      await stubFlows(page, "error");
      await signIn(page);
      await expect(page.getByText("Flödena kunde inte visas.")).toBeVisible();
    },
  },
  {
    // The device has lost its network while the page was open: the notice above the bar, and the page as it was.
    name: "offline",
    go: async (page) => {
      await stubFlows(page, "normal");
      await signIn(page);
      await page.context().setOffline(true);
      await expect(page.getByRole("alert").filter({ hasText: "Ingen anslutning." })).toBeVisible();
    },
  },
  {
    // Five minutes before the login ends: the warning is open over the page.
    name: "session-warning",
    go: async (page) => {
      await stubFlows(page, "normal");
      await stubControl(page, "session?ends_in=200");
      await signIn(page);
      await stubDefaults(page);
      await expect(page.getByRole("alertdialog", { name: "Du loggas snart ut" })).toBeVisible();
    },
  },
  {
    // The login has ended while the page was open: the page is covered by the sign-in dialog.
    name: "signed-out",
    go: async (page) => {
      await stubFlows(page, "normal");
      await stubControl(page, "session?token_seconds=4");
      await signIn(page);
      await stubDefaults(page);
      await stubControl(page, "end-session");
      const dialog = page.getByRole("alertdialog", { name: "Du behöver logga in igen" });
      await expect
        .poll(
          async () => {
            await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
            return dialog.isVisible();
          },
          { timeout: 20_000, intervals: [500] },
        )
        .toBe(true);
    },
  },
];
