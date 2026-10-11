import type { CamelCasedPropertiesDeep } from "type-fest";
import type { components } from "./generated/schema";

type Schemas = components["schemas"];
type Camel<K extends keyof Schemas> = CamelCasedPropertiesDeep<Schemas[K]>;

export type User = Camel<"UserOut">;
export type Me = Camel<"MeResponse">;
export type ConnectionSummary = Camel<"ConnectionSummary">;
export type ConnectionList = Camel<"ConnectionList">;
export type ConnectionTestResult = Camel<"ConnectionTestResponse">;
export type TargetCapabilities = Camel<"TargetCapabilities">;
export type PlanTree = Camel<"PlanTree">;
export type PlanNode = Camel<"PlanNode">;
export type NodeMetrics = Camel<"NodeMetrics">;
export type ExplainResult = Camel<"ExplainResponse">;
export type PlanInspection = Camel<"PlanInspection">;
export type SqlAnalysis = Camel<"SqlAnalysis">;
export type WorkloadCatalog = Camel<"WorkloadCatalog">;

export type CreateConnectionInput = {
  name: string;
  host: string;
  port: number;
  dbname: string;
  username: string;
  password: string;
  sslmode: "disable" | "require" | "verify-ca" | "verify-full";
  environment: "development" | "staging" | "production";
};
