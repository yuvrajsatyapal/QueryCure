"""Public demo gallery (T5.5). Every payload carries the prerecorded label."""

from typing import Any, Literal

from pydantic import BaseModel

from querycure.api.schemas.investigations import RunPlan


class DemoItem(BaseModel):
    slug: str
    title: str
    summary: str
    label: str
    provenance: Literal["prerecorded"] = "prerecorded"
    outcome: str | None
    model: str
    recorded_at: str | None
    measurements_recorded_on: str | None


class DemoBenchmarkArm(BaseModel):
    arm: str
    kind: str
    ddl: list[str]
    query: str | None
    verdict: str
    gate: int | None
    reasons: list[dict[str, str]]


class DemoBenchmarkStat(BaseModel):
    arm: str
    param_set: str
    speedup: float
    ci_low: float
    ci_high: float
    baseline_median_ms: float
    candidate_median_ms: float
    n: int


class DemoBenchmark(BaseModel):
    id: str
    label: str
    provenance: Literal["prerecorded"] = "prerecorded"
    recorded_on: str
    source_note: str
    workload_id: str
    baseline_query: str
    engine_version: str
    arms: list[DemoBenchmarkArm]
    stats: list[DemoBenchmarkStat]
    environment: dict[str, Any]


class DemoGallery(BaseModel):
    items: list[DemoItem]
    benchmarks: list[DemoBenchmark]


class DemoArtifactRef(BaseModel):
    role: str
    kind: str
    sha256: str


class DemoDetail(DemoItem):
    run_id: str
    manifest_sha256: str
    report_json_sha256: str
    report_md_sha256: str
    report: dict[str, Any]
    plans: list[RunPlan]
    artifacts: list[DemoArtifactRef]
    source: dict[str, Any]


class DemoCheck(BaseModel):
    name: str
    passed: bool
    detail: str


class DemoVerification(BaseModel):
    slug: str
    status: Literal["consistent", "mismatch"]
    checks: list[DemoCheck]
    scope: str
