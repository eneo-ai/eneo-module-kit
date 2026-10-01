// The unit tests: tsc to .test-build/ (ESM, as the package itself), the built theme beside the sources that import
// it, then node's test runner over the compiled tests.
import { cpSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";

rmSync(".test-build", { recursive: true, force: true });
const tsc = spawnSync("tsc", ["-p", "tsconfig.test.json"], { stdio: "inherit" });
if (tsc.status !== 0) process.exit(tsc.status ?? 1);

cpSync("src/theme/built", ".test-build/src/theme/built", { recursive: true });
const test = spawnSync(process.execPath, ["--test", ".test-build/tests/*.test.js"], { stdio: "inherit" });
process.exit(test.status ?? 1);
