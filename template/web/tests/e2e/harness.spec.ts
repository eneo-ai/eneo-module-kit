/**
 * The gate's own checks against pages built to fail them: a check that passes these would pass the module's faults too.
 * They run once, at one width. Copied from speech-to-text's gate (known debt, like checks.ts).
 */
import { expect, test } from "@playwright/test";
import { axe, blocking, clippedFocus, focusStop, reflow, settle, tabWalk, targetSizes } from "./checks";
import { signIn, stubFlows } from "./fixtures";

test.beforeEach(({}, info) => test.skip(info.project.name !== "laptop-1440-light", "the checks' own tests run once"));

test("a keyboard trap that cycles between two controls is caught", async ({ page }) => {
  await page.setContent(`
    <button id="a">A</button><button id="b">B</button><button id="c">C</button>
    <script>
      // Tab from B goes back to A, and Shift+Tab from A to B: focus never reaches C or leaves.
      document.getElementById("b").addEventListener("keydown", (e) => {
        if (e.key === "Tab" && !e.shiftKey) { e.preventDefault(); document.getElementById("a").focus(); }
      });
    </script>`);
  const { left } = await tabWalk(page, 12);
  expect(left, "the walk says focus never left the page").toBe(false);
});

test("a control in a dialog is in a dialog, native or with the role, so the page's reading order does not judge it", async ({ page }) => {
  await page.setContent(`
    <main><h1>Prov</h1><button>Bakom</button></main>
    <dialog id="native" aria-label="Namnge"><button>Spara</button></dialog>
    <div role="alertdialog" aria-label="Fråga"><button>Svara</button></div>
    <script>document.getElementById("native").showModal()</script>`);
  const inDialog = async (name: string) => {
    await page.getByRole("button", { name }).evaluate((element) => (element as HTMLElement).focus());
    return (await focusStop(page))?.inDialog;
  };
  expect(await inDialog("Spara"), "a native <dialog> has no role attribute").toBe(true);
  expect(await inDialog("Svara")).toBe(true);
  // The page behind a modal dialog cannot take focus, so what is not in a dialog is read where nothing is open.
  await page.evaluate(() => (document.getElementById("native") as HTMLDialogElement).close());
  expect(await inDialog("Bakom"), "the page itself is not a dialog").toBe(false);
});

test("a WCAG violation blocks the gate whatever axe calls its impact", async ({ page }) => {
  // html-xml-lang-mismatch is WCAG 3.1.1 and axe calls it moderate.
  await page.setContent(`<html lang="sv" xml:lang="en"><head><title>Prov</title></head><body><main><h1>Prov</h1></main></body></html>`);
  const scan = await axe(page);
  expect(blocking(scan.violations).map((v) => v.id)).toContain("html-xml-lang-mismatch");
});

test("colours are measured once a colour change has ended, not halfway through it", async ({ page }) => {
  // A button enabled a moment before the scan fades from its disabled grey to its colour.
  await page.setContent(`
    <style>
      button { color: #fff; background: #ddd; border: 0; padding: 8px; transition: background-color 1s linear; }
      button.on { background: #1d4ed8; }
    </style>
    <main><h1>Prov</h1><button>Godkänn</button></main>`);
  await page.evaluate(() => requestAnimationFrame(() => document.querySelector("button")!.classList.add("on")));
  await page.waitForFunction(() => document.getAnimations().length > 0);
  const scan = await axe(page);
  expect(scan.violations.map((v) => v.id)).not.toContain("color-contrast");
});

test("a focus outline that cannot be seen is not taken for a focus indicator", async ({ page }) => {
  await page.setContent(`
    <style>
      body { background: #fff; }
      button { background: #fff; color: #111; border: 1px solid #767676; outline: none; }
      #white:focus-visible { outline: 3px solid #fff; outline-offset: 2px; }
      #black:focus-visible { outline: 3px solid #111; outline-offset: 2px; }
    </style>
    <p><button id="white">Vit ring</button></p>
    <p><button id="black">Svart ring</button></p>`);
  await page.keyboard.press("Tab");
  expect((await focusStop(page))?.indicator, "white on white").toBe(false);
  await page.keyboard.press("Tab");
  expect((await focusStop(page))?.indicator, "black on white").toBe(true);
});

test("a region taller than the window is held to the ring on its edges that show, and a ring that shows nowhere fails", async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 600 });
  await page.setContent(`
    <style>
      body { margin: 0; background: #fff; }
      .region { box-sizing: border-box; margin: 520px 40px 40px; height: 1400px; border: 1px solid #ddd; outline: none; }
      #ringed:focus-visible { outline: 2px solid #111; outline-offset: -2px; }
    </style>
    <div class="region" id="ringed" tabindex="0" role="region" aria-label="Med ring"></div>
    <div class="region" id="bare" tabindex="0" role="region" aria-label="Utan ring"></div>`);
  // Its top and 80 px of its sides show, as a long list below the fold does; its bottom is far past the window's.
  await page.keyboard.press("Tab");
  await page.evaluate(() => window.scrollTo(0, 0));
  expect((await focusStop(page))?.indicator, "a ring on the top and the sides that show").toBe(true);
  await page.keyboard.press("Tab");
  await page.evaluate(() => document.getElementById("bare")!.scrollIntoView({ block: "start" }));
  expect((await focusStop(page))?.indicator, "no ring at all").toBe(false);
});

test("a list that holds the focus itself is measured by its own ring", async ({ page }) => {
  // A combobox's list in a bottom sheet keeps the focus and shows its option with aria-activedescendant: it cannot hand
  // the focus on to be measured without it, as a menu's item can.
  await page.setContent(`
    <style>
      body { background: #fff; }
      [role="listbox"] { outline: none; border: 1px solid #767676; padding: 4px; }
      [role="listbox"]:focus-visible { outline: 3px solid #111; outline-offset: 2px; }
    </style>
    <div role="listbox" tabindex="0" aria-label="Talare" aria-activedescendant="erik">
      <div role="option" id="erik" aria-selected="true">Erik Lund</div><div role="option" id="sara">Sara Holm</div>
    </div>`);
  await page.keyboard.press("Tab");
  expect((await focusStop(page))?.indicator).toBe(true);
});

test("a focus ring is measured under a policy that refuses data: pictures", async ({ page }) => {
  // The screenshots are read back in the page: a module's policy may leave data: out of img-src.
  await page.route("**/fixture/policy", (route) =>
    route.fulfill({
      contentType: "text/html; charset=utf-8",
      headers: { "content-security-policy": "img-src 'self'" },
      body: `<!doctype html><html lang="sv"><title>Prov</title><style>button { outline: none } button:focus-visible { outline: 3px solid #111; outline-offset: 2px }</style><main><button>Spara</button></main>`,
    }),
  );
  await page.goto("/fixture/policy");
  await page.keyboard.press("Tab");
  expect((await focusStop(page))?.indicator).toBe(true);
});

test("text past the window's left edge is reported, as text past its right is", async ({ page }) => {
  await page.setContent(`<main><h1>Prov</h1><p style="position: relative; left: -60px">Utanför till vänster</p></main>`);
  expect((await reflow(page)).beyond).toEqual([expect.stringContaining("Utanför till vänster")]);
});

test("focus is measured where a phone shows it, also on a page wider than the phone", async ({ browser }) => {
  // Content past the edge makes a phone's layout viewport wider than the screen; scrolled down, the box a script
  // reads and the picture of the screen then disagree by the visual viewport's offset.
  const context = await browser.newContext({ viewport: { width: 320, height: 568 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
  const page = await context.newPage();
  await page.setContent(`
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
      body { margin: 0; font: 16px sans-serif; }
      button { margin: 8px; outline: none; }
      button:focus-visible { outline: 3px solid #111; outline-offset: 2px; }
    </style>
    <div style="width: 360px; height: 1200px"></div>
    <button>Längst ner</button>
    <div style="height: 900px"></div>`);
  await page.keyboard.press("Tab");
  expect((await focusStop(page))?.indicator, "a black ring on white").toBe(true);
  await context.close();
});

test("a hit area grown by a pseudo-element is measured from the padding box, where its insets apply", async ({ page }) => {
  // 24 px across the border box, 16 px inside its 4 px border: grown by 12 px, the hit area is 40 px, not 48.
  await page.setContent(`
    <style>
      button { position: relative; box-sizing: border-box; width: 24px; height: 24px; border: 4px solid #333; padding: 0; }
      button::after { content: ""; position: absolute; inset: -12px; }
    </style>
    <button aria-label="Liten"></button>`);
  expect(await targetSizes(page, 44, false)).toEqual(['button "Liten" 24×24']);
});

test("a field's box counts as its control's target only for the control it activates", async ({ page }) => {
  await page.setContent(`
    <style>
      .astryx-text-input, .plain { display: flex; align-items: center; height: 44px; width: 240px; border: 1px solid #767676; }
      input { height: 20px; border: 0; }
      button { flex-shrink: 0; width: 20px; height: 20px; padding: 0; margin-left: 40px; }
    </style>
    <div class="astryx-text-input"><input aria-label="I fältets ruta"><button aria-label="Rensa"></button></div>
    <div class="plain" style="margin-top: 40px"><input aria-label="I en vanlig ruta"></div>`);
  // The design system's field is credited with its box; a control of its own inside that box, and a field in any
  // other box, are measured as they are.
  expect(await targetSizes(page, 44, false)).toEqual(['button "Rensa" 20×20', expect.stringMatching(/^input "I en vanlig ruta" \d+×20$/)]);
});

test("the design system's field box does activate its control, so crediting it is true", async ({ browser, browserName, baseURL }) => {
  // The page's own field, in its dialog, on a touch screen at a phone's width (a phone's layout viewport where the engine
  // can emulate one: not Firefox).
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: browserName !== "firefox", hasTouch: true, baseURL });
  const page = await context.newPage();
  await stubFlows(page, "normal");
  await signIn(page);
  await page.getByRole("button", { name: "Anteckning" }).tap();
  const dialog = page.getByRole("dialog", { name: "Anteckning" });
  await expect(dialog).toBeVisible();
  // At rest: the dialog opens from a smaller scale.
  await settle(page);
  const field = dialog.getByRole("textbox", { name: "Anteckning" });
  const box = (await dialog.locator(".astryx-text-input").boundingBox())!;
  expect(box.height, "the box is a 44 px target on a touch screen").toBeGreaterThanOrEqual(44);
  await dialog.getByRole("button", { name: "Klar" }).focus();
  // The box's own edge, above the input inside it.
  await page.touchscreen.tap(box.x + box.width / 2, box.y + 2);
  await expect(field, "a tap on the box's edge reaches the field").toBeFocused();
  await context.close();
});

test("a target in an open modal dialog is measured even under an inert ancestor", async ({ page }) => {
  await page.setContent(`<div inert><dialog><button aria-label="Liten" style="width: 10px; height: 10px; padding: 0"></button></dialog></div>`);
  await page.evaluate(() => document.querySelector("dialog")!.showModal());
  expect(await targetSizes(page, 24, false)).toEqual(['button "Liten" 10×10']);
});

test("a slider's control is its target, and a control too thin for a finger is reported", async ({ page }) => {
  // The design system's slider: a 20 px thumb inside a control, which takes the press and is the box that counts.
  const slider = (height: number) => `
    <div class="astryx-slider-control" data-orientation="horizontal" style="height: ${height}px; width: 240px">
      <div role="slider" aria-label="Läge" tabindex="0" style="width: 20px; height: 20px"></div>
    </div>`;
  await page.setContent(slider(44));
  expect(await targetSizes(page, 44, false), "44 px tall: the control is the target").toEqual([]);
  await page.setContent(slider(20));
  expect(await targetSizes(page, 44, false), "20 px tall: as the design system draws it").toEqual(['slider "Läge" 20×20']);
});

test("a focus ring cut by a scroller is reported; the clipping outside a modal dialog is not asked, the dialog's own is", async ({ page }) => {
  const ring = "outline: 3px solid #111; outline-offset: 2px; margin: 0";
  await page.setContent(`<div style="overflow: hidden"><button id="cut" style="${ring}">Klippt</button></div>`);
  await page.locator("#cut").focus();
  expect(await clippedFocus(page), "a ring that the next box clips").toMatch(/^div/);

  // The page's own clip does not reach a modal dialog (the top layer); a dialog that scrolls clips its own content.
  const dialog = (padding: number) => `
    <div style="overflow: clip; width: 200px; height: 60px">
      <dialog style="width: 300px; padding: ${padding}px; overflow: auto"><button id="in" style="${ring}">I dialogen</button></dialog>
    </div>`;
  for (const [padding, cut] of [[20, null], [0, "dialog."]] as const) {
    await page.setContent(dialog(padding));
    await page.evaluate(() => document.querySelector("dialog")!.showModal());
    await page.locator("#in").focus();
    expect(await clippedFocus(page), `a dialog with ${padding} px of room`).toBe(cut);
  }
});
