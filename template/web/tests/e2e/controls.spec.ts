/**
 * Every control of every state does something. Each visible, enabled button, link, menu item, tab, switch, checkbox and
 * radio of a state is activated in a fresh copy of that state (a browser context of its own, so what one activation
 * stores or sends is not there for the next), and must
 *
 * - take the press of the project's person: a finger's tap on a touch screen, a mouse's click elsewhere. A control that
 *   pointer cannot reach (it is under something, or off the screen) fails;
 * - cause nothing the sentinel of fixtures.ts fails a test for: no policy violation, no redirect, no console error,
 *   uncaught error or failed request that its state did not declare, and every failure that is declared;
 * - show a response: the address changed, focus moved elsewhere, an overlay (dialog, menu, list) opened or closed, an
 *   aria-pressed/checked/expanded/selected/current changed, a live region said something, a new tab, download or native
 *   dialog came up, or the page's own content changed (a region that changes by itself, a timer, is left out);
 * - leave the page usable: an overlay it opened closes on Escape or on its own close control.
 *
 * What is the current choice already (a chosen radio, the link to the page the person is on) is not pressed: it does
 * nothing by design. An external link is checked for its address only. Anything else that is not pressed as the others
 * are is in one of the lists below, by state and control, with the reason; never a pattern. The press itself and what
 * judges it are in controls.ts, which the checks' own tests run too (harness.spec.ts).
 */
import { sweep, type Declared } from "./controls";
import { expect, test } from "./fixtures";
import { STATES } from "./screens";

// Which projects press every control is the config's to say (playwright.config.ts). A trace of every copy would be large.
test.use({ trace: "off" });

/** Controls that are not activated (a press the shared stub Eneo could not take back), `<state> | <role> "<name>"`, and why. None today. */
const SKIPPED: Declared["skipped"] = {};

/** Failures a control is meant to cause, `<state> | <role> "<name>"`, as a state declares its own (screens.ts). None today. */
const EXPECTS: Declared["expects"] = {};

/** Presses that change nothing by design, `<state> | <role> "<name>"`, and why: they are still activated, and judged on everything else. None today. */
const NO_RESPONSE: Declared["noResponse"] = {};

/**
 * Controls no pointer reaches by design, `<state> | <role> "<name>"`, and why: these alone are given focus and Enter, as a
 * keyboard user does it. Any other control that a tap or a click cannot reach fails. None today.
 */
const KEYBOARD_ONLY: Declared["keyboardOnly"] = {};

/**
 * Controls Safari takes a tap on that Playwright's WebKit cannot tap, `<state> | <role> "<name>"`, and the evidence from
 * Safari itself: on a WebKit touch project these alone are clicked. None today.
 */
const CLICKED_IN_WEBKIT: Declared["clickedInWebKit"] = {};

for (const state of STATES) {
  test(`every control of ${state.name} does something`, async ({ browser }, info) => {
    test.setTimeout(300_000);
    const declared = { skipped: SKIPPED, expects: EXPECTS, noResponse: NO_RESPONSE, keyboardOnly: KEYBOARD_ONLY, clickedInWebKit: CLICKED_IN_WEBKIT };
    const { controls, problems, notes } = await sweep(browser, state, declared, info.project.use);
    if (!controls) test.skip(true, "a state with no control to activate");
    for (const note of notes) info.annotations.push({ type: "controls", description: note });
    info.annotations.push({ type: "controls", description: `${controls} controls` });
    expect(problems, `controls of ${state.name} that do nothing, break something or leave something open`).toEqual([]);
  });
}
