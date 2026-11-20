import { defineConfig, devices } from "@playwright/test";

// Runs against a live stack: docker compose with LLM_BACKEND=fake, seeded by scripts/seed_fixtures.py.
// E2E_URL points elsewhere, e.g. the Vite dev server (http://localhost:5173).
export default defineConfig({
  testDir: "e2e",
  workers: 1, // one shared database: the role demo publishes v2 at the end
  reporter: [["list"]],
  use: { baseURL: process.env.E2E_URL ?? "http://localhost:8000", trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
