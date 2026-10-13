/** report-builder@1 output (report schema 1) as the API client delivers it (camelCase keys).
 * The backend builder is the source of truth (backend/src/querycure/reports/builders/v1.py). */

export type Provenance = "measured" | "prerecorded" | "derived" | "recorded" | "configured" | "imported";
export type FinalVerdict = "verified" | "verified_with_noise_warning" | "rejected" | "inconclusive";

export interface ReportEvidence {
  id: string;
  kind: string;
  summary: string;
  provenance: string;
  artifactSha256: string | null;
  locator: string;
}

export interface LatencySummary {
  n: number;
  medianNs: number;
  p95Ns: number | null;
  robustCv: number | null;
}

export interface Measurement {
  arm: string;
  paramSet: string;
  baseline: LatencySummary;
  candidate: LatencySummary;
  speedup: number;
  ciLow: number;
  ciHigh: number;
  provenance: string | null;
  evidenceId: string | null;
  source: { artifactSha256: string; pointer: string };
}

export interface Correctness {
  arm: string;
  paramSet: string;
  sameRows: boolean | null;
  rows: number | null;
  baselineRows: number | null;
  provenance: string | null;
  evidenceId: string | null;
}

export interface AuditCheck {
  name: string;
  status: "pass" | "warn" | "fail" | "skip";
  detail: string;
  evidenceIds: string[];
}

export interface AuditConcern {
  arm: string;
  severity: "info" | "warning" | "downgrade";
  text: string;
  evidenceIds: string[];
}

export interface CandidateAudit {
  arm: string;
  engineVerdict: FinalVerdict;
  verdict: FinalVerdict;
  downgraded: boolean;
  auditorStatus: "completed" | "deterministic_only";
  promptVersion: string | null;
  notes: string | null;
  checks: AuditCheck[];
  concerns: AuditConcern[];
}

export interface ReplicationVerdict {
  arm: string;
  verdict: "verified" | "verified_with_noise_warning" | "inconclusive";
  experimentIds: string[];
  ciLow: number | null;
  ciHigh: number | null;
  reasons: { code: string; detail: string }[];
}

export interface ReportExperiment {
  id: string;
  round: number;
  replicate: number;
  status: string;
  engineVersion: string;
  rowProfile: string;
  seed: number;
  provenance: string | null;
  resultSha256: string | null;
  errorCode: string | null;
  environment: {
    digest: string | null;
    pgVersion: string | null;
    cpuArch: string | null;
    cpuModel: string | null;
    cpuCount: number | null;
    memoryBytes: number | null;
    os: string | null;
    containerRuntime: string | null;
    sandboxImageDigest: string | null;
    workloadId: string | null;
    workloadDataDigest: string | null;
    provenance: string | null;
  };
  config: {
    measuredRuns: number;
    warmupRuns: number;
    blockSize: number;
    minEffect: number;
    maxRegression: number;
    maxCv: number;
    provenance: string;
  } | null;
  builds: { arm: string; ok: boolean; reason: string | null; indexSizeBytes: number; buildNs: number; provenance: string | null }[];
  verdicts: { arm: string; verdict: string; reasons: { code: string; detail: string }[]; gate: number | null }[];
  tournament: { arm: string; rank: number; verdict: string; primaryCiLow: number | null }[];
  winner: string | null;
  measurements: Measurement[];
  correctness: Correctness[];
  replication: { verdicts: ReplicationVerdict[]; winner: string | null } | null;
  audit: CandidateAudit[];
}

export interface ReportCandidate {
  key: string;
  kind: string;
  ddl: string[];
  querySql: string | null;
  sqlSha256: string;
  addressesHypotheses: string[];
  expectedBenefit: string;
  risks: string[];
  status: string;
  reasons: { code: string; detail?: string }[];
}

export interface ReportRound {
  round: number;
  approval: {
    id: string;
    round: number;
    status: string;
    decidedBy: string | null;
    decidedAt: string | null;
    approvedCandidateIds: string[];
  } | null;
  candidates: ReportCandidate[];
  experiment: ReportExperiment | null;
  replicates: ReportExperiment[];
}

export interface ReplayPair {
  arm: string;
  paramSet: string;
  status: "reproduced" | "reproduced_with_drift" | "inconclusive" | "not_reproduced";
  code: string | null;
  originalVerdict: string | null;
  replayVerdict: string | null;
  originalSpeedup: number | null;
  replaySpeedup: number | null;
  originalCi: [number, number] | null;
  replayCi: [number, number] | null;
  originalMediansNs: [number, number] | null;
  replayMediansNs: [number, number] | null;
  drift: number | null;
  driftCiLow: number | null;
  driftCiHigh: number | null;
}

export interface EnvironmentDifference {
  field: string;
  class: "precondition" | "material" | "minor";
  original: unknown;
  replay: unknown;
}

export interface Comparison {
  status: string;
  failureCode: string | null;
  comparisonMode: "same_environment" | "cross_environment";
  config: { margin: number; resamples: number; confidence: number; seed: number };
  pairs: ReplayPair[];
  environment: {
    originalDigest: string | null;
    replayDigest: string | null;
    differences: EnvironmentDifference[];
  };
  winner: { original: string | null; replay: string | null };
  limitations: string[];
  detail?: string;
  originalExperimentId?: string;
  replayExperimentId?: string;
}

export interface ReportV1 {
  schemaVersion: number;
  builderVersion: string;
  run: { id: string; investigationId: string; runNumber: number; kind: string; parentRunId: string | null };
  investigation: { title: string; objective: string; modes: string[]; workloadId: string | null; liveConnection: boolean };
  finalizedAt: string;
  events: { cutoffSeq: number; digest: string; profile: string };
  finalStatus: string;
  outcome: string | null;
  stopReason: string | null;
  partial: boolean;
  headline: string;
  summary: string;
  query: { sql: string | null; sha256: string | null; paramSets: { name: string; values: unknown[]; edgeCase?: boolean }[] | null };
  problem: {
    evidence: ReportEvidence[];
    materiality: { verdict: string; reasons: string[]; evidenceIds: string[] } | null;
  };
  hypotheses: {
    key: string;
    rank: number;
    statement: string;
    category: string;
    supportingEvidence: string[];
    contradictingEvidence: string[];
    confidence: string;
    uncertaintyNotes: string;
    verificationMethod: string;
  }[];
  findings: { key: string; agent: string; title: string; detail: string; severity: string; evidenceIds: string[] }[];
  evidence: ReportEvidence[];
  rounds: ReportRound[];
  recommendation: {
    status: "verified" | "verified_with_noise_warning" | "unverified" | "none";
    candidateKey: string | null;
    kind: string | null;
    ddl: string[];
    querySql: string | null;
    primaryMeasurement: Measurement | null;
    scope: string;
  };
  limitations: string[];
  nextSteps: string[];
  provenance: {
    measurements: string[];
    stubModel: boolean;
    llm: { agent: string; model: string; servedBy: string | null; promptVersion: string; status: string; calls: number }[];
  };
  replay: { replayOf: { experimentId: string; runId: string | null } | null; comparison: Comparison | null } | null;
  missing: { section: string; reason: string }[];
  errors: { node?: string; code?: string; message?: string }[];
  usage: Record<string, number> | null;
}
