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
export type OptimizationCandidate = Camel<"OptimizationCandidate">;
export type CandidateList = Camel<"CandidateList">;
export type Approval = Camel<"ApprovalOut">;
export type ApprovalList = Camel<"ApprovalList">;
export type ExperimentSummary = Camel<"ExperimentSummary">;
export type ExperimentList = Camel<"ExperimentList">;
export type ExperimentDetail = Camel<"ExperimentDetail">;
export type SpeedupStats = Camel<"SpeedupStats">;
export type RuleVerdict = Camel<"RuleVerdict">;
export type WorkloadInfo = Camel<"WorkloadInfo">;
export interface DecisionInput {
  decision: "approve" | "decline" | "partial";
  candidateIds: string[];
  comment?: string;
}

export type InvestigationMode = "offline" | "live_inspection" | "sandbox_benchmark";
export interface ParamSetInput {
  name: string;
  values: (string | number | boolean | null)[];
  edgeCase?: boolean;
}
export interface CreateInvestigationInput {
  title: string;
  objective: string;
  modes: InvestigationMode[];
  query: string;
  paramSets: ParamSetInput[];
  connectionId?: string;
  planArtifactSha256?: string;
  workloadId?: string;
  preAuthorizeDemoSandbox?: boolean;
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

export type ReportOut = Camel<"ReportOut">;
export type ManifestOut = Camel<"ManifestOut">;
export type ReplayAttempt = Camel<"ReplayAttemptOut">;
export type ReplayAttemptPage = Camel<"ReplayAttemptPage">;
export type PlanDiffOut = Camel<"PlanDiffOut">;
export type PlanDiff = Camel<"PlanDiff">;
export type PlanNodeDiff = Camel<"PlanNodeDiff">;
export type Verification = Camel<"VerificationOut">;
export type VerificationList = Camel<"VerificationList">;
export type LlmCredential = Camel<"LlmCredentialOut">;
export type LlmCredentialList = Camel<"LlmCredentialList">;
