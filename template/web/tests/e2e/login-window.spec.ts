/**
 * The login window the session dialog opens, when the sign-in in it fails, through the dialog's own button: the window
 * says so and stays, tells the page nothing, and is the same after a reload; the page keeps its cover and what it holds.
 * The dialog marks the window as it opens it: the mark is in the page's sessionStorage for the moment of the call, and
 * the browser gives a window opened with an opener a copy. These cases are the proof of that copy; the unit tests show
 * each side alone. The mark outlasts a page on the way that sets Cross-Origin-Opener-Policy (the window's opener does
 * not). An ordinary tab is never marked. Shown in Chromium and WebKit (playwright.config.ts).
 *
 * The stub Eneo fails a sign-in by giving a ticket its exchange refuses (`__stub/module-login?ticket=refused`): the
 * module's callback ends as `exchange_failed`, on `/?auth_error=exchange_failed`.
 */
import type { BrowserContext, Page } from "@playwright/test";
import { endLogin, expect, signIn, signInShortLived, stubControl, stubDefaults, stubFlows, test } from "./fixtures";

const FAILED = { level: 1, name: "Inloggningen kunde inte slutföras" } as const;

test.beforeEach(async ({ page }) => {
  await stubFlows(page, "normal");
  await stubDefaults(page);
});
test.afterEach(async ({ page }) => {
  await stubDefaults(page);
});

/** What the module's tabs are told on the session channel from now on, as `page` hears it. */
async function listen(page: Page) {
  await page.evaluate(() => {
    const heard: unknown[] = [];
    const channel = new BroadcastChannel("eneo-module:session");
    channel.addEventListener("message", (event) => heard.push(event.data));
    Object.assign(window, { __heard: heard, __channel: channel });
  });
  return () => page.evaluate(() => (window as unknown as { __heard: unknown[] }).__heard);
}

/** Presses the dialog's button; the window it opens. */
async function openWindow(page: Page, context: BrowserContext, button: string) {
  const opened = context.waitForEvent("page");
  await page.getByRole("alertdialog").getByRole("button", { name: button }).click();
  return opened;
}

/** The window says its sign-in failed, and nothing more: no sign-in of its own, no word to the page, no code; it stays, also after a reload. */
async function failsAndStays(popup: Page, heard: () => Promise<unknown[]>) {
  for (const load of ["first", "after a reload"]) {
    await expect(popup.getByRole("heading", FAILED), load).toBeVisible();
    await expect(popup.getByRole("main")).toHaveText(/Stäng fönstret och försök igen från sidan\./);
    await expect(popup.getByRole("link", { name: "Logga in med Eneo" })).toHaveCount(0);
    expect(await popup.locator("body").innerText(), "no code is shown").not.toMatch(/exchange_failed|auth_error/);
    // Long enough for a word on the channel and a close, which come at once if they come.
    await popup.waitForTimeout(500);
    expect(popup.isClosed(), "it stays").toBe(false);
    expect(await heard(), "it tells the page nothing").toEqual([]);
    if (load === "first") await popup.reload();
  }
}

test("a sign-in that fails in the window after the login ended says so and stays; the page stays covered and keeps its note", async ({ page, context }) => {
  await signInShortLived(page);
  await page.getByRole("button", { name: "Anteckning" }).click();
  const note = page.getByRole("dialog", { name: "Anteckning" });
  await note.getByLabel("Anteckning").fill("Kom ihåg Zara");
  await endLogin(page);
  await stubDefaults(page);
  const heard = await listen(page);

  await stubControl(page, "module-login?ticket=refused");
  const popup = await openWindow(page, context, "Logga in igen");
  await failsAndStays(popup, heard);
  const cover = page.getByRole("alertdialog", { name: "Du behöver logga in igen" });
  await expect(cover, "the page stays covered").toBeVisible();

  // As the window says: closed, and tried again from the page. A completed sign-in tells the page and closes.
  await popup.close();
  await stubControl(page, "module-login?ticket=normal");
  const again = await openWindow(page, context, "Logga in igen");
  await expect.poll(() => again.isClosed(), { message: "the new window signs in and closes itself" }).toBe(true);
  await expect(cover).toBeHidden();
  await expect(note.getByLabel("Anteckning"), "the note is back with its text").toHaveValue("Kom ihåg Zara");
});

test("a renewal that fails in the window before the end says so and stays; the warning stays", async ({ page, context }) => {
  await stubControl(page, "session?ends_in=200");
  await signIn(page);
  await stubDefaults(page);
  const warning = page.getByRole("alertdialog", { name: "Du loggas snart ut" });
  await expect(warning).toBeVisible();
  const heard = await listen(page);

  await stubControl(page, "module-login?ticket=refused");
  const popup = await openWindow(page, context, "Fortsätt arbeta");
  await failsAndStays(popup, heard);
  await expect(warning, "the page's login is the one it had").toBeVisible();
});

test("behind a page that sets Cross-Origin-Opener-Policy the window loses its opener and still knows itself: a failure stays, a success tells the page", async ({ page, context }, info) => {
  await stubControl(page, "session?ends_in=200");
  await signIn(page);
  await stubDefaults(page);
  const warning = page.getByRole("alertdialog", { name: "Du loggas snart ut" });
  await expect(warning).toBeVisible();
  const heard = await listen(page);

  await stubControl(page, "module-login?ticket=refused&opener_policy=same-origin");
  const popup = await openWindow(page, context, "Fortsätt arbeta");
  await expect(popup.getByRole("heading", FAILED)).toBeVisible();
  expect(await popup.evaluate(() => window.opener === null), "the opener is gone: the policy page took effect").toBe(true);
  await failsAndStays(popup, heard);

  // The failed window is left open: the dialog's handle to it was cut with its opener.
  await stubControl(page, "module-login?ticket=normal&opener_policy=same-origin");
  const again = await openWindow(page, context, "Fortsätt arbeta");
  await expect(warning, "the page heard of the renewal and read its new end").toBeHidden();
  expect(await heard()).toEqual(["signed-in"]);
  expect(popup.isClosed(), "the dialog cannot close a window whose opener was cut").toBe(false);
  await expect(popup.getByRole("heading", FAILED), "it still shows its failure").toBeVisible();
  // Whether the window could close itself once its opener was gone: recorded, not promised.
  await expect.poll(async () => again.isClosed() || (await again.getByRole("heading", { level: 1, name: "Du är inloggad igen" }).isVisible())).toBe(true);
  info.annotations.push({ type: "window", description: again.isClosed() ? "closed itself after the policy page" : "stayed open after the policy page" });
});

test("a second press after a failure, with the failed window still open: a new window signs in, the failed one is closed, and the page keeps its note", async ({ page, context }) => {
  await signInShortLived(page);
  await page.getByRole("button", { name: "Anteckning" }).click();
  const note = page.getByRole("dialog", { name: "Anteckning" });
  await note.getByLabel("Anteckning").fill("Kom ihåg Zara");
  await endLogin(page);
  await stubDefaults(page);
  const heard = await listen(page);

  await stubControl(page, "module-login?ticket=refused");
  const failed = await openWindow(page, context, "Logga in igen");
  await expect(failed.getByRole("heading", FAILED)).toBeVisible();

  await stubControl(page, "module-login?ticket=normal");
  const again = await openWindow(page, context, "Logga in igen");
  // The `page` event fires only for a new page: `again` is a window of its own.
  await expect.poll(() => failed.isClosed(), { message: "the failed window is closed" }).toBe(true);
  await expect.poll(() => again.isClosed(), { message: "the new window signs in and closes itself" }).toBe(true);
  await expect(page.getByRole("alertdialog", { name: "Du behöver logga in igen" })).toBeHidden();
  expect(await heard()).toEqual(["signed-in"]);
  await expect(note.getByLabel("Anteckning"), "the note is back with its text").toHaveValue("Kom ihåg Zara");
});

test("an ordinary tab whose sign-in fails shows the sign-in screen with its alert, and signs in on the next try", async ({ page }) => {
  await page.goto("/");
  await stubControl(page, "module-login?ticket=refused");
  const signInLink = page.getByRole("link", { name: "Logga in med Eneo" });
  await signInLink.click();
  await expect(page.getByRole("alert")).toHaveText("Inloggningen kunde inte slutföras. Försök igen.");
  await expect(page.getByRole("heading", FAILED), "not the login window's view").toHaveCount(0);

  await stubControl(page, "module-login?ticket=normal");
  await signInLink.click();
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeVisible();
});
