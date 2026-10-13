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
