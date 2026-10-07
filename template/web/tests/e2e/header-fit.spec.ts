/**
 * The top bar at the narrowest width with WCAG 1.4.12 text spacing. The full product name must remain readable
 * beside the account control, including when the system font is wider than the development machine's.
 */
import { expect, signIn, test } from "./fixtures";

// A constructed style sheet: the page's Content Security Policy refuses an inline <style>.
const TEXT_SPACING = "* { line-height: 1.5 !important; letter-spacing: 0.12em !important; word-spacing: 0.16em !important; } p { margin-bottom: 2em !important; }";
const GAP = 8;

test("at 320 px with text spacing the brand and the account button keep apart, and the name is whole", async ({ page }, info) => {
  test.skip(info.project.name !== "phone-320-light", "the narrowest width");
  await signIn(page);
  await page.evaluate((css) => {
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(css);
    document.adoptedStyleSheets = [...document.adoptedStyleSheets, sheet];
  }, TEXT_SPACING);
  const brand = page.getByRole("link", { name: /^Eneo-modul –/ });
  await brand.locator('img[data-brand-logo="light"]').evaluate((image: HTMLImageElement) => image.decode());
  await page.evaluate(() => document.fonts.ready);
  const account = page.getByRole("button", { name: /^Öppna konto för/ });
  const [brandBox, accountBox] = [await brand.boundingBox(), await account.boundingBox()];
  expect(brandBox && accountBox, "both are shown").toBeTruthy();
  expect(accountBox!.x - (brandBox!.x + brandBox!.width), "the room between them").toBeGreaterThanOrEqual(GAP);
  const name = brand.getByText("Eneo-modul", { exact: true });
  expect(await name.evaluate((element) => element.scrollWidth <= element.clientWidth), "the name is not cut off").toBe(true);
});
