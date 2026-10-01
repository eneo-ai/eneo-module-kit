// The package: tsc to dist/, and the files tsc does not carry (the built theme, the stylesheets) beside it.
import { cpSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";

rmSync("dist", { recursive: true, force: true });
const tsc = spawnSync("tsc", ["-p", "tsconfig.json"], { stdio: "inherit" });
if (tsc.status !== 0) process.exit(tsc.status ?? 1);

cpSync("src/theme/built", "dist/theme/built", { recursive: true });
// The package's own stylesheets, under the names its `exports` give them.
cpSync("src/theme/built/eneo.css", "dist/theme.css");
cpSync("src/layers.css", "dist/layers.css");
cpSync("src/base.css", "dist/base.css");

// What was built is plain ESM that loads, with the public names a module imports.
const built = await import(new URL("../dist/index.js", import.meta.url).href);
const expected = ["BRANDING_DEADLINE_MS", "Brand", "BrandingProvider", "COLOR_MODE_KEY", "ColorModeProvider", "ModuleProviders", "ModuleShell", "eneoTheme", "readStoredColorMode", "useColorMode"];
const missing = expected.filter((name) => !(name in built));
if (missing.length > 0) {
  console.error(`dist/index.js does not export ${missing.join(", ")}`);
  process.exit(1);
}
