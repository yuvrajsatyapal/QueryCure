import { defineConfig, devices } from "@playwright/test";

const API_PORT = 8100;
const WEB_PORT = 3200;
const SANDBOX_URL = "postgresql://qc_sandbox_admin:qc_local_dev_only@127.0.0.1:55432/sandbox_admin";
// Pinned like the sandbox: backend/.env may point the app at a hosted metadata DB (Neon), and
// e2e must never write test runs there. Override with QC_E2E_DATABASE_URL.
const METADATA_URL = "postgresql://qc_app:qc_local_dev_only@127.0.0.1:5432/querycure";

/** End-to-end against the real API, worker and metadata DB (docker compose up -d), with the
 * offline stub LLM: no model calls, deterministic output (LLM_PROVIDER=stub, local only). */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  fullyParallel: false,
  // One spec at a time: the local profile allows 2 active runs per user, and sandbox
  // measurements should not overlap.
  workers: 1,
  retries: 0,
  use: { baseURL: `http://localhost:${WEB_PORT}`, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        `cd ../backend && export LLM_PROVIDER=stub WORKER_POLL_SECONDS=0.2 ` +
        `DATABASE_URL=\${QC_E2E_DATABASE_URL:-${METADATA_URL}} ` +
        `DATABASE_URL_DIRECT=\${QC_E2E_DATABASE_URL:-${METADATA_URL}} ` +
        // Mode C: the compose sandbox through its loopback relay (CI maps the same port).
        `SANDBOX_ADMIN_URL=\${SANDBOX_ADMIN_URL:-${SANDBOX_URL}} ` +
        `SANDBOX_BENCH_PASSWORD=\${SANDBOX_BENCH_PASSWORD:-qc_local_dev_only} ` +
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
