"""Optimization materiality: is enough at stake for a fix to be worth making? (AGENT_SYSTEM §5, §12)

A plan can show a textbook pattern (a Seq Scan with a filter) that is still not worth acting
on: 50 rows read in 0.04 ms will not get meaningfully faster with an index. This module decides
that from evidence, deterministically. There is no single latency cutoff; the verdict combines:

- measured execution time against the query's own fixed overhead (planning time),
- how much data the plan touched (rows read by scans, rows filtered away),
- how large the Seq-Scanned tables are in the catalog (a Seq Scan grows with its table),
- how often the query runs (its share of `pg_stat_statements` time, when matched),
- signals of real work regardless of size (sorts or hashes spilling to disk).

`not_material` needs *every* signal to agree; anything unmeasured leaves it `undetermined`,
and the gate only acts on `not_material`. The LLM never sees or sets this verdict.
"""

from collections.abc import Sequence
from typing import Literal

from querycure.domain.investigation import Confidence, Evidence, Frozen, Hypothesis
from querycure.sql.fingerprint import match_key

# Below this, a scan touches only a few 8 KiB pages: an index descent costs about as many page
# reads as the scan itself, so no access-path change can save meaningful work.
SMALL_WORK_ROWS = 1_000
# A query using at least this share of the measured statement time is hot: small per-call
# savings add up. The share is of the top statements captured, so it is an upper bound.
HOT_WORKLOAD_SHARE = 0.05

Verdict = Literal["material", "not_material", "undetermined"]


class Materiality(Frozen):
    verdict: Verdict
    reasons: list[str]
    evidence_ids: list[str]
    execution_time_ms: float | None = None
    planning_time_ms: float | None = None
    rows_examined: int | None = None
    largest_seq_scanned_rows: int | None = None
    workload_calls: int | None = None
    workload_time_share: float | None = None


def _num(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _workload(
    evidence: Sequence[Evidence], query_key: str | None
) -> tuple[Evidence, float, float] | None:
    """(matched statement, its total time, total time of all captured statements)."""
    stats = [
        e
        for e in evidence
        if e.kind == "workload_stat" and _num(e.data.get("total_exec_time_ms")) is not None
    ]
    if query_key is None or not stats:
        return None
    total = sum(_num(e.data["total_exec_time_ms"]) or 0.0 for e in stats)
    for e in stats:
        text = e.data.get("query")
        if isinstance(text, str) and match_key(text) == query_key:
            return e, _num(e.data["total_exec_time_ms"]) or 0.0, total
    return None


def assess_materiality(
    evidence: Sequence[Evidence], *, query_key: str | None = None
) -> Materiality:
    ordered = sorted({e.id: e for e in evidence}.values(), key=lambda e: (e.kind, e.locator))
    summary = next((e for e in ordered if e.kind == "plan_summary"), None)
    scans = [e for e in ordered if e.kind == "plan_node" and e.data.get("relation") is not None]
    table_rows = {
        str(e.data.get("table")).rsplit(".", 1)[-1].strip('"'): rows
        for e in ordered
        if e.kind == "table_stat" and (rows := _num(e.data.get("estimated_rows"))) is not None
    }

    cited: list[str] = []
    workload = _workload(ordered, query_key)
    calls = share = None
    if workload is not None:
        stat, mine, total = workload
        calls = int(_num(stat.data.get("calls")) or 0)
        share = mine / total if total > 0 else 0.0
        cited.append(stat.id)
        if share >= HOT_WORKLOAD_SHARE:
            return Materiality(
                verdict="material",
                reasons=[
                    f"The query ran {calls:,} times and used {share:.0%} of the captured "
                    "statement time: small per-call savings add up."
                ],
                evidence_ids=cited,
                workload_calls=calls,
                workload_time_share=share,
            )

    exec_ms = _num(summary.data.get("execution_time_ms")) if summary else None
    plan_ms = _num(summary.data.get("planning_time_ms")) if summary else None
    if summary is None or summary.data.get("analyzed") is not True or exec_ms is None:
        return Materiality(
            verdict="undetermined",
            reasons=["No measured execution time (estimates only), so materiality is unknown."],
            evidence_ids=cited,
            workload_calls=calls,
            workload_time_share=share,
        )
    cited.insert(0, summary.id)

    rows = 0
    seq_rows = 0.0
    for e in scans:
        actual = _num(e.data.get("actual_rows")) or 0.0
        loops = _num(e.data.get("loops")) or 1.0
        removed = _num(e.data.get("rows_removed_by_filter_total")) or 0.0
        read = actual * loops + removed
        rows += int(read)
        if e.data.get("node_type") in ("Seq Scan", "Parallel Seq Scan"):
            relation = str(e.data.get("relation"))
            seq_rows = max(seq_rows, read, table_rows.get(relation, 0.0))
        cited.append(e.id)
    stats_ids = [e.id for e in ordered if e.kind == "table_stat"]
    spilled = [e.id for e in ordered if e.kind == "plan_node" and e.data.get("sort_spilled")]
    measured = Materiality(
        verdict="undetermined",
        reasons=[],
        evidence_ids=[],
        execution_time_ms=exec_ms,
        planning_time_ms=plan_ms,
        rows_examined=rows,
        largest_seq_scanned_rows=int(seq_rows),
        workload_calls=calls,
        workload_time_share=share,
    )

    if spilled:
        return measured.model_copy(
            update={
                "verdict": "material",
                "reasons": ["A sort or hash spilled to disk."],
                "evidence_ids": [*cited, *spilled],
            }
        )
    if rows > SMALL_WORK_ROWS:
        return measured.model_copy(
            update={
                "verdict": "material",
                "reasons": [
                    f"Scans read {rows:,} rows: there is work a better access path can cut."
                ],
                "evidence_ids": cited,
            }
        )
    if seq_rows > SMALL_WORK_ROWS:
        return measured.model_copy(
            update={
                "reasons": [
                    f"The plan read {rows:,} rows, but a Seq-Scanned table holds ~{seq_rows:,.0f}"
                    " rows; its cost grows with the table."
                ],
                "evidence_ids": [*cited, *stats_ids],
            }
        )
    if plan_ms is None or exec_ms > plan_ms:
        return measured.model_copy(
            update={
                "reasons": [
                    f"Little data ({rows:,} rows), but execution ({exec_ms:.3f} ms) is not "
                    "below the query's fixed overhead, so a saving cannot be ruled out."
                ],
                "evidence_ids": cited,
            }
        )
    reasons = [
        f"Scans read only {rows:,} rows in total"
        + (f" (largest Seq-Scanned table ~{seq_rows:,.0f} rows)" if seq_rows else "")
        + ": an index cannot save meaningful work at this size.",
        f"Execution took {exec_ms:.3f} ms, less than the {plan_ms:.3f} ms spent planning: "
        "the remaining cost is fixed overhead that no plan change removes.",
    ]
    if calls is not None and share is not None:
        reasons.append(f"It ran {calls:,} times, {share:.1%} of the captured statement time.")
    return measured.model_copy(
        update={
            "verdict": "not_material",
            "reasons": reasons,
            "evidence_ids": [*cited, *stats_ids],
        }
    )


def gate_hypotheses(hypotheses: Sequence[Hypothesis], m: Materiality) -> list[Hypothesis]:
    """When nothing material is at stake, every hypothesis stays visible but is capped at low
    confidence, explains why, and cites the materiality evidence as contradicting it."""
    if m.verdict != "not_material":
        return list(hypotheses)
    low: Confidence = "low"
    gated = []
    for h in hypotheses:
        note = "Not worth optimizing (materiality check): " + " ".join(m.reasons)
        if h.confidence != low:
            note += f" Confidence capped from {h.confidence} to low."
        notes = f"{h.uncertainty_notes} {note}".strip()
        gated.append(
            h.model_copy(
                update={
                    "confidence": low,
                    "uncertainty_notes": notes[:1000],
                    "contradicting_evidence": list(
                        dict.fromkeys([*h.contradicting_evidence, *m.evidence_ids])
                    ),
                }
            )
        )
    return gated
