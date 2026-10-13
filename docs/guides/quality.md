# Check a module's pages, and find out why a check fails

Purpose: say what the template's browser tests and accessibility gate check, where each check lives, and how to find the cause when one fails on your machine or in CI.
Read this when: a browser test or a CI job is red, a test passes on your machine and fails in CI, or you add a page, a dialog or a key press to a module.
Related: [new module](new-module.md#5-test-it) (installing and running the tests), [what CI proves](new-module.md#what-ci-proves) (each measurement and its threshold), `template/AGENTS.md`.

Paths are in `template/`, which is the repository root of a module made from it. Commands run from `web/`. Status: built; everything on this page ships in the template.

## What is checked, and where

`npm run test:e2e` builds the app and runs every spec in `web/tests/e2e/` against it, served by the module's backend over the stub Eneo. The projects are in `web/tests/e2e/playwright.config.ts`: three browsers for the module as a person uses it, and the gate's eight in Chromium (`phone-320-light`, `phone-390-light`, `phone-390-dark`, `laptop-1440-light`, `laptop-1440-dark`, `zoom-200`, `forced-colors`, `reduced-motion`).

| Check | Lives in | Runs in |
|---|---|---|
| Sign-in, the page, the proxied route, sign-out, the strict Content Security Policy, colour mode, the organisation's logo | `flow.spec.ts` | `chromium`, `webkit`, `firefox` |
| The login ending while a page is open: the cover, the sign-in dialog, the warning before the end | `session-cover.spec.ts` | `chromium`, `webkit`, `firefox` |
| Every state of `screens.ts`: axe, named controls, placeholder contrast, target sizes, reflow, text spacing, motion | `a11y.spec.ts`, with the measurements in `checks.ts` | The gate's eight |
| The keyboard: focus is visible and not hidden, leaves the page at the end, follows the reading order; a menu and a dialog hold focus and give it back | `keyboard.spec.ts` | The gate's eight |
| Nothing on screen moves when an answer arrives ([below](#what-is-on-screen-stands-still)) | `still.spec.ts` | `phone-320-light`, `phone-390-light`, `laptop-1440-light` |
| Every control of every state does something, and breaks nothing ([below](#every-control-does-something)) | `controls.spec.ts`, with the press in `controls.ts` | `phone-390-light`, `laptop-1440-light` |
| The brand and the account button keep apart at 320 px with text spacing | `header-fit.spec.ts` | `phone-320-light` |
| Supporting text stays readable, a focused field has one frame, the warning's title takes focus without a ring | `theme.spec.ts` | The gate's eight |
| The checks themselves, against pages built to fail them | `harness.spec.ts` | `laptop-1440-light` |
| No policy violation, no redirect, and no console error, uncaught error or failed request that the test did not declare ([below](#what-every-test-watches-for)) | The `sentinel` fixture of `fixtures.ts` | Every spec that imports `test` from it |
| The sentinel itself, made to see each thing it fails a test for | `sentinel.spec.ts` | `chromium` |

## A red CI job

The job that runs the browser tests keeps its evidence when it fails: `web/test-results`, with Playwright's report (`results.json`) and the trace of each failed test, as an artifact named after the job: `web-results`, and `template-web-results` in the kit's own CI. Read it on your machine:

```bash
npm run ci:failure                   # the latest CI run of the branch that is checked out
npm run ci:failure -- 26             # the latest CI run of pull request 26
npm run ci:failure -- 38303520954    # that run
```

It needs the GitHub CLI (`gh`), signed in. It prints the run's failed jobs. For the browser job it downloads the results to a new folder under the system's temporary folder, never into the checkout, and lists every test whose outcome was not the expected one, with its errors and the paths of what Playwright kept for it. Open a trace with `npx playwright show-trace <trace.zip>`.

| Outcome of a test | Listed |
|---|---|
| It failed | Yes, as `failed` or `timedOut` |
| It is marked to fail (`test.fail()`) and passed | Yes, as `passed, and was marked to fail` |
| It failed and passed when tried again | Yes, as `flaky`. Only with `retries` in the Playwright config; the template sets none |
| It is marked to fail and failed, or it passed | No |

For any other failed job it prints the command that shows the job's log (`gh run view <run> --job <job> --log-failed`). When the results cannot be downloaded (they have expired, the sign-in has lapsed) it prints the download's own error and the same command.

| Part | Where |
|---|---|
| The report | `reporter` in `web/tests/e2e/playwright.config.ts` writes `web/test-results/results.json` on every run |
| The upload | The last step of the `web` job in `.github/workflows/ci.yml` (`template-web` in the kit's own), when the job has failed |
| The script | `web/scripts/ci-failure.mjs`. It finds the artifact from the job's name: the name up to a parenthesis, a dash for each space, then `-results` |

## A test that fails only in CI

A CI runner is slower than a developer's machine, so a test that presses or measures before the page is ready loses that race there first. `GATE_CPU` makes the main thread of each test's page that many times slower, with Chromium's own throttle, so the race is lost on your machine too, without loading it:

```bash
GATE_CPU=8 npm run test:e2e -- keyboard.spec.ts --project=laptop-1440-light
```

| Fact | Detail |
|---|---|
| The value | A number of 1 or more. Anything else stops the run with an error |
| The browser | Chromium only. A test in the `webkit` or `firefox` project fails with `GATE_CPU slows Chromium only`; it never runs unslowed |
| What is slowed | The test's own page, before the test touches it. A window the page opens (the login's) is not |
| In the report | Each slowed test carries the annotation `cpu: 8 times slower` |
| Where it lives | The `cpu` fixture of `web/tests/e2e/fixtures.ts`. A spec gets it by importing `test` from there; `harness.spec.ts` uses Playwright's own `test` and is not slowed |

Run a new spec once with `GATE_CPU=8` before you push it.

## A key press waits for a real state

A test waits for the state its key needs, never for a time. A dialog has its open style from the render and is made modal by an effect after it (`showModal()`), and only a modal dialog hears Escape: a key pressed between the two is lost.

| Before | Wait until | With |
|---|---|---|
| Escape, or another key meant for a dialog | Every dialog on screen is modal | `await untilModal(page)`, from `web/tests/e2e/fixtures.ts` |
| A key that moves inside a menu or a dialog | Focus has moved into it | `focusMovesInto(popup)` in `web/tests/e2e/keyboard.spec.ts` |
| Escape after focus left a control with a tooltip | The tooltip is gone (it takes the first Escape) | `await expect(page.getByRole("tooltip")).toHaveCount(0)` |

A test that asserts that a key did nothing also proves that the key arrived: a key that was lost on the way leaves the page unchanged too, and passes for the wrong reason. `web/tests/e2e/session-cover.spec.ts` ("nothing but the new login closes the sign-in dialog") lets the dialog mark itself when Escape reaches it while it is modal, and asserts the mark.

## What every test watches for

A test that imports `test` from `web/tests/e2e/fixtures.ts` has the sentinel on its browser context: its pages and the windows they open. It judges when the test ends, and filters nothing silently:

| What happens | The test |
|---|---|
| A Content Security Policy violation | Fails, always: the policy is never relaxed to make a test pass |
| A redirect (301, 302, 303, 307 or 308) on a fetch, a frame, an image or a page | Fails, but the sign-in's own: the backend's `/api/auth/login` and `/api/auth/callback`, and the stub Eneo's `/module-login` |
| A console error, an uncaught error or a failed request | Fails unless the test or its state declared it |
| A declared failure that does not happen | Fails: a state that is meant to cause an error proves that it does |
| A request that the browser or the page cancelled (`net::ERR_ABORTED`, and the other engines' words for it) | Passes: it is no failed request |

A state declares what it causes in its `go` (`web/tests/e2e/screens.ts`), before it causes it; a test does the same at its start. A console error is its text and, in brackets, the address it came from; a failed request is `METHOD address: reason`:

```ts
declare(page, [{ console: /status of 500.*\/api\/eneo\/flows\// }]);
declare(page, [{ console: /net::ERR_FAILED.*\/api\/auth\/logout/ }, { requestFailed: /POST .*\/api\/auth\/logout: net::ERR_FAILED/ }]);
```

The engines say a failure in their own words. The sentinel writes each in Chromium's, so a failure is declared once for all three, and a declared one that does not happen is missed in every engine:

| Engine | Writes to the console for a resource that did not load | Calls an aborted request | The sentinel |
|---|---|---|---|
| Chromium | "Failed to load resource: the server responded with a status of 500 (Internal Server Error)", and "Failed to load resource: net::ERR_FAILED" | `net::ERR_FAILED` | Records what it says |
| WebKit | The status line only | `Blocked by Web Inspector` | Writes the failure line, and records the abort as `net::ERR_FAILED` |
| Firefox | Neither | `NS_ERROR_FAILURE` | Writes both lines, and records the abort as `net::ERR_FAILED` |

`web/tests/e2e/sentinel.spec.ts` causes each thing the sentinel fails a test for and looks at what it saw, in Chromium; the engines' words are proved by the specs that declare a failure in WebKit and Firefox (`flow.spec.ts`).

## Every control does something

`web/tests/e2e/controls.spec.ts` presses every control of every state of `screens.ts`, each in a fresh copy of the state: a browser context of its own, so that what one press stores or sends is not there for the next. A control is a visible, enabled button, link, menu item, tab, switch, checkbox or radio, in the modal dialog or the open menu on top when there is one. The press is the project's person's: a finger's tap on a touch screen (`hasTouch`), a mouse's click elsewhere. A failure names the control as `<role> "<name>" (<n> of <all>)` and says what is wrong:

| The press fails when | Said as |
|---|---|
| The pointer cannot reach the control: it is under something, off the screen, or never still | `a finger cannot press it (…)`, `a mouse cannot press it (…)` |
| Nothing a person could see happened: not the address, the focus, an overlay, an `aria-` state, a live region, the page's own content, a new tab, a download or a native dialog | `nothing happened that a person could see` |
| What it opened closes neither on Escape nor on its own close control (`Stäng`, `Avbryt`, `Nej`, `Ångra`, `Behåll`) | `opened …, and neither Escape nor a close control closed it` |
| The sentinel would fail a test for it ([above](#what-every-test-watches-for)) | `console errors: …`, `failed requests: …`, `redirects: …`, `declared failures that did not occur: …`, `Content Security Policy: …` |

What is the person's choice or page already (a chosen radio, the link to the page that is open) is not pressed: it does nothing by design. An external link is checked for its address only. Anything else that is not pressed as the others are is declared in `controls.spec.ts`, keyed `<state> | <role> "<name>"`, with its reason; never a pattern:

| List | For | The control |
|---|---|---|
| `SKIPPED` | A press the shared stub Eneo could not take back | Is not pressed |
| `EXPECTS` | A failure the press causes on purpose, declared as a state declares its own | Is pressed, and the failure must happen |
| `NO_RESPONSE` | A press that changes nothing by design | Is pressed, and judged on everything else |
| `KEYBOARD_ONLY` | A control no pointer reaches by design: one kept out of sight until it has focus | Is given focus and Enter |
| `CLICKED_IN_WEBKIT` | A control that Safari takes a tap on and Playwright's WebKit cannot tap, with the evidence from Safari | Is clicked on a WebKit project with touch |

All five are empty in the template. The press and its judgement are in `web/tests/e2e/controls.ts`, which `harness.spec.ts` also runs on pages built to fail it. A new state is pressed as soon as it is in `screens.ts`.

## What is on screen stands still

Nothing on screen moves when an answer arrives: a control that moves is pressed by mistake, and a line that moves is lost by the eye reading it. `web/tests/e2e/still.spec.ts` opens each page by its address, hands it the backend's answers one at a time, in the order the page asked for them, and measures what is on screen before and after each. It runs in `phone-320-light`, `phone-390-light` and `laptop-1440-light`; the template has no tablet project.

A page satisfies the rule in one of three ways:

| Way | Example |
|---|---|
| An action has its place from the first draw, and is disabled until it can be pressed | A button whose data is still being read is drawn disabled, not added when the data comes |
| The page waits for an answer before it draws what stands under it | A notice above a list is read before the list is drawn |
| What arrives late and long stands last | Details read after a card stand below it, not above |

A failure names what moved and how far, after which request, and what took or gave the room in the same step. Shortened, for a line that is added above the heading when the greeting is read:

```text
Error: what moved on screen when no one pressed anything
  what took or gave the room: when GET /api/example answered: "Ett meddelande som kommer sent" appeared, 24 px high
  "Välj ett flöde" moved 48 px down and 0 px right when GET /api/example answered
```

| Fact | Detail |
|---|---|
| What is measured | Every control (links, buttons, fields, the interactive roles), every picture (`img`, `svg`, `video`, `canvas`) and every element that holds words of its own, whatever its tag. A move is 4 px or more |
| What is not | Words kept for a screen reader only (a box of one pixel) |
| Why the machine's speed does not decide | Each answer is fetched whole before it is handed over, in the page's own order, and a measurement waits until the document has stopped changing and no script is on its way. Nothing is pressed |
| A new page | Its states go in `web/tests/e2e/screens.ts`; a state that is the page as it opens also goes in `BY_ADDRESS` of the spec, with what shows that the page is drawn |
| A state reached by a press | Not in `BY_ADDRESS`: the spec fails it with `this state is reached by a press on its page`, because a press and the answers race. Give it a test of its own that holds one answer with `page.route` |
| A move that is left for now | One line in `KNOWN` of the spec: the page, the layout, the answer and the reason. It must still happen: when the page stands still, the line fails the test until it is taken out |

`KNOWN` has one move, on every page and layout: the organisation is read after the page is drawn ([K10](../decisions/k10-branding-without-templating.md)), and its mark then takes its place before the product's name, which moves along the top bar. The bar itself has the mark's height from the first frame (`packages/ui/src/base.css`), so nothing under it moves.

## Where these tools come from

These tools are adapted from `eneo-ai/eneo-mod-speech-to-text`, at the commit each row names: known debt, like the rest of the gate, to become a package export when a second module needs it.

| In the template | In speech-to-text | At commit |
|---|---|---|
| `web/tests/e2e/still.spec.ts` | `frontend/tests/e2e/still.spec.ts` | `194ae4c` |
| The `cpu` fixture of `web/tests/e2e/fixtures.ts` | `frontend/tests/e2e/gate.ts` | `194ae4c` |
| `untilModal` in `web/tests/e2e/fixtures.ts` | `cycle` in `frontend/tests/e2e/leaks.spec.ts` | `194ae4c` |
| `web/scripts/ci-failure.mjs` | `frontend/scripts/ci-failure.mjs` | `194ae4c` |
| The JSON report and the upload of a failed job's results | The `frontend-browser` job of `.github/workflows/ci.yml` | `194ae4c` |
| The `sentinel` fixture of `web/tests/e2e/fixtures.ts`, `web/tests/e2e/sentinel.spec.ts` | `frontend/tests/e2e/sentinel.ts`, `frontend/tests/e2e/sentinel.spec.ts` | `b8c3804` |
| The measurements of `web/tests/e2e/checks.ts`, and their own tests in `web/tests/e2e/harness.spec.ts` | `frontend/tests/e2e/checks.ts`, `frontend/tests/e2e/harness.spec.ts` | `b8c3804` |
| `web/tests/e2e/controls.ts`, `web/tests/e2e/controls.spec.ts` | `frontend/tests/e2e/controls.ts`, `frontend/tests/e2e/controls.spec.ts` | `b8c3804` |
