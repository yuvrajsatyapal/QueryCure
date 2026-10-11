import { afterEach, expect, test } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { CapabilityChecklist } from "../CapabilityChecklist";
import type { TargetCapabilities } from "@/lib/api/types";

afterEach(cleanup);

const caps: TargetCapabilities = {
  serverVersionNum: 170011,
  serverVersion: "17.11",
  isSuperuser: false,
  canCreateRole: false,
  bypassesRls: false,
  isReplicationRole: false,
  canReadAllStats: true,
  hasPgStatStatements: false,
  sslInUse: false,
  ownedTables: 0,
  schemas: ["public"],
  warnings: ["role is not a member of pg_read_all_stats; workload views are limited"],
};

test("each capability states its result in words, not only color", () => {
  render(<CapabilityChecklist capabilities={caps} />);

  expect(screen.getByText("PostgreSQL 17.11")).toBeDefined();
  expect(screen.getByText(/Not a superuser/)).toBeDefined();
  expect(screen.getByText(/pg_stat_statements not installed/)).toBeDefined();
  expect(screen.getByText(/workload views are limited/)).toBeDefined();
});
