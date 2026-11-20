import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs separately (uvicorn or docker compose on :8000); these paths go to it.
// In the built app the API serves the UI itself, on the same origin.
const api = "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/v1": api, "/ui": api, "/policies": api, "/health": api } },
  test: { include: ["src/**/*.test.ts"] },
});
