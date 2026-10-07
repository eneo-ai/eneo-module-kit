import { settle } from "./checks";
import { expect, signIn, test } from "./fixtures";
import { STATES } from "./screens";

test("supporting descriptions remain readable at the standard text size", async ({ page }) => {
  await signIn(page);
  const description = page.getByText("Transkriberar mötet och skapar en rapport.");
  await expect(description).toBeVisible();
  expect(await description.evaluate((element) => parseFloat(getComputedStyle(element).fontSize))).toBeGreaterThanOrEqual(14);
});

test("the note field has one focus frame following its own edge", async ({ page }, info) => {
  await signIn(page);
  await page.getByRole("button", { name: "Anteckning", exact: true }).click();
  const field = page.getByRole("textbox", { name: "Anteckning", exact: true });
  await field.focus();
  await settle(page);
  const frames = await field.evaluate((control) => {
    const frames: { outset: number; shadow: string }[] = [];
    for (let element: Element | null = control; element && !element.matches('[role="dialog"]'); element = element.parentElement) {
      const style = getComputedStyle(element);
      if (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) {
        frames.push({ outset: parseFloat(style.outlineOffset), shadow: style.boxShadow });
      }
    }
    return frames;
  });
  expect(frames, "a focused field has one frame").toHaveLength(1);
  expect(frames[0].outset, "the frame follows the field edge").toBeLessThanOrEqual(0);
  expect(frames[0].shadow, "no second shadow beside the frame").toBe("none");
  await expect(field).toBeFocused();
  if (process.env.SHOTS && /^(phone-390|laptop-1440)/.test(info.project.name)) {
    await page.screenshot({ path: `test-results/shots/${info.project.name}/note-focused.png`, fullPage: true, caret: "initial" });
  }
});

test("the session warning names itself on opening without framing the heading", async ({ page }, info) => {
  await STATES.find((state) => state.name === "session-warning")!.go(page);
  await settle(page);
  const warning = page.getByRole("alertdialog", { name: "Du loggas snart ut" });
  const title = warning.getByRole("heading", { name: "Du loggas snart ut" });
  await expect(title).toBeFocused();
  expect(await title.evaluate((heading) => {
    for (let element: Element | null = heading; element && !element.matches('[role="alertdialog"]'); element = element.parentElement) {
      const style = getComputedStyle(element);
      if (style.outlineStyle !== "none" && parseFloat(style.outlineWidth) > 0) return true;
    }
    return false;
  }), "a title receiving initial focus is not a control").toBe(false);
  if (process.env.SHOTS && /^(phone-390|laptop-1440)/.test(info.project.name)) {
    await page.screenshot({ path: `test-results/shots/${info.project.name}/warning-initial-focus.png`, fullPage: true, caret: "initial" });
  }
  await page.keyboard.press("Tab");
  await expect(warning.getByRole("button", { name: "Stäng", exact: true })).toBeFocused();
});
