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
) -> dict[str, Any]:
    cited = sorted(
        {i for _, f in findings for i in f.evidence_ids}
        | {i for h in hypotheses for i in h.supporting_evidence + h.contradicting_evidence}
        | set((materiality or {}).get("evidence_ids", []))
    )
    by_id = {e.id: e for e in evidence}
    return {
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
    lines += [
        "- Nothing in this report has been benchmarked; hypotheses are unverified.",
    ]
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
    lines += ["", "## Evidence"]
    for e in report["evidence"]:
        lines.append(f"- `{e['id']}` ({e['kind']}, {e['provenance']}): {e['summary']}")
    if report["errors"]:
        lines += ["", "## Errors"]
        lines += [f"- {e['node']}: {e['code']} — {e['message']}" for e in report["errors"]]
    lines.append("")
    return "\n".join(lines)
