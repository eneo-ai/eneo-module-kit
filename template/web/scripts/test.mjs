// The unit tests (`npm test`): tests/unit/ and the sources they import, compiled by tsc to .test-build/, then node's test
// runner over the compiled tests, each file after tests/unit/setup.mjs.
import { spawnSync } from "node:child_process";
import { rmSync } from "node:fs";

rmSync(".test-build", { recursive: true, force: true });
const tsc = spawnSync("tsc", ["-p", "tsconfig.test.json"], { stdio: "inherit" });
if (tsc.status !== 0) process.exit(tsc.status ?? 1);

const test = spawnSync(process.execPath, ["--import", "./tests/unit/setup.mjs", "--test", ".test-build/tests/unit/**/*.test.js"], { stdio: "inherit" });
process.exit(test.status ?? 1);
