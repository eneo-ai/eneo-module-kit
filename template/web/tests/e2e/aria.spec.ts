/**
 * What a screen reader is given: an ARIA snapshot of each state's region (names, roles, levels, states and the text that
 * is read), reviewed and kept in aria.spec.ts-snapshots, one file a width. The snapshots are of the page's markup as
 * Playwright reads it, the same in every engine unless the page itself differs there; where it does, the engine has a
 * file of its own for that state, `<state>-<width>-<engine>.aria.yml`, a copy that differs in that one thing.
 *
 * The files are curated by hand: a pattern where a value varies, no generated id, no empty text, only the nodes that say
 * something. Playwright's own update would write its raw tree over that, so this spec never lets it write. Run with
 * `--update-snapshots`, or for a state that has no file yet, a test puts the page's raw tree in its results folder and
 * fails with the two paths: carry what changed over to the curated file by hand, or copy and curate a new one.
 *
 * Adapted from speech-to-text's gate (`eneo-ai/eneo-mod-speech-to-text` at commit `b8c3804`).
 */
import { existsSync, writeFileSync } from "node:fs";
import type { Locator, Page } from "@playwright/test";
import { expect, stubFlows, test } from "./fixtures";
import { STATES } from "./screens";

/** Each state, and the region of it that is kept: the whole shell for a page, the dialog or menu open over one. */
const SNAPSHOTS: { state: string; region: (page: Page) => Locator }[] = [
  { state: "signin", region: (page) => page.locator(".astryx-app-shell") },
  { state: "flows", region: (page) => page.locator(".astryx-app-shell") },
  { state: "account-menu", region: (page) => page.getByRole("menu") },
  { state: "flows-empty", region: (page) => page.getByRole("main") },
  { state: "flows-error", region: (page) => page.getByRole("main") },
  { state: "session-warning", region: (page) => page.getByRole("alertdialog") },
  { state: "signed-out", region: (page) => page.getByRole("alertdialog") },
];

test.afterEach(async ({ page }) => {
  // The next test finds the list as it should be.
  await stubFlows(page, "normal");
});

for (const { state, region } of SNAPSHOTS) {
  test(`aria ${state}`, async ({ page, browserName }, info) => {
    await STATES.find((s) => s.name === state)!.go(page);
    const width = info.project.use.viewport!.width;
    const own = `${state}-${width}-${browserName}.aria.yml`;
    const name = existsSync(info.snapshotPath(own, { kind: "aria" })) ? own : `${state}-${width}.aria.yml`;
    const curated = info.snapshotPath(name, { kind: "aria" });
    const updating = info.config.updateSnapshots === "all" || info.config.updateSnapshots === "changed";
    if (updating || !existsSync(curated)) {
      const raw = info.outputPath(name);
      writeFileSync(raw, await region(page).ariaSnapshot());
      throw new Error(
        updating
          ? `${name} is curated by hand, so --update-snapshots does not write it. The page's raw tree is in ${raw}: carry what changed over to ${curated}, then run without the flag.`
          : `There is no snapshot of ${state} at ${width} px. The page's raw tree is in ${raw}: copy it to ${curated}, curate it (a pattern where a value varies, no generated id, no empty text), and run again.`,
      );
    }
    await expect(region(page)).toMatchAriaSnapshot({ name });
  });
}
