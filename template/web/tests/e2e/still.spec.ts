/**
 * What is on screen stands still when an answer arrives. Each page is opened by its address with the backend's answers
 * handed to it one at a time, in the order it asked for them: an answer is fetched at once and kept until the page has
 * stood still after the one before, and what is on screen (controls, headings, text, pictures) is measured before and
 * after each. Something that was on screen before an answer and has moved after it fails the page: what arrives late
 * (a button added when its data is read, a notice read after the list it stands above) must have its place from the
 * first draw, or it moves what a finger is on its way to and what an eye is reading.
 *
 * The clock does not decide the result. The answers come in the page's own order, each is whole before it is handed
 * over, the page is measured when its document has stopped changing, and nothing is pressed: a fast machine and a slow
 * one take the same steps. A page reached by a press is not here, because the press and the answers would race; what
 * a press sets in motion gets a test of its own that holds one answer. What is animating is measured when it rests.
 * Code the page fetches when it first needs it (a lazily imported part) is waited for before the next answer is handed
 * over, so its arrival belongs to the step that asked for it.
 *
 * A state is first reached as the gate reaches it (screens.ts), which leaves the stub Eneo and the login as the page
 * needs them; signing in is a press on the sign-in page, a document of its own. Then the page's address is opened
 * again, alone, and that opening is the one measured.
 *
 * Adapted from speech-to-text's gate (`eneo-ai/eneo-mod-speech-to-text` at commit `194ae4c`): known debt, to become a
 * package export when a second module needs it.
 */
import type { Locator, Page } from "@playwright/test";
import { expect, stubFlows, test } from "./fixtures";
import { STATES } from "./screens";

// The narrowest phone, a phone, a tablet and a laptop: the layouts a late answer can move differently.
const LAYOUTS = ["phone-320-light", "phone-390-light", "tablet-portrait", "laptop-1440-light"];
// Less than this is a rounding of the layout, not a move.
const MOVED_PX = 4;

/**
 * The gate's states that are a page as it opens, each with what shows that the page is drawn. A state reached by a
 * press on its page (the account menu), or by something that happens while the page is open (the login ending), is
 * not one. A new page adds its states here.
 */
const BY_ADDRESS: Record<string, (page: Page) => Locator> = {
  signin: (page) => page.getByRole("link", { name: "Logga in med Eneo" }),
  flows: (page) => page.getByRole("list", { name: "Flöden" }),
  "flows-empty": (page) => page.getByRole("heading", { level: 2, name: /Det finns inga publicerade flöden/ }),
  "flows-error": (page) => page.getByText("Flödena kunde inte visas."),
  "session-warning": (page) => page.getByRole("alertdialog", { name: "Du loggas snart ut" }),
  "not-found": (page) => page.getByRole("heading", { level: 1, name: "Sidan finns inte." }),
};

// The organisation's mark is 40 px high (base.css of @eneo-ai/module-kit) and arrives when the brand is read. With a
// mouse the top bar is 48 px until then and 56 px after, and the page under it moves; on a touch screen the bar is
// 60 px from the first draw and stands still. The fix is the package's: the bar keeps the mark's height from the
// first draw.
// The organisation is read after the page is drawn (decision K10 of the kit: the same built page serves every
// deployment, and nothing is written into it). Its mark then takes its place before the product's name, which moves
// along the bar; the bar itself keeps its height (base.css), so nothing under it moves.
const BRAND = {
  when: / moved 0 px down and \d+ px right when GET \/api\/branding answered$/,
  why: "the organisation's mark arrives before the product's name in the top bar (K10: branding is read at runtime)",
};

/**
 * Moves that are left, each one answer on one page in one layout, with why it is left. An entry must still happen:
 * when the page stands still, the line goes. The organisation is the one playwright.config.ts gives its own backend;
 * a module that is already running (E2E_EXTERNAL_URL) has its own, and no entry.
 */
const KNOWN: { page: string; layout: string; when: RegExp; why: string }[] = process.env.E2E_EXTERNAL_URL
  ? []
  : ["signin", "flows", "flows-empty", "flows-error", "session-warning", "not-found"].flatMap((page) => LAYOUTS.map((layout) => ({ page, layout, ...BRAND })));

type Anchor = { id: number; name: string; x: number; y: number; height: number; onScreen: boolean };
type Measure = { anchors: Anchor[]; presses: number };
type Still = { measure: () => Measure; quiet: () => Promise<void> };

/** In the page: numbers what it has measured so an element is compared with itself, counts presses, and knows when the document rests. */
function watch() {
  const state = { presses: 0, next: 1, changed: performance.now() };
  for (const type of ["pointerdown", "keydown", "wheel", "touchstart"]) {
    document.addEventListener(type, () => void (state.presses += 1), { capture: true, passive: true });
  }
  const observe = () =>
    new MutationObserver(() => void (state.changed = performance.now())).observe(document.documentElement, {
      subtree: true,
      childList: true,
      characterData: true,
      attributes: true,
      attributeFilter: ["hidden", "open"],
    });
  if (document.documentElement) observe();
  else document.addEventListener("readystatechange", observe, { once: true });

  // What a person sees: every control, every picture, and every element that holds words of its own, whatever its tag
  // (a product name in a bare span moves as surely as a heading).
  const seen =
    'a[href], button, input, select, textarea, summary, [role="button"], [role="link"], [role="tab"], [role="radio"], [role="switch"], [role="checkbox"], [role="menuitem"], img, svg, video, canvas';
  const visible = () => {
    const elements = new Set(document.querySelectorAll<HTMLElement>(seen));
    const words = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let node = words.nextNode(); node; node = words.nextNode()) {
      if (node.nodeValue?.trim() && node.parentElement) elements.add(node.parentElement);
    }
    return elements;
  };
  const still: Still = {
    // The document has not changed for a moment (five frames' worth), or a second and a half has passed: a page that
    // never rests is measured as it is.
    quiet: () =>
      new Promise<void>((done) => {
        const began = performance.now();
        const look = () => {
          const now = performance.now();
          if (now - state.changed >= 80 || now - began >= 1500) done();
          else requestAnimationFrame(look);
        };
        requestAnimationFrame(() => requestAnimationFrame(look));
      }),
    measure: () => {
      // What is in motion is on its way somewhere: its place is measured when it rests.
      const moving = document.getAnimations().flatMap((animation) => {
        const target = (animation.effect as KeyframeEffect | null)?.target;
        return animation.playState === "running" && target ? [target] : [];
      });
      const anchors: Anchor[] = [];
      for (const element of visible()) {
        if (!element.checkVisibility({ visibilityProperty: true })) continue;
        const box = element.getBoundingClientRect();
        // No box, or the one pixel of words kept for a screen reader only.
        if (box.width <= 1 || box.height <= 1) continue;
        if (moving.some((target) => target.contains(element))) continue;
        const numbered = element as HTMLElement & { __still?: number };
        numbered.__still ??= state.next++;
        anchors.push({
          id: numbered.__still,
          name:
            (element.getAttribute("aria-label") ?? element.getAttribute("alt") ?? element.textContent ?? "").trim().replace(/\s+/g, " ").slice(0, 50) ||
            element.tagName.toLowerCase(),
          x: Math.round(box.x),
          y: Math.round(box.y),
          height: Math.round(box.height),
          onScreen: box.bottom > 0 && box.top < window.innerHeight && box.right > 0 && box.left < window.innerWidth,
        });
      }
      return { anchors, presses: state.presses };
    },
  };
  (window as unknown as { __still: Still }).__still = still;
}

/** What is on screen once the document rests; null while the page is between two documents. */
const rested = (page: Page): Promise<Measure | null> =>
  page
    .evaluate(async () => {
      const still = (window as unknown as { __still?: Still }).__still;
      if (!still) return null;
      await still.quiet();
      return still.measure();
    })
    .catch(() => null);

test.afterEach(async ({ page }) => {
  // The next test finds the list as it should be.
  await stubFlows(page, "normal");
});

for (const [name, shown] of Object.entries(BY_ADDRESS)) {
  const state = STATES.find((candidate) => candidate.name === name);
  if (!state) throw new Error(`still.spec.ts: no state named ${name} in screens.ts`);
  test(`${name} stands still when an answer arrives`, async ({ page }, info) => {
    test.skip(!LAYOUTS.includes(info.project.name), "two phones, a tablet and a laptop");
    test.setTimeout(180_000);

    await page.addInitScript(watch);
    await state.go(page);
    const reached = await rested(page);
    expect(reached, "the state's page is measured").not.toBeNull();
    expect(reached!.presses, "this state is reached by a press on its page: it does not belong among the pages opened by their address").toBe(0);
    const address = page.url();

    // The answers, in the order the page asked for them.
    const asked: { path: string; fetched: Promise<void>; hand: () => void }[] = [];
    await page.route(/\/api\//, async (route) => {
      const request = route.request();
      // What the page reads itself. A style sheet and a picture are the browser's own reads.
      if (!["fetch", "xhr"].includes(request.resourceType())) return route.fallback();
      let hand!: () => void;
      const handed = new Promise<void>((resolve) => (hand = resolve));
      const response = route.fetch().catch(() => null);
      asked.push({ path: `${request.method()} ${new URL(request.url()).pathname}`, fetched: response.then(() => undefined), hand });
      const [answer] = await Promise.all([response, handed]);
      await (answer ? route.fulfill({ response: answer }) : route.fallback()).catch(() => undefined);
    });

    // Code on its way to the page: nothing is measured, and no answer handed over, until it has arrived and the
    // document has rested after it.
    let fetching = 0;
    page.on("request", (request) => void (request.resourceType() === "script" && (fetching += 1)));
    page.on("requestfinished", (request) => void (request.resourceType() === "script" && (fetching -= 1)));
    page.on("requestfailed", (request) => void (request.resourceType() === "script" && (fetching -= 1)));
    const look = async () => {
      for (;;) {
        while (fetching > 0) await page.waitForTimeout(20);
        const measure = await rested(page);
        if (fetching === 0) return measure;
      }
    };

    const moves: string[] = [];
    const why: string[] = [];
    const answers: string[] = [];
    let pressed = false;
    let before: Measure | null = null;
    const compare = (after: Measure | null, cause: string) => {
      const was = before;
      before = after;
      if (after && after.presses > 0) pressed = true;
      if (!was || !after) return;
      const moved = after.anchors.flatMap((now) => {
        const then = was.anchors.find((anchor) => anchor.id === now.id);
        if (!then?.onScreen || (Math.abs(now.y - then.y) < MOVED_PX && Math.abs(now.x - then.x) < MOVED_PX)) return [];
        return [`"${now.name}" moved ${now.y - then.y} px down and ${now.x - then.x} px right ${cause}`];
      });
      if (moved.length === 0) return;
      // What took or gave the room: what appeared, went or changed its height in the same step.
      const room = [
        ...after.anchors.flatMap((now) => {
          const then = was.anchors.find((anchor) => anchor.id === now.id);
          if (!then) return now.onScreen ? [`"${now.name}" appeared, ${now.height} px high`] : [];
          return Math.abs(now.height - then.height) >= MOVED_PX ? [`"${now.name}" went from ${then.height} to ${now.height} px high`] : [];
        }),
        ...was.anchors.flatMap((then) => (then.onScreen && !after.anchors.some((now) => now.id === then.id) ? [`"${then.name}" went away, ${then.height} px high`] : [])),
      ];
      moves.push(...moved);
      if (room.length > 0) why.push(`${cause}: ${room.slice(0, 4).join("; ")}`);
    };

    let arrived = false;
    const arriving = (async () => {
      await page.goto(address);
      await expect(shown(page), `${name} is shown when its address is opened, with nothing else done`).toBeVisible({ timeout: 30_000 });
    })().finally(() => (arrived = true));
    // A failure to arrive is the test's failure, once the loop below has handed its answers over.
    arriving.catch(() => undefined);
    for (;;) {
      const answer = asked.shift();
      if (answer) {
        await answer.fetched;
        compare(await look(), "by itself, between two answers");
        answer.hand();
        answers.push(answer.path);
        compare(await look(), `when ${answer.path} answered`);
      } else if (!arrived) await page.waitForTimeout(20);
      else {
        // Drawn, and nothing asked for: the page has arrived when it rests without asking again.
        compare(await look(), "by itself, after the last answer");
        if (asked.length === 0) break;
      }
    }
    await arriving;
    await page.unrouteAll({ behavior: "ignoreErrors" });
    for (const answer of asked) answer.hand();
    info.annotations.push({ type: "answers", description: answers.join(", ") || "none" });

    // `before` is now the page as it stands at the end.
    expect((before as Measure | null)?.anchors.length ?? 0, "the opened page is measured: something of it is on screen").toBeGreaterThan(0);
    expect(pressed, "something was pressed while the page opened: the press and the answers race").toBe(false);
    const declared = KNOWN.filter((known) => known.page === name && known.layout === info.project.name);
    for (const known of declared) {
      info.annotations.push({ type: "known", description: known.why });
      expect(moves.some((move) => known.when.test(move)), `listed as still moving (${known.why}), and it stood still: take it off the list`).toBe(true);
    }
    const unknown = [...new Set(moves)].filter((move) => !declared.some((known) => known.when.test(move)));
    expect(unknown.slice(0, 6), `what moved on screen when no one pressed anything\n  what took or gave the room: ${why.join("\n  ") || "nothing that is measured"}`).toEqual([]);
  });
}
