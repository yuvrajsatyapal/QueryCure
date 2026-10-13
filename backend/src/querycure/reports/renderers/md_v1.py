"""report-md@1 (REPLAY_ENGINE §7): report JSON (schema 1) → Markdown. Released; frozen.

Pure and deterministic. Every line that shows a number names where it came from, using one
of the provenance labels in `PROVENANCE_LABELS` (the renderer test scans for unlabeled
numbers). Identifiers, digests and SQL are shown as code so they are never mistaken for
measurements. The manifest digest is not part of the report: exports add it in a footer.
"""

from typing import Any

MD_RENDERER_VERSION = "report-md@1"
TIMES = "\u00d7"  # multiplication sign after a ratio
DASH = "\u2013"  # en dash between interval bounds
PROVENANCE_LABELS = (
    "measured",
    "prerecorded",
    "derived",
    "recorded",
    "configured",
    "imported",
    "agent claim",
    "user input",
)
STATUS_LABELS = {
    "verified_recommendation": "Verified recommendation",
    "unverified_recommendations": "Unverified recommendations",
    "no_action_needed": "No action needed",
    "inconclusive": "Inconclusive",
}
VERDICT_LABELS = {
    "verified": "verified",
    "verified_with_noise_warning": "verified with noise warning",
    "rejected": "rejected",
    "inconclusive": "inconclusive",
}


def _code(value: object) -> str:
    text = str(value).replace("`", "'")
    return f"`{text}`"


def _ms(ns: float | int | None) -> str:
    return "n/a" if ns is None else f"{ns / 1e6:.3f} ms"


def _x(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}{TIMES}"


def _label(provenance: str | None, evidence_id: str | None = None) -> str:
    parts = [provenance or "recorded"]
    if evidence_id:
        parts.append(_code(evidence_id))
    return " · ".join(parts)


def _evidence_line(e: dict[str, Any]) -> str:
    return f"- {_code(e['id'])} ({e['kind']}, {e['provenance']}): {e['summary']}"


def _header(r: dict[str, Any]) -> list[str]:
    inv, run = r["investigation"], r["run"]
    status = STATUS_LABELS.get(r["outcome"] or "", r["final_status"] or "unknown")
    lines = [
        f"# QueryCure report: {inv['title']}",
        "",
        f"> **{status}.** {r['headline']}",
    ]
    if any(rnd["experiment"] for rnd in r["rounds"]):
        lines.append(
            "> Sandbox only: every measurement ran in a disposable copy of a demo database. "
            "Nothing was applied to your database."
        )
    if "prerecorded" in r["provenance"]["measurements"]:
        lines.append("> Contains prerecorded demo measurements: these are not live results.")
    if r["provenance"]["stub_model"]:
        lines.append("> Agent text came from the offline stub model: canned, not a diagnosis.")
    lines += [
        "",
        f"- Run: {_code(run['id'])}, {run['kind']} (run number {run['run_number']}, recorded)",
        f"- Status: {r['final_status']}"
        + (f", outcome {_code(r['outcome'])}" if r["outcome"] else ""),
        f"- Objective (user input): {inv['objective']}",
        f"- Modes: {', '.join(_code(m) for m in inv['modes'])}"
        + (f"; workload {_code(inv['workload_id'])}" if inv["workload_id"] else ""),
        f"- Finalized: {_code(r['finalized_at'])}",
    ]
    if r["partial"]:
        lines.append(
            "- **Partial report**: the run stopped "
            f"({_code(r['stop_reason'] or r['final_status'])}); sections without data are "
            "listed under Missing evidence."
        )
    if r["summary"]:
        lines.append(f"- Summary (agent claim): {r['summary']}")
    return lines


def _query(r: dict[str, Any]) -> list[str]:
    q = r["query"]
    lines = ["", "## Query"]
    if q["sql"] is None:
        return [*lines, "No query was provided."]
    lines += ["```sql", q["sql"].rstrip("\n"), "```", f"Digest {_code(q['sha256'])}."]
    for p in q["param_sets"] or []:
        lines.append(
            f"- Parameter set {_code(p['name'])}: {_code(p['values'])}"
            + (" (edge case)" if p.get("edge_case") else "")
            + " (user input)"
        )
    return lines


def _problem(r: dict[str, Any]) -> list[str]:
    lines = ["", "## Observed problem"]
    m = r["problem"]["materiality"]
    if m:
        lines.append(
            f"- Materiality check: {_code(m['verdict'])} (derived)"
            + (": " + " ".join(m["reasons"]) if m.get("reasons") else "")
        )
    evidence = r["problem"]["evidence"]
    if not evidence:
        lines.append("No plan evidence was collected.")
    lines += [_evidence_line(e) for e in evidence]
    return lines


def _hypotheses(r: dict[str, Any]) -> list[str]:
    lines = ["", "## Hypotheses"]
    if not r["hypotheses"]:
        return [*lines, "No hypotheses were produced."]
    for h in r["hypotheses"]:
        lines.append(
            f"- {_code(h['key'])} **{h['category']}**, {h['confidence']} confidence "
            f"(agent claim, cites {', '.join(_code(i) for i in h['supporting_evidence'])}): "
            f"{h['statement']}"
        )
    if r["findings"]:
        lines += ["", "### Findings"]
        for f in r["findings"]:
            lines.append(
                f"- [{f['agent']}] {f['severity']}: {f['title']}: {f['detail']} "
                f"(agent claim, cites {', '.join(_code(i) for i in f['evidence_ids'])})"
            )
    return lines


def _measurement_rows(exp: dict[str, Any]) -> list[str]:
    rows = [
        "Intervals are 95% bootstrap confidence intervals of the ratio of medians (derived "
        "from the measured samples).",
        "",
        "| Candidate | Parameter set | Baseline median | Candidate median | Speed-up "
        "(interval) | Samples | Source |",
        "|---|---|---|---|---|---|---|",
    ]
    for m in exp["measurements"]:
        rows.append(
            f"| {_code(m['arm'])} | {_code(m['param_set'])} | {_ms(m['baseline']['median_ns'])} "
            f"| {_ms(m['candidate']['median_ns'])} | {_x(m['speedup'])} "
            f"({_x(m['ci_low'])}{DASH}{_x(m['ci_high'])}) "
            f"| {m['baseline']['n']} / {m['candidate']['n']} "
            f"| {_label(m['provenance'], m['evidence_id'])} |"
        )
    return rows


def _round(rnd: dict[str, Any]) -> list[str]:
    lines = ["", f"### Round {rnd['round'] + 1}"]
    a = rnd["approval"]
    if a is None:
        lines.append("- No approval was requested.")
    else:
        who = f" by {_code(a['decided_by'])}" if a["decided_by"] else ""
        when = f" at {_code(a['decided_at'])}" if a["decided_at"] else ""
        lines.append(f"- Approval: **{a['status']}**{who}{when}.")
    for c in rnd["candidates"]:
        reasons = ", ".join(_code(x["code"]) for x in c["reasons"])
        lines.append(
            f"- {_code(c['key'])} {c['kind']}: **{VERDICT_LABELS.get(c['status'], c['status'])}**"
            + (f" ({reasons})" if reasons else "")
        )
        sql = c["ddl"] or ([c["query_sql"]] if c["query_sql"] else [])
        lines += ["  ```sql", *(f"  {s}" for s in sql), "  ```"]
        lines.append(f"  Expected benefit (agent claim): {c['expected_benefit']}")
    exp = rnd["experiment"]
    if exp is None:
        lines.append("- Not benchmarked.")
        return lines
    env = exp["environment"]
    lines.append(
        f"- Experiment {_code(exp['id'])}: {exp['status']}, engine {_code(exp['engine_version'])}"
        f", seed {_code(exp['seed'])}, samples {exp['provenance'] or 'none'}."
    )
    if exp["error_code"]:
        lines.append(f"- Experiment error: {_code(exp['error_code'])}.")
    if env["digest"]:
        lines.append(
            f"- Environment (recorded): PostgreSQL {_code(env['pg_version'])}, "
            f"{env['cpu_arch']}, {env['cpu_count']} CPUs, {_code(env['container_runtime'])}; "
            f"digest {_code(env['digest'])}."
        )
    if exp["config"]:
        cfg = exp["config"]
        lines.append(
            f"- Rules (configured): {cfg['measured_runs']} measured runs per arm and set, "
            f"required effect {_x(cfg['min_effect'])}, regression limit "
            f"{_x(cfg['max_regression'])}, robust CV limit {cfg['max_cv']}."
        )
    for b in exp["builds"]:
        lines.append(
            f"- Build {_code(b['arm'])}: {'applied' if b['ok'] else 'failed'}"
            + (f" ({_code(b['reason'])})" if b["reason"] else "")
            + f", index size {b['index_size_bytes']} bytes, build {_ms(b['build_ns'])} "
            f"({b['provenance']})."
        )
    if exp["measurements"]:
        lines += ["", *_measurement_rows(exp), ""]
    for v in exp["verdicts"]:
        reasons = "; ".join(f"{x['code']}: {x['detail']}" for x in v["reasons"])
        lines.append(
            f"- Engine verdict {_code(v['arm'])}: **{v['verdict']}**"
            + (f" — {reasons}" if reasons else "")
            + " (derived)"
        )
    for c in exp["correctness"]:
        same = {True: "same rows as", False: "different rows than", None: "not comparable with"}
        lines.append(
            f"- Correctness {_code(c['arm'])} on {_code(c['param_set'])}: "
            f"{same[c['same_rows']]} the baseline ({c['rows']} vs {c['baseline_rows']} rows; "
            f"{_label(c['provenance'], c['evidence_id'])})."
        )
    if exp["replication"]:
        rep = exp["replication"]
        for v in rep["verdicts"]:
            span = (
                f", interval range {_x(v['ci_low'])}{DASH}{_x(v['ci_high'])} across experiments"
                if v["ci_low"] is not None and v["ci_high"] is not None
                else ""
            )
            lines.append(
                f"- Replication {_code(v['arm'])}: **{VERDICT_LABELS[v['verdict']]}** over "
                f"{len(v['experiment_ids'])} independent experiments{span} (derived)."
            )
    for audit in exp["audit"]:
        lines += _audit(audit)
    return lines


def _audit(a: dict[str, Any]) -> list[str]:
    change = (
        f"{VERDICT_LABELS[a['engine_verdict']]} → **{VERDICT_LABELS[a['verdict']]}** "
        "(downgraded by the auditor)"
        if a["downgraded"]
        else f"**{VERDICT_LABELS[a['verdict']]}** (unchanged)"
    )
    lines = [f"- Audit {_code(a['arm'])}: {change}; review {a['auditor_status']}."]
    for c in a["checks"]:
        lines.append(f"  - {c['name']}: {c['status']} — {c['detail']} (derived)")
    for c in a["concerns"]:
        lines.append(
            f"  - Concern, {c['severity']} (agent claim, cites "
            f"{', '.join(_code(i) for i in c['evidence_ids'])}): {c['text']}"
        )
    if a["notes"]:
        lines.append(f"  - Auditor notes (agent claim): {a['notes']}")
    return lines


def _recommendation(r: dict[str, Any]) -> list[str]:
    rec = r["recommendation"]
    lines = ["", "## Recommendation"]
    if rec["candidate_key"] is None:
        text = {
            "unverified": "No change is recommended as verified. The hypotheses and candidates "
            "above are unverified.",
            "none": "No change is recommended.",
        }[rec["status"]]
        return [*lines, text]
    lines.append(
        f"Apply {_code(rec['candidate_key'])} ({rec['kind']}) after your own review: "
        f"**{VERDICT_LABELS[rec['status']]}** in the sandbox."
    )
    sql = rec["ddl"] or ([rec["query_sql"]] if rec["query_sql"] else [])
    lines += ["```sql", *sql, "```"]
    m = rec["primary_measurement"]
    if m:
        lines.append(
            f"Primary parameter set {_code(m['param_set'])}: speed-up {_x(m['speedup'])} "
            f"(interval {_x(m['ci_low'])}{DASH}{_x(m['ci_high'])}; "
            f"{_label(m['provenance'], m['evidence_id'])})."
        )
    return lines


def _replay(r: dict[str, Any]) -> list[str]:
    replay = r["replay"]
    if replay is None:
        return []
    lines = ["", "## Experiment replay"]
    src = replay["replay_of"] or {}
    lines.append(
        f"- Re-measured experiment {_code(src.get('experiment_id'))} of run "
        f"{_code(src.get('run_id'))} with the same configuration and seed (no LLM calls)."
    )
    cmp = replay["comparison"]
    if cmp is None:
        return [*lines, "- No comparison was recorded."]
    lines.append(
        f"- Comparison: **{cmp['status']}** ({_code(cmp['comparison_mode'])})"
        + (f", code {_code(cmp['failure_code'])}" if cmp.get("failure_code") else "")
        + " (derived)."
    )
    for p in cmp["pairs"]:
        lines.append(
            f"  - {_code(p['arm'])} on {_code(p['param_set'])}: {p['status']}"
            + (f" ({_code(p['code'])})" if p.get("code") else "")
            + f", speed-up {_x(p['original_speedup'])} → {_x(p['replay_speedup'])}, drift "
            f"interval {_x(p['drift_ci_low'])}{DASH}{_x(p['drift_ci_high'])} (derived)."
        )
    for d in cmp["environment"]["differences"]:
        lines.append(
            f"  - Environment {d['class']} difference {_code(d['field'])}: "
            f"{_code(d['original'])} → {_code(d['replay'])}."
        )
    return lines


def _footer(r: dict[str, Any]) -> list[str]:
    lines = ["", "## Limitations"]
    lines += [f"- {x}" for x in r["limitations"]]
    lines += ["", "## Next steps"]
    lines += [f"- {x}" for x in r["next_steps"]]
    if r["missing"]:
        lines += ["", "## Missing evidence"]
        lines += [f"- {_code(m['section'])}: {m['reason']}" for m in r["missing"]]
    if r["errors"]:
        lines += ["", "## Errors"]
        lines += [
            f"- {_code(e.get('node'))}: {_code(e.get('code'))} — {e.get('message', '')} (recorded)"
            for e in r["errors"]
        ]
    lines += ["", "## Provenance"]
    for c in r["provenance"]["llm"]:
        lines.append(
            f"- {_code(c['agent'])}: model {_code(c['model'])}, prompt "
            f"{_code(c['prompt_version'])}, {c['status']}, {c['calls']} call(s) (recorded)"
        )
    if not r["provenance"]["llm"]:
        lines.append("- No language-model calls were made for this run (recorded).")
    usage = r["usage"] or {}
    if usage:
        lines.append(
            "- Usage: " + ", ".join(f"{k} {usage[k]}" for k in sorted(usage)) + " (recorded)"
        )
    ev = r["events"]
    lines += [
        f"- Events sealed through sequence {ev['cutoff_seq']}, digest {_code(ev['digest'])} "
        f"({_code(ev['profile'])}, recorded).",
        f"- Built by {_code(r['builder_version'])}, rendered by {_code(MD_RENDERER_VERSION)}, "
        f"report schema {r['schema_version']} (recorded).",
        "- Integrity checks compare stored records with stored digests; they show "
        "consistency, not authenticity.",
    ]
    if r["evidence"]:
        lines += ["", "## Evidence cited"]
        lines += [_evidence_line(e) for e in r["evidence"]]
    return lines


def render_markdown(r: dict[str, Any]) -> str:
    lines = [*_header(r), *_query(r), *_problem(r), *_hypotheses(r)]
    if r["rounds"]:
        lines += ["", "## Optimizations, approvals and benchmarks"]
        for rnd in r["rounds"]:
            lines += _round(rnd)
    lines += [*_recommendation(r), *_replay(r), *_footer(r), ""]
    return "\n".join(lines)
