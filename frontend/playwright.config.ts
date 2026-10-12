import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8100;
const WEB_PORT = 3200;

/** End-to-end against the real API, worker and metadata DB (docker compose up -d), with the
 * offline stub LLM: no model calls, deterministic output (LLM_PROVIDER=stub, local only). */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  retries: 0,
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        `cd ../backend && export LLM_PROVIDER=stub WORKER_POLL_SECONDS=0.2 ` +
        `CORS_ORIGINS='["http://localhost:${WEB_PORT}"]' && ` +
        `(uv run python -m querycure.worker &) && ` +
        `exec uv run uvicorn querycure.api.main:app --port ${API_PORT}`,
      url: `http://localhost:${API_PORT}/api/v1/healthz`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
    {
      command: `pnpm dev --port ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}/app`,
      env: { NEXT_PUBLIC_API_BASE_URL: `http://localhost:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
