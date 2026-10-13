"""Interim report (Phase 2): a deterministic findings summary built from persisted records.

It reads no clock and takes every value from stored rows, so rebuilding it from the same
records gives identical bytes. Finalization, manifests and versioned builders arrive in
Phase 4 (REPLAY_ENGINE §5, §7); these reports are never retro-sealed.
"""

from typing import Any

from querycure.domain.investigation import Evidence, Finding, Hypothesis

# @2 adds the deterministic materiality verdict (@1 stays as released, ADR-0015).
BUILDER_VERSION = "interim-report@2"
REPORT_SCHEMA_VERSION = 2
# @3 (Phase 3) adds the optimization rounds: candidates, approvals, experiments and their
# deterministic verdicts. A run without optimization data still builds byte-identical @2.
BUILDER_VERSION_V3 = "interim-report@3"
REPORT_SCHEMA_VERSION_V3 = 3
# @4 (ADR-0019) adds replicate experiments and replication verdicts to a round. A run without
# replicates still builds byte-identical @3.
BUILDER_VERSION_V4 = "interim-report@4"
REPORT_SCHEMA_VERSION_V4 = 4


def build_report(
    *,
    run_id: str,
    objective: str,
    final_status: str,
    outcome: str | None,
    stop_reason: str | None,
    findings: list[tuple[str, Finding]],
    hypotheses: list[Hypothesis],
    evidence: list[Evidence],
    errors: list[dict[str, Any]],
    usage: dict[str, Any],
    synthesis_summary: str,
    materiality: dict[str, Any] | None = None,
    optimization: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cited = sorted(
        {i for _, f in findings for i in f.evidence_ids}
        | {i for h in hypotheses for i in h.supporting_evidence + h.contradicting_evidence}
        | set((materiality or {}).get("evidence_ids", []))
        | set((optimization or {}).get("evidence_ids", []))
    )
    by_id = {e.id: e for e in evidence}
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "run_id": run_id,
        "objective": objective,
        "final_status": final_status,
        "outcome": outcome,
        "stop_reason": stop_reason,
        "partial": stop_reason is not None or final_status != "completed",
        "summary": synthesis_summary,
        "materiality": materiality,
        "hypotheses": [h.model_dump() for h in sorted(hypotheses, key=lambda h: h.rank)],
        "findings": [{"key": key, **f.model_dump()} for key, f in findings],
        "evidence": [by_id[i].model_dump() for i in cited if i in by_id],
        "errors": errors,
        "usage": usage,
        "verification": "not_benchmarked",
    }
    if optimization is None:
        return report
    replicated = any(
        (r.get("experiment") or {}).get("replication") is not None for r in optimization["rounds"]
    )
    return {
        **report,
        "schema_version": REPORT_SCHEMA_VERSION_V4 if replicated else REPORT_SCHEMA_VERSION_V3,
        "builder_version": BUILDER_VERSION_V4 if replicated else BUILDER_VERSION_V3,
        "verification": optimization["verification"],
        "optimization": {k: v for k, v in optimization.items() if k != "evidence_ids"},
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# QueryCure investigation (interim report)",
        "",
        f"- Run: `{report['run_id']}`",
        f"- Status: {report['final_status']}"
        + (f" ({report['outcome']})" if report["outcome"] else ""),
    ]
    if report["partial"]:
        lines.append(
            f"- Partial report (stopped: {report['stop_reason'] or report['final_status']})"
        )
    optimization = report.get("optimization")
    if optimization is None:
        lines += [
            "- Nothing in this report has been benchmarked; hypotheses are unverified.",
        ]
    else:
        lines.append(f"- Verification: {report['verification']}")
    materiality = report.get("materiality")
    if materiality and materiality["verdict"] == "not_material":
        lines.append(
            "- **Not worth optimizing** (deterministic materiality check): "
            + " ".join(materiality["reasons"])
            + f" — evidence {', '.join(materiality['evidence_ids'])}"
        )
    lines += ["", "## Hypotheses"]
    if not report["hypotheses"]:
        lines.append("No hypotheses were produced.")
    for h in report["hypotheses"]:
        lines.append(
            f"{h['rank']}. **{h['category']}** ({h['confidence']} confidence): {h['statement']} "
            f"— evidence {', '.join(h['supporting_evidence'])}"
        )
    lines += ["", "## Findings"]
    if not report["findings"]:
        lines.append("No findings were produced.")
    for f in report["findings"]:
        lines.append(
            f"- [{f['agent']}] ({f['severity']}) {f['title']}: {f['detail']} "
            f"— evidence {', '.join(f['evidence_ids'])}"
        )
    if optimization is not None:
        lines += _optimization_lines(optimization)
    lines += ["", "## Evidence"]
    for e in report["evidence"]:
        lines.append(f"- `{e['id']}` ({e['kind']}, {e['provenance']}): {e['summary']}")
    if report["errors"]:
        lines += ["", "## Errors"]
        lines += [f"- {e['node']}: {e['code']} — {e['message']}" for e in report["errors"]]
    lines.append("")
    return "\n".join(lines)


def _optimization_lines(optimization: dict[str, Any]) -> list[str]:
    lines = ["", "## Optimization (sandbox benchmark)"]
    for rnd in optimization["rounds"]:
        approval = rnd["approval"]
        lines.append(
            f"### Round {rnd['round'] + 1}: approval {approval['status'] if approval else 'none'}"
            + (f" by {approval['decided_by']}" if approval and approval["decided_by"] else "")
        )
        for c in rnd["candidates"]:
            sql = " ; ".join(c["ddl"]) if c["ddl"] else (c["query_sql"] or "")
            reasons = ", ".join(f"{r['code']}" for r in c["reasons"] or [])
            lines.append(
                f"- `{c['key']}` {c['kind']}: **{c['status']}**"
                + (f" ({reasons})" if reasons else "")
                + f" — `{sql}`"
            )
        experiment = rnd["experiment"]
        if experiment is None:
            continue
        lines.append(
            f"- Experiment `{experiment['id']}` ({experiment['engine_version']}): "
            f"{experiment['status']}"
            + (f", winner `{experiment['winner']}`" if experiment["winner"] else "")
            + (
                f", environment digest `{experiment['environment_digest']}`"
                if experiment["environment_digest"]
                else ""
            )
        )
        for m in experiment["metrics"]:
            lines.append(f"  - {m['summary']} — evidence {m['evidence_id']} (measured)")
        replication = experiment.get("replication")
        if replication is not None:
            lines += _replication_lines(replication)
    lines.append(
        "- Verified means: faster with matching results on the tested data and parameter sets, "
        "warm cache, single session, in the sandbox. It is not a production guarantee."
    )
    return lines


def _replication_lines(replication: dict[str, Any]) -> list[str]:
    """ADR-0019: the noise warning is always spelled out, never shortened to "verified"."""
    lines = [
        f"- Noisy result re-measured in {len(replication['replicates'])} independent replicate "
        "experiment(s) (new seeds and clones, same approved SQL):"
    ]
    for r in replication["replicates"]:
        lines.append(f"  - Replicate {r['replicate']}: `{r['id']}` {r['status']}")
    for v in replication["verdicts"]:
        label = {
            "verified_with_noise_warning": "verified with noise warning",
            "verified": "verified",
            "inconclusive": "inconclusive",
        }[v["verdict"]]
        span = (
            f", speedup CI range {v['ci_low']:.2f}-{v['ci_high']:.2f}x across experiments"
            if v["ci_low"] is not None and v["ci_high"] is not None
            else ""
        )
        why = f" ({v['reasons'][0]['detail']})" if v["reasons"] else ""
        lines.append(f"  - `{v['arm']}`: **{label}**{span}{why}")
    return lines
