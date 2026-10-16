import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { defineConfig, devices, type PlaywrightTestConfig } from "@playwright/test";

// The built app, served by the module's backend, with the stub Eneo behind it: what runs in the image, minus the
// container. Build first (`npm run build`). Ports are the pair of this checkout: set E2E_APP_PORT and E2E_STUB_PORT
// when others are in use. One worker: the tests share one stub, and some of them change what it answers.
const APP = Number(process.env.E2E_APP_PORT ?? 3011);
const STUB = Number(process.env.E2E_STUB_PORT ?? 8011);

// E2E_EXTERNAL_URL: test a module that is already running (the container of `docker compose up`, with its stub Eneo
// on E2E_STUB_PORT of this machine) instead of starting one.
const external = process.env.E2E_EXTERNAL_URL;

const template = resolve(import.meta.dirname, "../../..");
// PYTHON, if set, is an absolute path (the backend runs from another folder, so a relative one fails). The kit's checkout has a
// virtual environment at its root; a module made from the template has its own python3.
const kitPython = resolve(template, "../.venv/bin/python");
const python = process.env.PYTHON ?? (existsSync(kitPython) ? kitPython : "python3");

type Use = NonNullable<PlaywrightTestConfig["use"]>;
// A touch screen: Chromium then matches (pointer: coarse) and (hover: none).
const touch = (width: number, height: number): Use => ({ viewport: { width, height }, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
const desktop = (width: number, height: number): Use => ({ viewport: { width, height } });
// WebKit and Firefox, each with its own launch options in place of Chromium's (the shared `use` below). Firefox keeps what a
// page plays out of the speakers with a preference; Playwright's WebKit has no such switch.
const webkit: Use = { browserName: "webkit", launchOptions: {} };
const firefox: Use = { browserName: "firefox", launchOptions: { firefoxUserPrefs: { "media.volume_scale": "0.0" } } };

// Which specs a project runs. The specs about the module's logic stay in Chromium, which several of them need (the
// DevTools protocol, GATE_CPU); in a spec, what only Chromium can do is chosen by `browserName === "chromium"`, and what a
// finger does by the project's `hasTouch`.
const specs = (...names: string[]) => new RegExp(`(${names.join("|")})\\.spec\\.ts`);
// The module as a person uses it, in each browser it supports; the sentinel's own tests in Chromium's (the other engines'
// words for a failure are proved by the specs that run there).
const flow = specs("flow", "session-cover");
// Every state at every width and theme, the keyboard on the real screens, and the checks that each name their own project.
const gate = ["a11y", "header-fit", "keyboard", "still", "theme"];
// What another engine can change: the scan, the keyboard walks, the press on every control and the snapshots. The checks'
// own tests (harness.spec.ts) run once in each engine, on its laptop.
const portable = ["a11y", "keyboard", "controls", "aria"];

// The stub Eneo, and the module's backend serving the built UI, with the organisation of the brand test and a release's build.
const servers: NonNullable<PlaywrightTestConfig["webServer"]> = [
  {
    command: `${python} ${resolve(template, "stub-eneo/server.py")} ${STUB}`,
    url: `http://127.0.0.1:${STUB}/health`,
    reuseExistingServer: false,
  },
  {
    command: `${python} -c "from eneo_module_bff import serve; serve('main:build_app', factory=True, host='127.0.0.1', port=${APP})"`,
    cwd: resolve(template, "backend"),
    url: `http://127.0.0.1:${APP}/health`,
    reuseExistingServer: false,
    env: {
      ENEO_BACKEND_URL: `http://127.0.0.1:${STUB}`,
      ENEO_PUBLIC_URL: `http://127.0.0.1:${STUB}`,
      MODULE_PUBLIC_URL: `http://127.0.0.1:${APP}`,
      MODULE_KEY: "eneo-module",
      ENEO_API_KEY: "stub-service-key",
      SESSION_SECRET: "a-secret-of-at-least-32-characters-for-tests",
      COOKIE_SECURE: "false",
      STATIC_DIR: resolve(template, "web/dist"),
      // An organisation with a logo for each colour mode, to show the lockup the deployment configures.
      ORGANIZATION_NAME: "Exempelkommunen",
      ORGANIZATION_LOGO: resolve(import.meta.dirname, "fixtures/logo-light.svg"),
      ORGANIZATION_LOGO_DARK: resolve(import.meta.dirname, "fixtures/logo-dark.svg"),
      // A release's build, so that the version dialog shows what a deployment shows: the release, the commit, when it was
      // built (10:00 on the tests' Stockholm clock) and the pages of both.
      SOURCE_REVISION: "0123456789abcdef0123456789abcdef01234567",
      BUILD_DATE: "2026-10-01T08:00:00Z",
      SOURCE_URL: "https://github.com/eneo-ai/eneo-module",
      MODULE_VERSION: "v1.0.0",
    },
  },
];

export default defineConfig({
  testDir: ".",
  outputDir: "../../test-results",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  // The JSON report is what `npm run ci:failure` reads from a failed CI job; it lies in the output folder, beside the traces.
  reporter: [["list"], ["json", { outputFile: "../../test-results/results.json" }]],
  use: {
    baseURL: external ?? `http://127.0.0.1:${APP}`,
    locale: "sv-SE",
    timezoneId: "Europe/Stockholm",
    trace: "retain-on-failure",
    // Chromium's: what a page plays goes to no speaker, and plays as it does with sound.
    launchOptions: { args: ["--mute-audio"] },
  },
  projects: [
    // The module in the browsers it supports: sign in, the page, the proxied route, sign out, under the sentinel.
    { name: "chromium", testMatch: specs("flow", "session-cover", "sentinel"), use: { ...devices["Desktop Chrome"], colorScheme: "light" } },
    { name: "webkit", testMatch: flow, use: { ...devices["Desktop Safari"], ...webkit, colorScheme: "light" } },
    { name: "firefox", testMatch: flow, use: { ...devices["Desktop Firefox"], ...firefox, colorScheme: "light" } },
    // The accessibility gate: every state at every width and theme, and the keyboard on the real screens. The press on
    // every control (controls.spec.ts, the gate's longest part) and the snapshots (aria.spec.ts) on a phone and a laptop.
    { name: "phone-320-light", testMatch: specs(...gate), use: { ...touch(320, 568), colorScheme: "light" } },
    { name: "phone-390-light", testMatch: specs(...gate, "controls", "aria"), use: { ...touch(390, 844), colorScheme: "light" } },
    { name: "phone-390-dark", testMatch: specs(...gate), use: { ...touch(390, 844), colorScheme: "dark" } },
    { name: "laptop-1440-light", testMatch: specs(...gate, "controls", "aria", "harness"), use: { ...desktop(1440, 900), colorScheme: "light" } },
    { name: "laptop-1440-dark", testMatch: specs(...gate), use: { ...desktop(1440, 900), colorScheme: "dark" } },
    // 200 % zoom of a 1280 x 800 window.
    { name: "zoom-200", testMatch: specs(...gate), use: { viewport: { width: 640, height: 400 }, deviceScaleFactor: 2, colorScheme: "light" } },
    { name: "forced-colors", testMatch: specs(...gate), use: { ...desktop(1440, 900), colorScheme: "light", forcedColors: "active" } },
    { name: "reduced-motion", testMatch: specs(...gate), use: { ...touch(390, 844), colorScheme: "light", reducedMotion: "reduce" } },
    // A tablet is a finger on a laptop's layout (landscape) or on the stacked one at its widest (portrait): the scan, its
    // own keyboard walks and its own presses; upright, also the stand-still test's tablet.
    { name: "tablet-portrait", testMatch: specs("a11y", "keyboard", "controls", "still"), use: { ...touch(768, 1024), isMobile: false, colorScheme: "light" } },
    { name: "tablet-landscape", testMatch: specs("a11y", "keyboard", "controls"), use: { ...touch(1024, 768), isMobile: false, colorScheme: "light" } },
    // A phone on its side: as wide as a tablet, as low as 200 % zoom. Scanned in every state.
    { name: "landscape-844", testMatch: specs("a11y"), use: { ...touch(844, 390), colorScheme: "light" } },
    // The other engines, as engine checks and not as the products built on them (Playwright's WebKit is ahead of Safari):
    // WebKit where an iPhone, an iPad and a Mac have it, Firefox on a laptop. The tablet has no snapshots, as Chromium's.
    { name: "phone-390-webkit", testMatch: specs(...portable), use: { ...touch(390, 844), ...webkit, colorScheme: "light" } },
    { name: "tablet-landscape-webkit", testMatch: specs("a11y", "keyboard", "controls"), use: { ...touch(1024, 768), isMobile: false, ...webkit, colorScheme: "light" } },
    { name: "laptop-1440-webkit", testMatch: specs(...portable, "harness"), use: { ...desktop(1440, 900), ...webkit, colorScheme: "light" } },
    { name: "laptop-1440-firefox", testMatch: specs(...portable, "harness"), use: { ...desktop(1440, 900), ...firefox, colorScheme: "light" } },
  ],
  webServer: external ? undefined : servers,
});
