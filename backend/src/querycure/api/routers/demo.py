"""Public, read-only demo gallery (T5.5; DEPLOYMENT §1 "prerecorded, labelled").

No session is needed and nothing is executed: bundles and benchmark fixtures ship with the
package. Each response carries `provenance = "prerecorded"` and the human label, and the
verification endpoint recomputes digests over the shipped bytes only.
"""

import base64
import json

from fastapi import APIRouter

from querycure.api.schemas.demo import (
    DemoArtifactRef,
    DemoBenchmark,
    DemoBenchmarkArm,
    DemoBenchmarkStat,
    DemoCheck,
    DemoDetail,
    DemoGallery,
    DemoItem,
    DemoVerification,
)
from querycure.api.schemas.investigations import RunPlan
from querycure.benchmark.fixtures import PrerecordedExperiment
from querycure.core.errors import NotFoundError
from querycure.demo.gallery import DemoBundle, load_benchmark_fixtures, load_bundles, verify_bundle
from querycure.plans.metrics import compute_metrics
from querycure.plans.parser import parse_plan

router = APIRouter(prefix="/demo", tags=["demo"])
PLAN_ROLES = ("input.plan", "context.plan")
SCOPE = (
    "Recomputes the SHA-256 of every shipped artifact and checks it against the run's "
    "manifest digest. This shows the shipped bytes are consistent with the manifest; it is "
    "not a full report replay (the demo ships no database records) and not proof of "
    "authenticity."
)


def _item(b: DemoBundle) -> DemoItem:
    return DemoItem(
        slug=b.slug,
        title=b.title,
        headline=str(b.report().get("headline", "")),
        summary=b.summary,
        label=b.label,
        outcome=b.outcome,
        model=b.source.model,
        recorded_at=b.source.recorded_at,
        measurements_recorded_on=b.source.measurements_recorded_on,
    )


def _benchmark(path_id: str, e: PrerecordedExperiment) -> DemoBenchmark:
    verdicts = {v.arm: v for v in e.result.verdicts}
    return DemoBenchmark(
        id=path_id,
        label=e.label,
        recorded_on=e.recorded_on,
        source_note=e.source_note,
        workload_id=e.config.workload_id,
        baseline_query=e.config.baseline_query,
        engine_version=e.result.engine_version,
        arms=[
            DemoBenchmarkArm(
                arm=c.arm,
                kind=c.kind,
                ddl=list(c.ddl),
                query=c.query,
                verdict=verdicts[c.arm].verdict if c.arm in verdicts else "inconclusive",
                gate=verdicts[c.arm].gate if c.arm in verdicts else None,
                reasons=[
                    {"code": r.code, "detail": r.detail}
                    for r in (verdicts[c.arm].reasons if c.arm in verdicts else [])
                ],
            )
            for c in e.config.candidates
        ],
        stats=[
            DemoBenchmarkStat(
                arm=s.arm,
                param_set=s.param_set,
                speedup=round(s.speedup, 3),
                ci_low=round(s.ci_low, 3),
                ci_high=round(s.ci_high, 3),
                baseline_median_ms=round(s.baseline.median_ns / 1e6, 3),
                candidate_median_ms=round(s.candidate.median_ns / 1e6, 3),
                n=min(s.baseline.n, s.candidate.n),
            )
            for s in e.result.stats
        ],
        environment={
            "cpu_arch": e.environment.cpu_arch,
            "cpu_count": e.environment.cpu_count,
            "os": e.environment.os,
            "pg_version": e.environment.pg_version,
            "container_runtime": e.environment.container_runtime,
        },
    )


def _bundle(slug: str) -> DemoBundle:
    for b in load_bundles():
        if b.slug == slug:
            return b
    raise NotFoundError("Demo investigation not found.")


@router.get("/gallery")
async def gallery() -> DemoGallery:
    benchmarks = [
        _benchmark(f"fixture-{i}", e) for i, e in enumerate(load_benchmark_fixtures(), start=1)
    ]
    return DemoGallery(items=[_item(b) for b in load_bundles()], benchmarks=benchmarks)


@router.get("/gallery/{slug}")
async def demo_detail(slug: str) -> DemoDetail:
    b = _bundle(slug)
    plans = []
    for art in b.artifacts:
        if art.role in PLAN_ROLES:
            tree = parse_plan(json.loads(base64.b64decode(art.content_b64)))
            plans.append(
                RunPlan(
                    sha256=art.sha256, kind=art.kind, role=art.role, plan=tree,
                    metrics=compute_metrics(tree),
                )
            )  # fmt: skip
    return DemoDetail(
        **_item(b).model_dump(),
        run_id=b.run_id,
        manifest_sha256=b.manifest_sha256,
        report_json_sha256=b.report_json_sha256,
        report_md_sha256=b.report_md_sha256,
        report=b.report(),
        plans=plans,
        artifacts=[DemoArtifactRef(role=a.role, kind=a.kind, sha256=a.sha256) for a in b.artifacts],
        source=b.source.model_dump(),
    )


@router.get("/gallery/{slug}/verification")
async def demo_verification(slug: str) -> DemoVerification:
    checks = verify_bundle(_bundle(slug))
    return DemoVerification(
        slug=slug,
        status="consistent" if all(c.passed for c in checks) else "mismatch",
        checks=[DemoCheck(name=c.name, passed=c.passed, detail=c.detail) for c in checks],
        scope=SCOPE,
    )
