import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the backend (python backend/...) listens on 3001 and the app asks it for /api; the built app is served
// by the backend itself, so there is no proxy in production.
export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:3001" } },
  build: { outDir: "dist" },
});
