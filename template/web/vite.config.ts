import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, extname, join, resolve } from "node:path";
import { brotliCompressSync, constants, gzipSync } from "node:zlib";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

/**
 * The build's assets/ as the backend serves them (eneo_module_bff/web.py): kept for a year, so every name carries its
 * content's hash, and a .br and a .gz beside each script, stylesheet, SVG and JSON file, sent to a browser that accepts
 * one. Images and fonts are compressed already.
 */
function servedAssets(): Plugin {
  let assets = "";
  return {
    name: "eneo-module-served-assets",
    apply: "build",
    configResolved(config) {
      assets = resolve(config.root, config.build.outDir, config.build.assetsDir);
    },
    closeBundle() {
      const files = readdirSync(assets, { recursive: true, withFileTypes: true })
        .filter((entry) => entry.isFile())
        .map((entry) => join(entry.parentPath, entry.name));
      // ponytail: Vite's `name-<8 characters>`; a name whose last word has 8 letters passes too.
      const unhashed = files.filter((file) => !/[-.][\w-]{8}$/.test(basename(file, extname(file))));
      if (unhashed.length > 0) {
        throw new Error(`The backend keeps every file of ${assets} for a year, and these are not named by their content: ${unhashed.join(", ")}`);
      }
      for (const file of files.filter((name) => [".js", ".css", ".svg", ".json"].includes(extname(name)))) {
        const content = readFileSync(file);
        writeFileSync(`${file}.br`, brotliCompressSync(content, { params: { [constants.BROTLI_PARAM_QUALITY]: 11 } }));
        writeFileSync(`${file}.gz`, gzipSync(content, { level: 9 }));
      }
    },
  };
}

// In development the backend (python backend/...) listens on 3001 and the app asks it for /api; the built app is served
// by the backend itself, so there is no proxy in production.
export default defineConfig({
  plugins: [react(), servedAssets()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:3001" } },
  build: { outDir: "dist" },
});
