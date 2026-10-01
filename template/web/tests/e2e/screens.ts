/**
 * How to reach every state of the module for the accessibility gate: each is a name and the steps a person takes to
 * get there, against the stub Eneo. A new page of the module adds its states here.
 */
import { expect, type Page } from "@playwright/test";
import { signIn, stubFlows } from "./fixtures";

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
      await stubFlows(page, "error");
      await signIn(page);
      await expect(page.getByText("Flödena kunde inte visas.")).toBeVisible();
    },
  },
];
