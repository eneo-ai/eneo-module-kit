import { expect, test as base, type BrowserContext, type Page } from "@playwright/test";

// GATE_CPU=8 makes the main thread of each test's page that many times slower (Chromium's own throttle), so a race that
// only a slow CI runner loses is lost here too, without loading the machine:
// `GATE_CPU=8 npm run test:e2e -- keyboard.spec.ts --project=laptop-1440-light`. It slows the test's own page before the
// test touches it; a window the page opens (the login's) is not slowed, and other engines have no such throttle.
const CPU = Number(process.env.GATE_CPU ?? 1);
if (!Number.isFinite(CPU) || CPU < 1) throw new Error(`GATE_CPU is a number of 1 or more (how many times slower), not "${process.env.GATE_CPU}".`);

/** A failure a state or a test causes on purpose. The sentinel lets it through, and fails the test when it does not happen. */
export interface Expectation {
  /** The text of a console error or an uncaught error and, in brackets, where it came from: `/status of 500.*\/api\/eneo\/flows\//`. */
  console?: RegExp;
  /** A failed request as `METHOD url: reason`, e.g. an abort: `/POST .*\/api\/auth\/logout: net::ERR_FAILED/`. */
  requestFailed?: RegExp;
}

/** The sentinel of each browser context, so a state can declare what it causes without being handed one. */
const watching = new WeakMap<BrowserContext, Sentinel>();

/** Declares, for the test whose page this is, the failures it is meant to cause (a state calls it in its `go`). */
export function declare(page: Page, expectations: Expectation[]) {
  watching.get(page.context())?.expect(...expectations);
}

/**
 * A request that the browser or the page itself cancelled, in each engine's words as Playwright reports them: Chromium's,
 * Firefox's (a cancel of its own, and one that a script or a route asked for) and WebKit's (a cancel, and a page load
 * that became a download).
 */
const CANCELLED = new Set(["net::ERR_ABORTED", "NS_BINDING_ABORTED", "NS_ERROR_ABORT", "cancelled", "Frame load interrupted"]);

/**
 * A request that the network failed, which is what a test's `route.abort()` makes of one, in Firefox's and WebKit's words.
 * It is recorded in Chromium's, so that a failure is declared once (`requestFailed: /… net::ERR_FAILED/`). WebKit has this
 * one text for every request a route aborts, whatever reason the route gave.
 */
const FAILED = new Map([["NS_ERROR_FAILURE", "net::ERR_FAILED"], ["Blocked by Web Inspector", "net::ERR_FAILED"]]);

/**
 * Chromium writes a resource that did not load to the console, whatever stopped it: "Failed to load resource: the server
 * responded with a status of 500 (Internal Server Error)", or "Failed to load resource: net::ERR_FAILED". WebKit writes the
 * first of the two and Firefox neither. The sentinel writes the line for them, from the request itself and in Chromium's
 * words, so that a console error is declared once, and a declared one that does not happen is missed in every engine.
 */
const WRITES_NO_STATUS = new Set(["firefox"]);
const WRITES_NO_FAILURE = new Set(["firefox", "webkit"]);

/**
 * Playwright's, not the page's: in WebKit each screenshot adds a <style> to the page and takes it away again, to bring the
 * page's animations into step. The policy refuses it, with a violation that names no source file, and WebKit writes a line
 * about it to the console. Code of the page always has a file (the policy allows no inline script and no eval).
 */
const SCREENSHOT_STYLE = /^style-src-elem blocked inline \(the page:\d+\)/;
const REFUSED_STYLE = /^Refused to apply a stylesheet because its hash, its nonce, or 'unsafe-inline' does not appear in the style-src directive/;

/** The redirects of the sign-in handshake: the backend's login and callback, and the stub Eneo's login. */
const HANDSHAKE = new Set(["/api/auth/login", "/api/auth/callback", "/module-login"]);
const REDIRECTS = new Set([301, 302, 303, 307, 308]);

/** The page's listener for `securitypolicyviolation`, which reports at once, so a navigation does not lose what it saw. */
const LISTEN = () => {
  document.addEventListener(
    "securitypolicyviolation",
    (event) =>
      void (window as unknown as { __sentinelViolation(report: string): void }).__sentinelViolation(
        `${event.violatedDirective} blocked ${event.blockedURI || "inline"} (${event.sourceFile || "the page"}:${event.lineNumber}) ${event.disposition}`,
      ),
    true,
  );
};

/**
 * What every test watches for in its browser context, under the backend's strict policy (no 'unsafe-inline'). Nothing is
 * filtered silently:
 *
 * - A Content Security Policy violation fails the test, always: the policy is never relaxed to make a test pass.
 * - A redirect fails it (a 301, 302, 303, 307 or 308 on a fetch, a frame, an image or a page), but the sign-in handshake's.
 * - A console error, an uncaught error or a failed request fails it unless the test or its state declared it, and a
 *   declared one that did not happen fails it as well: a state that is meant to cause an error proves that it does. A
 *   request that the browser or the page cancelled (`CANCELLED`) is no failed request.
 *
 * Adapted from speech-to-text's sentinel (`eneo-ai/eneo-mod-speech-to-text` at commit `b8c3804`).
 */
export class Sentinel {
  readonly violations: string[] = [];
  readonly redirects: string[] = [];
  private readonly console: string[] = [];
  private readonly failed: string[] = [];
  private readonly declared: { expectation: Expectation; seen: boolean }[] = [];
  /** How many of Playwright's screenshot styles WebKit refused (`SCREENSHOT_STYLE`). */
  private screenshotStyles = 0;

  /** The failures this test is meant to cause. */
  expect(...expectations: Expectation[]) {
    for (const expectation of expectations) this.declared.push({ expectation, seen: false });
  }

  async watch(context: BrowserContext) {
    const engine = context.browser()?.browserType().name() ?? "chromium";
    watching.set(context, this);
    await context.exposeBinding("__sentinelViolation", (_source, report: string) => {
      if (engine === "webkit" && SCREENSHOT_STYLE.test(report)) this.screenshotStyles += 1;
      else this.violations.push(report);
    });
    await context.addInitScript(LISTEN);
    context.on("console", (message) => {
      // The URL is where the browser says the message came from: for a failed resource, the resource.
      if (message.type() === "error") this.console.push(`${message.text()} [${message.location().url}]`);
    });
    context.on("weberror", (error) => void this.console.push(`uncaught: ${error.error().message}`));
    context.on("requestfailed", (request) => {
      const reason = request.failure()?.errorText ?? "failed";
      if (CANCELLED.has(reason)) return;
      this.failed.push(`${request.method()} ${request.url()}: ${FAILED.get(reason) ?? reason}`);
      if (FAILED.has(reason) && WRITES_NO_FAILURE.has(engine)) this.console.push(`Failed to load resource: ${FAILED.get(reason)} [${request.url()}]`);
    });
    context.on("response", (response) => {
      if (response.status() >= 400 && WRITES_NO_STATUS.has(engine)) {
        this.console.push(`Failed to load resource: the server responded with a status of ${response.status()} (${response.statusText()}) [${response.url()}]`);
      }
      if (!REDIRECTS.has(response.status()) || HANDSHAKE.has(new URL(response.url()).pathname)) return;
      this.redirects.push(`${response.status()} ${response.request().method()} ${response.url()} to ${response.headers()["location"] ?? "nowhere"}`);
    });
  }

  /** What was not declared, marking every declaration a text matches as seen. */
  private unexpected(found: string[], pick: (expectation: Expectation) => RegExp | undefined) {
    return found.filter((text) => {
      const matches = this.declared.filter(({ expectation }) => pick(expectation)?.test(text));
      for (const match of matches) match.seen = true;
      return matches.length === 0;
    });
  }

  /** What was not declared; and what was declared and did not happen. */
  verify() {
    // WebKit's console line for each of Playwright's screenshot styles goes with it.
    const logged = [...this.console];
    for (let left = this.screenshotStyles; left > 0; left--) {
      const at = logged.findIndex((text) => REFUSED_STYLE.test(text));
      if (at >= 0) logged.splice(at, 1);
    }
    const unexpectedConsole = this.unexpected(logged, (expectation) => expectation.console);
    const unexpectedFailed = this.unexpected(this.failed, (expectation) => expectation.requestFailed);
    const missing = this.declared
      .filter(({ seen }) => !seen)
      .map(({ expectation }) => String(expectation.console ?? expectation.requestFailed));
    return { unexpectedConsole, unexpectedFailed, missing };
  }

  /** Forgets what was seen and declared: for the sentinel's own tests, which cause what it watches for. */
  reset() {
    for (const list of [this.violations, this.redirects, this.console, this.failed, this.declared]) list.length = 0;
    this.screenshotStyles = 0;
  }

  /** The assertions at the end of a test. `expect.soft`: every kind is reported, not only the first. */
  assertClean() {
    const { unexpectedConsole, unexpectedFailed, missing } = this.verify();
    expect.soft(this.violations, "Content Security Policy violations: the policy is never relaxed, so the source is fixed").toEqual([]);
    expect.soft(this.redirects, "redirects: the browser's exact paths must not meet one").toEqual([]);
    expect.soft(unexpectedConsole, "console errors that the test did not declare").toEqual([]);
    expect.soft(unexpectedFailed, "failed requests that the test did not declare").toEqual([]);
    expect.soft(missing, "declared failures that did not occur").toEqual([]);
  }
}

/** `test` with the sentinel on every page of its browser context, judged when the test ends, and GATE_CPU. */
export const test = base.extend<{ sentinel: Sentinel; cpu: void }>({
  cpu: [
    async ({ page, browserName }, use, info) => {
      if (browserName !== "chromium") throw new Error("GATE_CPU slows Chromium only: run it with a Chromium project.");
      await (await page.context().newCDPSession(page)).send("Emulation.setCPUThrottlingRate", { rate: CPU });
      info.annotations.push({ type: "cpu", description: `${CPU} times slower` });
      await use();
    },
    { auto: CPU > 1 },
  ],
  sentinel: [
    // `page` first: the sentinel is torn down, and judges, before the page is closed, whose teardown aborts what is in flight.
    async ({ context, page }, use) => {
      void page;
      const sentinel = new Sentinel();
      await sentinel.watch(context);
      await use(sentinel);
      sentinel.assertClean();
    },
    { auto: true },
  ],
});

export { expect };

const STUB = Number(process.env.E2E_STUB_PORT ?? 8011);

/** What the stub Eneo answers for the flow list: two flows, none, or a failure. */
export async function stubFlows(page: Page, mode: "normal" | "empty" | "error") {
  const response = await page.request.post(`http://127.0.0.1:${STUB}/__stub/flows?mode=${mode}`);
  expect(response.ok()).toBe(true);
}

/** Signs in through the stub Eneo: the module's login, Eneo's, the callback, and back to the flows. */
export async function signIn(page: Page) {
  await page.goto("/");
  await page.getByRole("link", { name: "Logga in med Eneo" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Välj ett flöde" })).toBeVisible();
}

/**
 * Every dialog on screen is modal: wait for it before a key meant for a dialog. A dialog has its open style from the
 * render and is made modal by an effect after it (`showModal()`), and only a modal one hears Escape: a key pressed in
 * between is lost, on a slow machine first.
 */
export const untilModal = (page: Page) =>
  expect
    .poll(() => page.evaluate(() => [...document.querySelectorAll("dialog")].every((dialog) => !dialog.checkVisibility() || dialog.matches(":modal"))), {
      message: "every dialog on screen is modal",
    })
    .toBe(true);

/** A control route of the stub Eneo (template/stub-eneo/server.py). */
export async function stubControl(page: Page, route: string) {
  const response = await page.request.post(`http://127.0.0.1:${STUB}/__stub/${route}`);
  expect(response.ok(), `stub ${route}`).toBe(true);
}

/** The logins made from now on are the stub's defaults again: a long session, Erik Lund. */
export async function stubDefaults(page: Page) {
  await stubControl(page, "session?ends_in=reset&token_seconds=reset");
  await stubControl(page, "login-as?user=erik");
}
