/**
 * The session client as a person meets it, against the real backend and the stub Eneo: the login ends while the page is
 * open, and what the page and its dialogs do. Nothing of the page may show, take focus or be read while the login has
 * ended; the sign-in dialog cannot be skipped; the page comes back as it was after the new login of the same user.
 *
 * The login ends the way Eneo ends it: the stub refuses the module's next token refresh, which the page's keepalive
 * asks for within a few seconds (tokens of four seconds, refreshed at half).
 */
import type { Page } from "@playwright/test";
import { expect, signIn, stubControl, stubDefaults, stubFlows, test } from "./fixtures";

const SIGN_IN = { name: "Du behöver logga in igen" };

test.beforeEach(async ({ page }) => {
  await stubFlows(page, "normal");
  await stubDefaults(page);
});
test.afterEach(async ({ page }) => {
  await stubDefaults(page);
});

/** Signs in with tokens that live four seconds, so that ending the login takes seconds, not minutes. */
async function signInShortLived(page: Page) {
  await stubControl(page, "session?token_seconds=4");
  await signIn(page);
}

/** Eneo ends the login; the page learns at its next keepalive, or when it is looked at again. */
async function endLogin(page: Page) {
  await stubControl(page, "end-session");
  const dialog = page.getByRole("alertdialog", SIGN_IN);
  await expect
    .poll(
      async () => {
        await page.evaluate(() => document.dispatchEvent(new Event("visibilitychange")));
        return dialog.isVisible();
      },
      { timeout: 20_000, intervals: [500] },
    )
    .toBe(true);
}

/** The login in a window of its own, as the dialog's button opens it; resolves when that window has closed itself. */
async function signInAgainInWindow(page: Page, context: import("@playwright/test").BrowserContext, button: string) {
  const popup = context.waitForEvent("page");
  await page.getByRole("alertdialog").getByRole("button", { name: button }).click();
  const window = await popup;
  await window.waitForEvent("close");
}

/** How many pixels of the screen are exactly this colour: what of a coloured probe shows. */
async function pixelsOf(page: Page, [r, g, b]: [number, number, number]) {
  const png = (await page.screenshot({ caret: "initial" })).toString("base64");
  return page.evaluate(
    async ([png, r, g, b]) => {
      const image = new Image();
      image.src = `data:image/png;base64,${png}`;
      await image.decode();
      const canvas = document.createElement("canvas");
      canvas.width = image.width;
      canvas.height = image.height;
      const context = canvas.getContext("2d")!;
      context.drawImage(image, 0, 0);
      const data = context.getImageData(0, 0, image.width, image.height).data;
      let count = 0;
      for (let i = 0; i < data.length; i += 4) {
        if (Math.abs(data[i] - r) < 8 && Math.abs(data[i + 1] - g) < 8 && Math.abs(data[i + 2] - b) < 8) count++;
      }
      return count;
    },
    [png, r, g, b] as const,
  );
}

/** Where Tab can go while a modal dialog is open: its own controls, or the browser's (the document has no focus). Never the page. */
const notBehind = (page: Page) => page.evaluate(() => !document.hasFocus() || document.activeElement?.closest('[role="alertdialog"]') != null);

test("a page dialog open when the login ends is closed and covered, and is back with its edit after the new login of the same user", async ({ page, context }) => {
  await signInShortLived(page);
  await page.getByRole("button", { name: "Anteckning" }).click();
  const note = page.getByRole("dialog", { name: "Anteckning" });
  await note.getByLabel("Anteckning").fill("Kom ihåg Zara");

  await endLogin(page);
  await expect(note, "the page's own dialog is closed while signed out").toBeHidden();
  const tree = await page.locator("body").ariaSnapshot();
  expect(tree, "the sign-in dialog is in the accessibility tree, whole").toMatch(/heading "Du behöver logga in igen"[\s\S]*button "Logga in igen"/);
  expect(tree, "and nothing of the page").not.toMatch(/Välj ett flöde|Anteckning|Nämndmöte/);
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeHidden();

  await stubDefaults(page);
  await signInAgainInWindow(page, context, "Logga in igen");
  await expect(page.getByRole("alertdialog", SIGN_IN)).toBeHidden();
  await expect(note, "the page's dialog is back, as a modal").toBeVisible();
  await expect(note.getByLabel("Anteckning"), "with its edit, kept above the dialog").toHaveValue("Kom ihåg Zara");
  expect(await note.evaluate((element) => element.matches(":modal"))).toBe(true);
});

test("nothing but the new login closes the sign-in dialog: not Escape, not a click beside it, not a close request", async ({ page }) => {
  await signInShortLived(page);
  await endLogin(page);
  const dialog = page.getByRole("alertdialog", SIGN_IN);
  await expect(dialog.getByRole("button", { name: "Stäng" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await page.mouse.click(2, 2);
  await expect(dialog).toBeVisible();
  // A second close request without a new user action (Android's back is one) closes a dialog no handler can keep.
  for (let request = 1; request <= 2; request++) {
    await dialog.evaluate((element) => (element as HTMLDialogElement).close());
    await expect.poll(() => dialog.evaluate((element) => element.matches(":modal")), `modal again after close request ${request}`).toBe(true);
  }
  for (let i = 0; i < 12; i++) {
    await page.keyboard.press("Tab");
    expect(await notBehind(page), `Tab ${i + 1} stays in the dialog or leaves the page for the browser's own controls`).toBe(true);
  }
});

/** What a native dialog of the page is that the module did not close (a mistake the cover is the net for), in a colour of its own. */
async function leaveProbeOpen(page: Page) {
  await page.evaluate(() => {
    const probe = document.createElement("dialog");
    probe.setAttribute("aria-label", "Sidans sond");
    // Property by property: the page's Content Security Policy refuses a style attribute set as text.
    for (const [name, value] of [["background", "rgb(255, 0, 255)"], ["border", "0"], ["padding", "0"], ["width", "60vw"], ["height", "50vh"]]) probe.style.setProperty(name, value);
    probe.innerHTML = '<button type="button" id="probe-button">Sondens knapp</button>';
    document.querySelector('[role="main"]')!.append(probe);
    probe.showModal();
  });
}

test.describe("a native dialog the module left open when the login ended", () => {
  test("is hidden behind the opaque backdrop, and cannot take focus", async ({ page, browserName }) => {
    // Playwright's WebKit puts an inline style in the page for a screenshot, which the page's policy refuses: the
    // pixels of the backdrop are proved in Chromium and Firefox. (The focus half of the contract differs, below.)
    test.skip(browserName === "webkit", "a screenshot in WebKit adds an inline style that the strict CSP refuses");
    await signInShortLived(page);
    await leaveProbeOpen(page);
    expect(await pixelsOf(page, [255, 0, 255]), "the probe shows while the login lasts").toBeGreaterThan(1_000);
    await endLogin(page);
    expect(await pixelsOf(page, [255, 0, 255]), "nothing of it shows through the backdrop").toBe(0);
    const reached = await page.evaluate(() => {
      const button = document.getElementById("probe-button")!;
      button.focus();
      return document.activeElement === button;
    });
    expect(reached, "its button cannot take focus").toBe(false);
    expect(await page.locator("body").ariaSnapshot(), "and it is not in the accessibility tree").not.toMatch(/Sidans sond|Sondens knapp/);
  });

  test("WebKit: the backdrop hides it, but its button can still take focus (the engine does not block a modal that was open first), so a module closes its dialogs with useSignedOut", async ({ page, browserName }) => {
    test.skip(browserName !== "webkit", "Chromium and Firefox block it: the test above");
    await signInShortLived(page);
    await leaveProbeOpen(page);
    await endLogin(page);
    const reached = await page.evaluate(() => {
      const button = document.getElementById("probe-button")!;
      button.focus();
      return document.activeElement === button;
    });
    // Pinned as it is, so that a WebKit that blocks it makes this fail and the exception is taken out of the docs.
    expect(reached, "WebKit lets a dialog left open under the sign-in dialog take focus").toBe(true);
  });
});

test("someone else's login keeps the page covered and says whom to sign in as; the page's own user lifts it", async ({ page, context }) => {
  await signInShortLived(page);
  await endLogin(page);
  await stubDefaults(page);
  await stubControl(page, "login-as?user=sara");
  await signInAgainInWindow(page, context, "Logga in igen");
  const dialog = page.getByRole("alertdialog", SIGN_IN);
  await expect(dialog).toContainText("Du är inloggad som Sara Holm. Logga in som Erik Lund för att fortsätta.");
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" }), "the page stays covered").toBeHidden();
  await stubControl(page, "login-as?user=erik");
  await signInAgainInWindow(page, context, "Logga in igen");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeVisible();
});

test("the warning five minutes before the end renews in a window bound to this user; a renewal that signed in someone else is refused", async ({ page, context }) => {
  await stubControl(page, "session?ends_in=200");
  await signIn(page);
  await stubDefaults(page);
  const warning = page.getByRole("alertdialog", { name: "Du loggas snart ut" });
  await expect(warning).toBeVisible();
  await expect(warning).toContainText(/Inloggningen upphör kl\. \d\d:\d\d/);
  await expect(warning.getByRole("button", { name: "Stäng" })).toBeVisible();

  await stubControl(page, "login-as?user=sara");
  const popup = context.waitForEvent("page");
  await warning.getByRole("button", { name: "Fortsätt arbeta" }).click();
  const refused = await popup;
  await expect(refused.getByRole("heading", { level: 1, name: "Du loggade in som en annan användare" })).toBeVisible();
  await expect(refused.getByRole("main")).toContainText("Stäng fönstret och logga in som Erik Lund för att fortsätta.");
  await refused.close();
  await expect(warning, "the warning stays: the page's login is still the one in the cookie").toBeVisible();

  await stubControl(page, "login-as?user=erik");
  await signInAgainInWindow(page, context, "Fortsätt arbeta");
  await expect(warning).toBeHidden();
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeVisible();
});

for (const height of [256, 200]) {
  test(`at 320 x ${height} the sign-in dialog scrolls as a whole and every part is usable, with no scrolling in two directions`, async ({ page }) => {
    await signInShortLived(page);
    await page.setViewportSize({ width: 320, height });
    await endLogin(page);
    const dialog = page.getByRole("alertdialog", SIGN_IN);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "horizontal scroll (WCAG 1.4.10)").toBe(true);
    const box = (await dialog.boundingBox())!;
    expect(box.y >= 0 && box.y + box.height <= height && box.x >= 0 && box.x + box.width <= 320, "the dialog is within the screen").toBe(true);
    await expect(dialog.getByRole("heading", SIGN_IN)).toBeInViewport({ ratio: 1 });
    const button = dialog.getByRole("button", { name: "Logga in igen" });
    await button.evaluate((element) => (element as HTMLElement).blur());
    await button.focus();
    await expect(button, "the sign-in button is whole in view when it has the focus").toBeInViewport({ ratio: 1 });
  });
}
