/**
 * Keyboard only, on the module's real screens (harness.spec.ts only proves that the checks can fail): Tab through each
 * screen from the top. Every stop shows focus (WCAG 2.4.7) and is not hidden under anything (2.4.11); focus leaves the
 * page at the end (no trap, 2.1.2); on a phone the order reads top to bottom (2.4.3). The account menu, the page's
 * dialog, the warning and the sign-in dialog keep focus inside and give it back. Adapted from speech-to-text's gate:
 * known debt, to become a package export when a second module needs it.
 */
import { writeFileSync } from "node:fs";
import type { Locator, Page } from "@playwright/test";
import { clippedFocus, focusStop, orderProblems, settle, stopProblems, tabWalk } from "./checks";
import { expect, signIn, stubControl, stubDefaults, stubFlows, test } from "./fixtures";
import { STATES } from "./screens";

test.afterEach(async ({ page }) => {
  // The next test finds the list as it should be.
  await stubFlows(page, "normal");
});

const state = (name: string) => STATES.find((s) => s.name === name)!;

for (const name of ["signin", "flows", "flows-empty", "flows-error"]) {
  const screen = state(name);
  // The state may provoke console messages on purpose (the failed list); anything else still fails the test.
  const walk = test.extend({ allowConsole: screen.allowConsole ?? [] });
  walk(`tab through ${name}`, async ({ page }, info) => {
    await screen.go(page);
    const { stops, left } = await tabWalk(page);
    writeFileSync(info.outputPath("stops.json"), JSON.stringify(stops, null, 2));
    expect(stops.length, "something to focus").toBeGreaterThan(0);
    expect.soft(left, `focus never leaves the page after ${stops.length} stops (WCAG 2.1.2)`).toBe(true);
    expect.soft(stopProblems(stops), "focus visible and unobscured").toEqual([]);
    if (!info.project.name.startsWith("laptop")) {
      expect.soft(orderProblems(stops), "focus order follows the reading order (WCAG 2.4.3)").toEqual([]);
    }
  });
}

/**
 * Tab has left the page for the browser's own controls (the document has no focus). A native modal dialog lets Tab
 * do that, as a trap would break WCAG 2.1.2; it never lets Tab reach the page behind it.
 */
const inBrowser = (page: Page) => page.evaluate(() => !document.hasFocus());

/** What is wrong with the focus now: it is not inside `popup`, it cannot be seen, it is covered or its ring is cut. */
async function focusProblems(page: Page, popup: Locator): Promise<string[]> {
  // At rest: the tooltip of the control that has the focus enters over a few frames, and in them overlaps it.
  await settle(page);
  const stop = await focusStop(page);
  const inside = await popup.evaluate((element) => element.contains(document.activeElement));
  if (!stop || !inside) return [`${stop?.label ?? "the page"} is outside the ${await popup.getAttribute("role")}`];
  const clipped = await clippedFocus(page);
  return [...stopProblems([stop]), ...(clipped ? [`${stop.label}: its focus ring is cut by ${clipped}`] : [])];
}

/** Focus moves into `popup` after it opens (WCAG 2.4.3): it may take a frame after the popup shows, so wait for it, and fail if it never comes. */
const focusMovesInto = (popup: Locator) =>
  expect.poll(() => popup.evaluate((element) => element.contains(document.activeElement)), { message: "focus moves into the popup" }).toBe(true);

/** Opens `popup` from its trigger with Enter, moves with `keys`, checks focus after each, and closes it with Escape. */
async function holdsFocus(page: Page, trigger: Locator, popup: Locator, keys: string[], initialHeading?: Locator) {
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(popup).toBeVisible();
  await focusMovesInto(popup);
  const problems: string[] = [];
  for (const key of [undefined, ...keys]) {
    if (key) await page.keyboard.press(key);
    if (!key && initialHeading) {
      // The announced title is a static initial focus target; keyboard controls still need a visible indicator.
      await expect(initialHeading).toBeFocused();
      await expect(initialHeading).toHaveAttribute("tabindex", "-1");
    } else if (!(await inBrowser(page))) problems.push(...(await focusProblems(page, popup)));
  }
  expect.soft(problems, "focus stays inside and is visible (WCAG 2.1.2, 2.4.7)").toEqual([]);
  // A tooltip leaves a moment after focus does, and takes the first Escape if it is still there.
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(popup).toBeHidden();
  await expect(trigger, "Escape gives focus back to what opened it").toBeFocused();
}

test("the account menu holds focus through its items and gives it back", async ({ page }) => {
  await stubFlows(page, "normal");
  await signIn(page);
  // The items: the theme's three choices and "Logga ut", down and up again.
  await holdsFocus(page, page.getByRole("button", { name: /^Öppna konto för/ }), page.getByRole("menu"), [
    "ArrowDown",
    "ArrowDown",
    "ArrowDown",
    "ArrowDown",
    "ArrowUp",
  ]);
});

test("the page's dialog holds focus and gives it back", async ({ page }) => {
  await stubFlows(page, "normal");
  await signIn(page);
  const dialog = page.getByRole("dialog", { name: "Anteckning" });
  await holdsFocus(page, page.getByRole("button", { name: "Anteckning" }), dialog, [
    "Tab",
    "Tab",
    "Tab",
    "Tab",
    "Shift+Tab",
    "Shift+Tab",
  ], dialog.getByRole("heading", { name: "Anteckning" }));
});

test("the warning before the login ends takes focus, holds it, and gives it back on Escape", async ({ page }) => {
  // The warning opens five minutes before the end: with 305 s left, a few seconds after the page is shown.
  await stubFlows(page, "normal");
  await stubControl(page, "session?ends_in=305");
  await signIn(page);
  await stubDefaults(page);
  // Focus somewhere on the page before the warning opens.
  const opener = page.getByRole("button", { name: "Anteckning" });
  await opener.focus();
  const warning = page.getByRole("alertdialog", { name: "Du loggas snart ut" });
  await expect(warning).toBeVisible({ timeout: 15_000 });
  // The dialog takes focus on its own controls or its title, which names it (no Tab stop, so it needs no ring).
  await focusMovesInto(warning);
  const problems: string[] = [];
  for (const key of ["Tab", "Tab", "Shift+Tab", "Tab", "Tab"]) {
    await page.keyboard.press(key);
    if (!(await inBrowser(page))) problems.push(...(await focusProblems(page, warning)));
  }
  expect.soft(problems, "focus stays inside the warning and is visible (WCAG 2.1.2, 2.4.7)").toEqual([]);
  await expect(page.getByRole("tooltip")).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(warning).toBeHidden();
  await expect(opener, "focus goes back to where it was").toBeFocused();
});

test("signed out, the sign-in dialog holds focus, with its action inside it", async ({ page }) => {
  await state("signed-out").go(page);
  const dialog = page.getByRole("alertdialog", { name: "Du behöver logga in igen" });
  // The page's control that had focus is covered: focus moves into the dialog that appeared (WCAG 2.4.3).
  await focusMovesInto(dialog);
  const problems: string[] = [];
  const reached = new Set<string>();
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press(i % 3 === 2 ? "Shift+Tab" : "Tab");
    if (await inBrowser(page)) continue;
    const found = await focusProblems(page, dialog);
    problems.push(...found);
    const stop = await focusStop(page);
    if (stop && !found.length) reached.add(stop.label);
  }
  expect.soft(problems, "focus stays inside and is visible (WCAG 2.1.2, 2.4.7)").toEqual([]);
  expect([...reached], "the dialog's own action is a Tab stop").toContain('button "Logga in igen"');
});
