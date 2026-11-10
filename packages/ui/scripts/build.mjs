// The package: tsc to dist/, and the files tsc does not carry (the built theme, the stylesheets) beside it.
import { appendFileSync, cpSync, readFileSync, rmSync } from "node:fs";
import { createRequire } from "node:module";
import { spawnSync } from "node:child_process";
import { pathToFileURL } from "node:url";

rmSync("dist", { recursive: true, force: true });
const tsc = spawnSync("tsc", ["-p", "tsconfig.json"], { stdio: "inherit" });
if (tsc.status !== 0) process.exit(tsc.status ?? 1);

cpSync("src/theme/built", "dist/theme/built", { recursive: true });
// The package's own stylesheets, under the names its `exports` give them.
cpSync("src/theme/built/eneo.css", "dist/theme.css");
cpSync("src/layers.css", "dist/layers.css");
cpSync("src/base.css", "dist/base.css");
// Astryx writes its layers' position rules (`@position-try`) into a <style> of its own, which the strict `style-src 'self'`
// refuses. base.css carries them, from the release the package is built against (they are not among its exports), and
// ModuleProviders renders the element Astryx looks for first, so it writes nothing.
const layerRules = await import(new URL("layerSlideRules.js", pathToFileURL(createRequire(import.meta.url).resolve("@astryxdesign/core/Layer"))).href);
appendFileSync("dist/base.css", `\n/* Astryx's layer position rules (scripts/build.mjs). */\n${layerRules.slideRulesCss()}\n`);
if (!readFileSync("dist/ModuleProviders.js", "utf8").includes(`"${layerRules.SLIDE_RULES_ID}"`)) {
  console.error(`dist/ModuleProviders.js does not render #${layerRules.SLIDE_RULES_ID}, the element Astryx looks for before it writes its layer rules`);
  process.exit(1);
}

// What was built is plain ESM that loads, with the public names a module imports.
const built = await import(new URL("../dist/index.js", import.meta.url).href);
const expected = ["BRANDING_DEADLINE_MS", "Brand", "BrandingProvider", "COLOR_MODE_KEY", "ColorModeProvider", "CopyButton", "ErrorPage", "LoadFailure", "LoadingShell", "ModuleProviders", "ModuleShell", "NotFoundPage", "OfflineBanner", "RouteEffects", "SlowWait", "VersionInfo", "createDrafts", "createOnlineStatus", "eneoTheme", "lazyLoader", "onlineStatus", "readStoredColorMode", "useColorMode", "useConnection", "useLeaveQuestion", "useLoaded", "useRouteReady"];
const missing = expected.filter((name) => !(name in built));
if (missing.length > 0) {
  console.error(`dist/index.js does not export ${missing.join(", ")}`);
  process.exit(1);
}
const session = await import(new URL("../dist/session/index.js", import.meta.url).href);
const expectedSession = ["RequestTimeoutError", "RequireSession", "SESSION_CHANNEL", "SessionExpiredError", "SignInScreen", "SignedInAgain", "createFetchWithSession", "createSessionState", "createUploadWithProgress", "errorAdvice", "fetchWithSession", "isSessionEndedAnswer", "refusalOf", "sessionState", "sessionUser", "uploadWithProgress", "useSessionUser", "useSignedOut", "useSignedOutSlot", "userDisplayName", "userInitial"];
const missingSession = expectedSession.filter((name) => !(name in session));
if (missingSession.length > 0) {
  console.error(`dist/session/index.js does not export ${missingSession.join(", ")}`);
  process.exit(1);
}
