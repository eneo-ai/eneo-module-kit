/**
 * The press on every control of a state, and what judges it: controls.spec.ts runs it on the module's states, and the
 * checks' own tests (harness.spec.ts) on pages built to fail it, which is why it is here and not in the spec.
 *
 * A control is pressed the way the project's person presses it: a finger taps (`hasTouch`), a mouse clicks. A control
 * that neither reaches is a fault and is reported as one. Only a control declared as a keyboard's own (`keyboardOnly`: a
 * control kept out of sight until it has focus) is given focus and Enter instead.
 *
 * Adapted from speech-to-text's gate (`eneo-ai/eneo-mod-speech-to-text` at commit `b8c3804`): known debt, to become a
 * package export when a second module needs it.
 */
import type { Browser, Locator, Page, TestInfo } from "@playwright/test";
import { Sentinel, type Expectation } from "./fixtures";
import type { State } from "./screens";

/** What a spec declares about its controls, each keyed `<state> | <role> "<name>"` with its reason. Never a pattern. */
export interface Declared {
  /** Controls that are not activated (a press the shared stub Eneo could not take back). */
  skipped?: Record<string, string>;
  /** Failures a control is meant to cause, as a state declares its own (screens.ts). */
  expects?: Record<string, { reason: string; expects: Expectation[] }>;
  /** Presses that change nothing by design: they are still activated, and judged on everything else. */
  noResponse?: Record<string, string>;
  /** Controls no pointer reaches by design: activated with focus and Enter, as a keyboard user does it. */
  keyboardOnly?: Record<string, string>;
  /**
   * Controls a finger presses in Safari that Playwright's WebKit cannot tap, with the evidence from Safari itself: these
   * alone are clicked on a WebKit touch project.
   */
  clickedInWebKit?: Record<string, string>;
}

/** The browser context a copy of a state is made with: the project's, or a self-test's own (a finger on a laptop's project). */
export type Use = TestInfo["project"]["use"];

const SELECTOR = [
  "button", "a[href]", '[role="button"]', '[role="link"]', '[role="menuitem"]', '[role="menuitemradio"]', '[role="menuitemcheckbox"]',
  '[role="tab"]', '[role="switch"]', '[role="checkbox"]', '[role="radio"]', 'input[type="checkbox"]', 'input[type="radio"]',
].join(",");

interface Control {
  index: number;
  role: string;
  name: string;
  /** The address of a link. */
  href: string | null;
  external: boolean;
  /** What the person has chosen or is on already: pressing it changes nothing by design. */
  current: boolean;
}

/** Tags the controls a person can use now with data-controls-index, in document order, and describes them. */
function tagControls(selector: string): Control[] {
  document.querySelectorAll("[data-controls-index]").forEach((element) => element.removeAttribute("data-controls-index"));
  // The modal dialog on top is the one a point inside it reaches: one opened over another covers it, wherever the two
  // stand in the document.
  const modals = [...document.querySelectorAll("dialog")].filter((dialog) => dialog.matches(":modal"));
  const onTop = (dialog: HTMLDialogElement) => {
    const box = dialog.getBoundingClientRect();
    return dialog.contains(document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2));
  };
  const modal = modals.find(onTop) ?? modals.at(-1);
  const popover = [...document.querySelectorAll("[popover]")].filter((element) => element.matches(":popover-open") && element.querySelector(selector)).at(-1);
  // Under an open modal, or an open menu, what lies behind it cannot be reached.
  const scope: ParentNode = modal ?? popover ?? document;
  const found: Control[] = [];
  const seen = new Set<Element>();
  for (const element of scope.querySelectorAll(selector)) {
    if (seen.has(element)) continue;
    seen.add(element);
    const style = getComputedStyle(element);
    const box = element.getBoundingClientRect();
    if (style.visibility === "hidden" || style.display === "none" || box.width === 0 || box.height === 0) continue;
    // What a closed <details> holds is not drawn, though a box can be read for it: there is nothing there to press.
    if (!element.checkVisibility()) continue;
    if (element.closest("[inert], [aria-hidden='true']")) continue;
    if ((element as HTMLButtonElement).disabled || element.getAttribute("aria-disabled") === "true") continue;
    const tag = element.tagName.toLowerCase();
    const role = element.getAttribute("role") ?? (tag === "a" ? "link" : tag === "input" ? (element as HTMLInputElement).type : tag);
    const labelledBy = element.getAttribute("aria-labelledby")?.split(/\s+/).map((id) => document.getElementById(id)?.textContent ?? "").join(" ");
    const name = (
      element.getAttribute("aria-label") ??
      labelledBy ??
      (element as HTMLInputElement).labels?.[0]?.textContent ??
      element.getAttribute("title") ??
      element.textContent ??
      ""
    )
      .trim()
      .replace(/\s+/g, " ")
      .slice(0, 60);
    const href = tag === "a" ? (element as HTMLAnchorElement).href : null;
    const external = href !== null && (!/^https?:$/.test(new URL(href).protocol) || new URL(href).origin !== location.origin);
    const chosen =
      (role === "radio" && ((element as HTMLInputElement).checked === true || element.getAttribute("aria-checked") === "true")) ||
      (role === "menuitemradio" && element.getAttribute("aria-checked") === "true") ||
      (role === "tab" && element.getAttribute("aria-selected") === "true");
    const here =
      tag === "a" &&
      !external &&
      ((element.getAttribute("aria-current") ?? "false") !== "false" || new URL(href!).pathname + new URL(href!).search === location.pathname + location.search);
    const current = chosen || here;
    element.setAttribute("data-controls-index", String(found.length));
    found.push({ index: found.length, role, name, href: tag === "a" ? element.getAttribute("href") : null, external, current });
  }
  return found;
}

/**
 * Installed before an activation: remembers what the page shows now, and watches for what changes in it. A region that
 * changes with nobody touching the page (a timer, a poll) is found by watching it idle first, and is not a response.
 */
function watch() {
  const key = (element: Element | null) =>
    element ? `${element.tagName.toLowerCase()}${element.getAttribute("role") ? `[${element.getAttribute("role")}]` : ""}:${(element.getAttribute("aria-label") ?? element.textContent ?? "").trim().slice(0, 40)}` : "none";
  const shown = (element: Element) => {
    const box = element.getBoundingClientRect();
    return getComputedStyle(element).visibility !== "hidden" && box.width > 0 && box.height > 0;
  };
  const overlays = () =>
    [...document.querySelectorAll('dialog[open], [role="dialog"], [role="alertdialog"], [role="menu"], [role="listbox"], [popover]')]
      .filter((element) => !element.matches('[role="tooltip"]') && (element.matches("dialog") || element.matches("[popover]") ? element.matches(":modal, :popover-open") : shown(element)))
      .map(key)
      .sort();
  const snapshot = () => ({
    url: location.href,
    focus: key(document.activeElement),
    overlays: overlays().join("|"),
    states: [
      ...[...document.querySelectorAll("[aria-pressed], [aria-checked], [aria-expanded], [aria-selected], [aria-current]")].map(
        (element) => `${key(element)}=${["pressed", "checked", "expanded", "selected", "current"].map((name) => element.getAttribute(`aria-${name}`) ?? "").join(",")}`,
      ),
      ...[...document.querySelectorAll("input")].map((input) => `${input.type}:${input.name}:${input.checked}`),
    ].join("|"),
    live: [...document.querySelectorAll('[aria-live]:not([aria-live="off"]), [role="status"], [role="alert"], [role="log"], [data-astryx-live-region]')]
      .map((element) => (element.textContent ?? "").trim())
      .join("|"),
  });
  const SEMANTIC = /^(aria-|disabled$|hidden$|open$|checked$|selected$|value$|href$|src$|role$|tabindex$)/;
  const noisy = new Set<Element>();
  let learning = true;
  const changes: string[] = [];
  const observer = new MutationObserver((records) => {
    for (const record of records) {
      const target = record.target instanceof Element ? record.target : record.target.parentElement;
      if (!target || target.closest('[role="tooltip"]')) continue;
      if (record.type === "attributes" && !SEMANTIC.test(record.attributeName ?? "")) continue;
      if (record.type === "childList" && [...record.addedNodes, ...record.removedNodes].every((node) => node.nodeType === Node.TEXT_NODE && !node.textContent?.trim())) continue;
      if (learning) noisy.add(target);
      else if (![...noisy].some((region) => region === target || region.contains(target))) changes.push(`${record.type} in ${key(target)}`);
    }
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
  const state = {
    before: snapshot(),
    endLearning() {
      learning = false;
      state.before = snapshot();
    },
    /** What differs now, as words; empty when nothing shows a response. */
    response(target: Element | null): string[] {
      const now = snapshot();
      const out: string[] = [];
      if (now.url !== state.before.url) out.push("the address changed");
      const moved = now.focus !== state.before.focus && !(target && document.activeElement && target.contains(document.activeElement));
      if (moved) out.push(`focus moved to ${now.focus}`);
      if (now.overlays !== state.before.overlays) out.push("an overlay opened or closed");
      if (now.states !== state.before.states) out.push("a state (pressed, checked, expanded, selected) changed");
      if (now.live !== state.before.live) out.push("a live region said something");
      if (changes.length) out.push(`the page changed (${changes[0]})`);
      return out;
    },
    overlays,
  };
  (window as unknown as { __controls: typeof state }).__controls = state;
}

/** The overlays that are open now (dialogs, menus, lists), each as words. */
const overlays = (page: Page) => page.evaluate(() => (window as unknown as { __controls: { overlays(): string[] } }).__controls.overlays());

interface Copy {
  page: Page;
  sentinel: Sentinel;
  /** Pages, downloads and native dialogs the page caused. */
  caused: string[];
  close(): Promise<void>;
}

/** A fresh copy of a state: a browser context of its own, with its own sentinel, and the state reached. */
async function copyOf(browser: Browser, state: State, use: Use): Promise<Copy> {
  const { viewport, deviceScaleFactor, isMobile, hasTouch, locale, timezoneId, baseURL, colorScheme, reducedMotion, forcedColors } = use;
  const context = await browser.newContext({ viewport, deviceScaleFactor, isMobile, hasTouch, locale, timezoneId, baseURL, colorScheme, reducedMotion, forcedColors });
  const sentinel = new Sentinel();
  await sentinel.watch(context);
  const caused: string[] = [];
  context.on("page", (popup) => void caused.push(`a new tab opened (${popup.url()})`));
  const page = await context.newPage();
  page.on("download", (download) => void caused.push(`a download (${download.suggestedFilename()})`));
  page.on("filechooser", () => void caused.push("a file chooser opened"));
  page.on("dialog", (dialog) => {
    caused.push(`a native ${dialog.type()} dialog`);
    void dialog.dismiss();
  });
  // A state that is not reached takes its context with it.
  await state.go(page).catch(async (error) => {
    await context.close();
    throw error;
  });
  caused.length = 0;
  return { page, sentinel, caused, close: () => context.close() };
}

/** Waits until the page has stopped changing for a moment (late data, an animation). */
async function quiet(page: Page) {
  await page.evaluate(
    () =>
      new Promise<void>((resolve) => {
        let timer = setTimeout(done, 200);
        const observer = new MutationObserver(() => {
          clearTimeout(timer);
          timer = setTimeout(done, 200);
        });
        const stop = setTimeout(done, 2_500);
        function done() {
          observer.disconnect();
          clearTimeout(timer);
          clearTimeout(stop);
          resolve();
        }
        observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true });
      }),
  );
}

/** The words a dialog's own close control starts with. */
const CLOSERS = /^(Stäng|Avbryt|Nej|Ångra|Behåll)/;

/** The overlays open now that were not there before the activation: what it opened. Waits up to `ms` for them to go. */
async function openedSince(page: Page, before: string[], ms: number) {
  const until = Date.now() + ms;
  let opened = (await overlays(page)).filter((overlay) => !before.includes(overlay));
  while (opened.length && Date.now() < until) {
    await page.waitForTimeout(100);
    opened = (await overlays(page)).filter((overlay) => !before.includes(overlay));
  }
  return opened;
}

/** Why a press did not land, from Playwright's log of it: what was in the way if it says, else its first line. */
function whyNot(error: unknown) {
  // Without the colours Playwright writes its log in.
  const lines = String(error).replace(/\u001b\[[0-9;]*m/g, "").split("\n").map((line) => line.replace(/^\s*-\s*/, "").trim());
  return lines.findLast((line) => /intercepts pointer events|outside of the viewport|not visible|not stable/.test(line)) ?? lines[0];
}

/** Activates one control in a fresh copy of the state, and says what is wrong with it, if anything. */
async function check(browser: Browser, state: State, control: Control, of: number, declared: Declared, use: Use): Promise<string[]> {
  const label = `${state.name} | ${control.role} "${control.name}"`;
  const where = `${control.role} "${control.name}" (${control.index + 1} of ${of})`;
  const problems: string[] = [];
  const finger = use.hasTouch === true && !(browser.browserType().name() === "webkit" && label in (declared.clickedInWebKit ?? {}));
  const press = (locator: Locator, timeout: number) => (finger ? locator.tap({ timeout }) : locator.click({ timeout }));
  let copy: Copy;
  try {
    copy = await copyOf(browser, state, use);
  } catch (error) {
    return [`${where}: the state could not be reached in a fresh copy: ${String(error).split("\n")[0]}`];
  }
  try {
    await quiet(copy.page);
    const tagged = await copy.page.evaluate(tagControls, SELECTOR);
    if (tagged[control.index]?.name !== control.name) return [`${where}: the state differs between two copies (found ${JSON.stringify(tagged[control.index]?.name)})`];
    copy.sentinel.expect(...(declared.expects?.[label]?.expects ?? []));
    const target = copy.page.locator(`[data-controls-index="${control.index}"]`);
    await copy.page.evaluate(watch);
    const initial = await overlays(copy.page);
    // Long enough to see what ticks by itself once a second (a timer).
    await copy.page.waitForTimeout(1_100);
    await copy.page.evaluate(() => (window as unknown as { __controls: { endLearning(): void } }).__controls.endLearning());

    if (label in (declared.keyboardOnly ?? {})) {
      await target.focus({ timeout: 2_000 });
      await copy.page.keyboard.press("Enter");
    } else {
      try {
        await press(target, 5_000);
      } catch (error) {
        // No press landed, so there is no response to judge: under something, off the screen, or never still.
        return [`${where}: a ${finger ? "finger" : "mouse"} cannot press it (${whyNot(error)})`];
      }
    }
    let navigated = false;
    let response: string[] = [];
    const start = Date.now();
    while (Date.now() - start < 1_500) {
      await copy.page.waitForTimeout(100);
      try {
        response = await copy.page.evaluate(
          (index) => (window as unknown as { __controls: { response(target: Element | null): string[] } }).__controls.response(document.querySelector(`[data-controls-index="${index}"]`)),
          control.index,
        );
      } catch {
        navigated = true;
        break;
      }
      if (response.length || copy.caused.length) break;
    }
    if (!navigated && !response.length && !copy.caused.length && !(label in (declared.noResponse ?? {}))) problems.push(`${where}: nothing happened that a person could see`);

    if (!navigated) {
      // Usable afterwards: what it opened closes on Escape or on its own close control.
      let opened = await openedSince(copy.page, initial, 0);
      if (opened.length) {
        await copy.page.keyboard.press("Escape");
        opened = await openedSince(copy.page, initial, 1_500);
      }
      if (opened.length) {
        const closer = copy.page.locator("dialog[open]").last().getByRole("button", { name: CLOSERS });
        if (await closer.count()) {
          await press(closer.first(), 3_000).catch(() => undefined);
          opened = await openedSince(copy.page, initial, 1_500);
        }
      }
      if (opened.length) problems.push(`${where}: opened ${opened.join(", ")}, and neither Escape nor a close control closed it`);
    }

    // Everything the sentinel judges. A failure that is declared may come a moment after what the person sees, so it is
    // waited for before it is called missing.
    for (const until = Date.now() + 5_000; copy.sentinel.verify().missing.length && Date.now() < until; ) await copy.page.waitForTimeout(100);
    const { unexpectedConsole, unexpectedFailed, missing } = copy.sentinel.verify();
    if (unexpectedConsole.length) problems.push(`${where}: console errors: ${unexpectedConsole.join("; ")}`);
    if (unexpectedFailed.length) problems.push(`${where}: failed requests: ${unexpectedFailed.join("; ")}`);
    if (missing.length) problems.push(`${where}: declared failures that did not occur: ${missing.join("; ")}`);
    if (copy.sentinel.redirects.length) problems.push(`${where}: redirects: ${copy.sentinel.redirects.join("; ")}`);
    if (copy.sentinel.violations.length) problems.push(`${where}: Content Security Policy: ${copy.sentinel.violations.join("; ")}`);
  } catch (error) {
    problems.push(`${where}: ${String(error).split("\n")[0]}`);
  } finally {
    await copy.close();
  }
  return problems;
}

/**
 * Presses every control of a state, each in a fresh copy of it. `controls` is how many the state has; `problems` what is
 * wrong with them; `notes` what was not pressed with a pointer, and why. `use` is the browser context of the copies: the
 * project's own unless a self-test asks for another.
 */
export async function sweep(browser: Browser, state: State, declared: Declared, use: Use) {
  const problems: string[] = [];
  const notes: string[] = [];

  const first = await copyOf(browser, state, use);
  await quiet(first.page);
  const controls = await first.page.evaluate(tagControls, SELECTOR);
  await first.close();

  for (const control of controls) {
    const label = `${state.name} | ${control.role} "${control.name}"`;
    if (label in (declared.skipped ?? {})) {
      notes.push(`skipped ${label}: ${declared.skipped![label]}`);
    } else if (control.href !== null && control.external) {
      if (!control.href || control.href === "#" || /^javascript:/i.test(control.href)) problems.push(`${control.role} "${control.name}": an external link without an address`);
      notes.push(`external ${label}: ${control.href}`);
    } else if (control.href === "#" || control.href === "") {
      problems.push(`${control.role} "${control.name}": a link without an address`);
    } else if (control.current) {
      notes.push(`current ${label}: the choice or the page it is already`);
    } else {
      if (label in (declared.keyboardOnly ?? {})) notes.push(`keyboard ${label}: ${declared.keyboardOnly![label]}`);
      if (label in (declared.clickedInWebKit ?? {})) notes.push(`clicked in WebKit ${label}: ${declared.clickedInWebKit![label]}`);
      problems.push(...(await check(browser, state, control, controls.length, declared, use)));
    }
  }
  return { controls: controls.length, problems, notes };
}
