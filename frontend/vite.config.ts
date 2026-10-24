import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  worker: { format: "es" }, // MapLibre starts its worker as a module worker
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
      // D-24: tiles are built into infra/tiles/ and served by the frontend container.
      "/tiles": "http://localhost:3000",
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"], // e2e/ is Playwright
    css: false,
  },
});
