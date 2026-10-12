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
export type RunSummary = Camel<"RunSummary">;
export type RunDetail = Camel<"RunDetail">;
export type InvestigationSummary = Camel<"InvestigationSummary">;
export type InvestigationDetail = Camel<"InvestigationDetail">;
export type InvestigationPage = Camel<"InvestigationPage">;
export type CreateInvestigationResponse = Camel<"CreateInvestigationResponse">;
export type FindingsResponse = Camel<"FindingsResponse">;
export type Finding = Camel<"FindingOut">;
export type Hypothesis = Camel<"Hypothesis">;
export type Evidence = Camel<"Evidence">;
export type EvidenceDetail = Camel<"EvidenceDetail">;
export type RunPlan = Camel<"RunPlan">;
export type RunPlanList = Camel<"RunPlanList">;
export type ModelsInfo = Camel<"ModelsResponse">;
export type RunEvent = Camel<"RunEvent">;

export type InvestigationMode = "offline" | "live_inspection";
export interface ParamSetInput {
  name: string;
  values: (string | number | boolean | null)[];
}
export interface CreateInvestigationInput {
  title: string;
  objective: string;
  modes: InvestigationMode[];
  query: string;
  paramSets: ParamSetInput[];
  connectionId?: string;
  planArtifactSha256?: string;
}

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
