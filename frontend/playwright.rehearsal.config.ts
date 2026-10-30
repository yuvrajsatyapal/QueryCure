import { defineConfig } from "@playwright/test";
import base from "./playwright.config";

/** Workstream 5 real-stack rehearsal (REPLAY_OUTCOME_AUDIT §17, §19): the same API, web app,
 * metadata DB, sandbox and production worker code as the e2e suite. The only difference is that
 * the worker is started as `tests.rehearsal.clocked_worker`, which times benchmarks with the
 * seeded virtual clock so each replay reaches the scenario it names. Classification and sealing
 * are the activated production code. Local only.
 * Run: `pnpm exec playwright test -c playwright.rehearsal.config.ts`. */
const servers = Array.isArray(base.webServer) ? base.webServer : [];
const PRODUCTION_WORKER = "uv run python -m querycure.worker";
if (!servers[0]?.command.includes(PRODUCTION_WORKER)) throw new Error("rehearsal: unexpected API server command");

export default defineConfig({
  ...base,
  testIgnore: [],
  testMatch: ["**/replay-rehearsal.spec.ts"],
  webServer: [
    { ...servers[0]!, command: servers[0]!.command.replace(PRODUCTION_WORKER, "uv run python -m tests.rehearsal.clocked_worker") },
    ...servers.slice(1),
  ],
});
