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
| The brand and the account button keep apart at 320 px with text spacing | `header-fit.spec.ts` | `phone-320-light` |
| Supporting text stays readable, a focused field has one frame, the warning's title takes focus without a ring | `theme.spec.ts` | The gate's eight |
| The checks themselves, against pages built to fail them | `harness.spec.ts` | `laptop-1440-light` |
| No console error and no Content Security Policy violation, in every test | The `clean` fixture of `fixtures.ts` | Every spec that imports `test` from it |

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
| What is measured | Controls (links, buttons, fields, the interactive roles) and `h1` to `h6`, `p`, `li`, `dt`, `dd`, `th`, `td`, `label`, `img`, `video`, `canvas`. A move is 4 px or more |
| What is not | Text in a bare `span` or `div`. The product name in the top bar moves right when the organisation's mark arrives, and the check does not see it |
| Why the machine's speed does not decide | Each answer is fetched whole before it is handed over, in the page's own order, and a measurement waits until the document has stopped changing and no script is on its way. Nothing is pressed |
| A new page | Its states go in `web/tests/e2e/screens.ts`; a state that is the page as it opens also goes in `BY_ADDRESS` of the spec, with what shows that the page is drawn |
| A state reached by a press | Not in `BY_ADDRESS`: the spec fails it with `this state is reached by a press on its page`, because a press and the answers race. Give it a test of its own that holds one answer with `page.route` |
| A move that is left for now | One line in `KNOWN` of the spec: the page, the layout, the answer and the reason. It must still happen: when the page stands still, the line fails the test until it is taken out |

`KNOWN` has one move, on every page, in `laptop-1440-light`: the organisation's mark is 40 px high (`packages/ui/src/base.css`) and arrives when `GET /api/branding` answers, in a top bar that is 48 px with a mouse and grows to 56 px, so the page under it moves 8 px down. On a touch screen the bar is 60 px from the first draw and stands still.

## Where these tools come from

`still.spec.ts`, `GATE_CPU`, `untilModal`, `ci-failure.mjs` and the kept results are adapted from `eneo-ai/eneo-mod-speech-to-text` at commit `194ae4c`: known debt, like the rest of the gate, to become a package export when a second module needs it.

| In the template | In speech-to-text |
|---|---|
| `web/tests/e2e/still.spec.ts` | `frontend/tests/e2e/still.spec.ts` |
| The `cpu` fixture of `web/tests/e2e/fixtures.ts` | `frontend/tests/e2e/gate.ts` |
| `untilModal` in `web/tests/e2e/fixtures.ts` | `cycle` in `frontend/tests/e2e/leaks.spec.ts` |
| `web/scripts/ci-failure.mjs` | `frontend/scripts/ci-failure.mjs` |
| The JSON report and the upload of a failed job's results | The `frontend-browser` job of `.github/workflows/ci.yml` |
