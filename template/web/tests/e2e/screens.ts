/**
 * How to reach every state of the module for the accessibility gate: each is a name and the steps a person takes to
 * get there, against the stub Eneo. A new page of the module adds its states here.
 */
import { expect, type Page } from "@playwright/test";
import { signIn, stubControl, stubDefaults, stubFlows } from "./fixtures";

export interface State {
  name: string;
  go: (page: Page) => Promise<void>;
  /** Console messages the state provokes on purpose (a failure the test caused); anything else on the console fails the gate. */
  allowConsole?: RegExp[];
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
    name: "flows-empty",
    go: async (page) => {
      await stubFlows(page, "empty");
      await signIn(page);
      await expect(page.getByRole("heading", { level: 2, name: /Det finns inga publicerade flöden/ })).toBeVisible();
    },
  },
  {
    name: "flows-error",
    // The browser reports the 500 the stub was told to answer.
    allowConsole: [/status of 500/],
    go: async (page) => {
      await stubFlows(page, "error");
      await signIn(page);
      await expect(page.getByText("Flödena kunde inte visas.")).toBeVisible();
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
