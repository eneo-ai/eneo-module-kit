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
// The kit's checkout has a virtual environment at its root; a module made from the template has its own python3.
const kitPython = resolve(template, "../.venv/bin/python");
const python = process.env.PYTHON ?? (existsSync(kitPython) ? kitPython : "python3");

type Use = NonNullable<PlaywrightTestConfig["use"]>;
// A touch screen: Chromium then matches (pointer: coarse) and (hover: none).
const touch = (width: number, height: number): Use => ({ viewport: { width, height }, deviceScaleFactor: 2, hasTouch: true, isMobile: true });
const desktop = (width: number, height: number): Use => ({ viewport: { width, height } });

const flow = /flow\.spec\.ts/;
const gate = /(a11y|harness|header-fit)\.spec\.ts/;

// The stub Eneo, and the module's backend serving the built UI, with the organisation of the brand test.
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
  reporter: [["list"]],
  use: { baseURL: external ?? `http://127.0.0.1:${APP}`, locale: "sv-SE", timezoneId: "Europe/Stockholm", trace: "retain-on-failure" },
  projects: [
    // The module in the browsers it supports: sign in, the page, the proxied route, sign out, a clean console.
    { name: "chromium", testMatch: flow, use: { ...devices["Desktop Chrome"], colorScheme: "light" } },
    { name: "webkit", testMatch: flow, use: { ...devices["Desktop Safari"], colorScheme: "light" } },
    { name: "firefox", testMatch: flow, use: { ...devices["Desktop Firefox"], colorScheme: "light" } },
    // The accessibility gate: every state at every width and theme.
    { name: "phone-320-light", testMatch: gate, use: { ...touch(320, 568), colorScheme: "light" } },
    { name: "phone-390-light", testMatch: gate, use: { ...touch(390, 844), colorScheme: "light" } },
    { name: "phone-390-dark", testMatch: gate, use: { ...touch(390, 844), colorScheme: "dark" } },
    { name: "laptop-1440-light", testMatch: gate, use: { ...desktop(1440, 900), colorScheme: "light" } },
    { name: "laptop-1440-dark", testMatch: gate, use: { ...desktop(1440, 900), colorScheme: "dark" } },
    // 200 % zoom of a 1280 x 800 window.
    { name: "zoom-200", testMatch: gate, use: { viewport: { width: 640, height: 400 }, deviceScaleFactor: 2, colorScheme: "light" } },
    { name: "forced-colors", testMatch: gate, use: { ...desktop(1440, 900), colorScheme: "light", forcedColors: "active" } },
    { name: "reduced-motion", testMatch: gate, use: { ...touch(390, 844), colorScheme: "light", reducedMotion: "reduce" } },
  ],
  webServer: external ? undefined : servers,
});
