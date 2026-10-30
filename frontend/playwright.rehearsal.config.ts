import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/** Workstream 5 real-stack rehearsal (REPLAY_OUTCOME_AUDIT §17): the same API, web app, metadata
 * DB and sandbox as the e2e suite, but the worker is `tests.rehearsal.activated_worker`, which
 * simulates the approved replay-outcome activation (classifier + report-builder@2 / report-md@2)
 * and times benchmarks with the seeded virtual clock. Local only; production code and defaults
 * are unchanged. Run: `pnpm exec playwright test -c playwright.rehearsal.config.ts`. */
const servers = Array.isArray(base.webServer) ? base.webServer : [];
const PRODUCTION_WORKER = "uv run python -m querycure.worker";
if (!servers[0]?.command.includes(PRODUCTION_WORKER)) throw new Error("rehearsal: unexpected API server command");

export default defineConfig({
  ...base,
  testIgnore: [],
  testMatch: ["**/replay-rehearsal.spec.ts"],
  webServer: [
    { ...servers[0]!, command: servers[0]!.command.replace(PRODUCTION_WORKER, "uv run python -m tests.rehearsal.activated_worker") },
    ...servers.slice(1),
  ],
});
