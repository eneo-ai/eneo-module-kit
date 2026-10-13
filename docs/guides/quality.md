# Find out why a browser test fails

Purpose: say what the template's browser gate checks and where each check lives, and how to find the cause when one fails on your machine or in CI.
Read this when: a browser test or a CI job is red, a test passes on your machine and fails in CI, or you add a page, a dialog or a key press to a module.
Related: [new module](new-module.md#5-test-it) (installing and running the tests), [what CI proves](new-module.md#what-ci-proves), `template/AGENTS.md`.

Paths are in `template/`, which is the repository root of a module made from it. Commands run from `web/`. Built: every tool on this page is in the template and runs in its CI.

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

A test waits for the state its key needs, never for a time. A dialog has its open style from the render and is made modal by an effect after it (`showModal()`), and only a modal dialog hears Escape: a key pressed in between is lost.

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
