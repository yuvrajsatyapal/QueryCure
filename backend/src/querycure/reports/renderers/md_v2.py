"""report-md@2 (REPLAY_ENGINE §7): report JSON (schema 2) → Markdown.

Pure and deterministic. Reuses the frozen `report-md@1` section functions; only the version
line differs for ordinary runs. An experiment replay gets its own header label, an
"Experiment Replay Result" section, and a recommendation section that shows the source run's
candidate as the *original* recommendation, never as one this replay made. The replay's own
best arm appears only as a labelled measurement. Every line with a number carries one of
`PROVENANCE_LABELS` (shared with `report-md@1`).
"""

from typing import Any

from querycure.reports.renderers import md_v1
from querycure.reports.renderers.md_v1 import DASH, PROVENANCE_LABELS, _code, _label, _x

MD_RENDERER_VERSION = "report-md@2"
SUPPORTED_SCHEMAS = (2,)
__all__ = ["MD_RENDERER_VERSION", "PROVENANCE_LABELS", "render_markdown"]

_YES_NO = {True: "yes", False: "no", None: "not determined"}


def _footer(r: dict[str, Any]) -> list[str]:
    old = f"rendered by {_code(md_v1.MD_RENDERER_VERSION)}"
    new = f"rendered by {_code(MD_RENDERER_VERSION)}"
    return [line.replace(old, new) for line in md_v1._footer(r)]


def _header(r: dict[str, Any]) -> list[str]:
    lines = md_v1._header(r)
    rr = r["replay_result"]
    title, headline = rr["title"], r["headline"]
    rest = headline[len(title) :].lstrip(":. ") if headline.startswith(title) else headline
    lines[2] = f"> **{title}.** {rest[:1].upper()}{rest[1:]}"
    return lines


def _result(r: dict[str, Any]) -> list[str]:
    rr = r["replay_result"]
    src, replay_of = rr["source"], (r["replay"] or {}).get("replay_of") or {}
    lines = ["", "## Experiment Replay Result"]
    experiment = (src or {}).get("experiment_id") or replay_of.get("experiment_id")
    run = (src or {}).get("run_id") or replay_of.get("run_id")
    kind = f"{src['run_kind']}, " if src else ""
    lines.append(
        f"- What was replayed: experiment {_code(experiment)} of source run {_code(run)} "
        f"({kind}recorded), re-measured in a new sandbox with the same configuration and seed; "
        "no language-model calls."
    )
    if src:
        lines.append(
            f"- Source investigation (recorded): final status {_code(src['final_status'])}, "
            f"outcome {_code(src['outcome'])}, sealed by {_code(src['builder_version'])}; "
            f"manifest {_code('sha256:' + src['manifest_sha256'])}, report "
            f"{_code('sha256:' + src['report_json_sha256'])}."
        )
    else:
        lines.append("- Source investigation: not available; no source snapshot was read.")
    if rr["snapshot_error"]:
        lines.append(f"- Source snapshot error (recorded): {rr['snapshot_error']}.")
    if rr["comparison_status"] is None:
        lines.append("- Comparison: none recorded.")
    else:
        lines.append(
            f"- Comparison: **{rr['comparison_status']}** ({_code(rr['comparison_mode'])})"
            + (
                f", code {_code(rr['comparison_failure_code'])}"
                if rr["comparison_failure_code"]
                else ""
            )
            + " (derived)."
        )
    if rr["margin"]:
        lines.append(
            f"- Equivalence margin: drift interval within {_x(1 / rr['margin'])}{DASH}"
            f"{_x(rr['margin'])} (configured)."
        )
    lines += [
        f"- Correctness reproduced: {_YES_NO[rr['correctness_reproduced']]} (derived).",
        f"- Performance reproduced: {_YES_NO[rr['performance_reproduced']]} (derived).",
        f"- Material drift: {_YES_NO[rr['material_drift']]} (derived).",
    ]
    comparable = _YES_NO[rr["environment_comparable"]]
    if rr["material_differences"]:
        comparable += ", material differences " + ", ".join(
            _code(f) for f in rr["material_differences"]
        )
    lines.append(f"- Environments comparable: {comparable} (derived).")
    match = rr["experiment_match"]["matches"]
    lines.append(
        "- Matching experiment: "
        + {
            True: "the original recommendation was measured by this experiment",
            False: "the original recommendation was measured by a different experiment",
            None: "no measured original recommendation to match",
        }[match]
        + " (recorded)."
    )
    what = (
        "Original no-action conclusion reproduced"
        if (src or {}).get("outcome") == "no_action_needed"
        else "Original recommendation reproduced"
    )
    lines.append(f"- {what}: {_YES_NO[rr['original_reproduced']]} (derived).")
    basis = rr["basis"]
    lines.append(
        "- Classification basis: "
        + ("not recorded" if basis is None else _code(basis["code"]))
        + " (recorded)."
    )
    lines.append(f"- Why: {rr['explanation']}")
    winner = rr["replay_measurement"]["engine_winner"]
    if winner:
        lines.append(
            f"- Replay's own best arm: {_code(winner)} "
            f"({rr['replay_measurement']['provenance'] or 'recorded'}): "
            f"{rr['replay_measurement']['label']}."
        )
    else:
        lines.append("- Replay's own best arm: none (recorded).")
    return lines


def _recommendation(r: dict[str, Any]) -> list[str]:
    rec, rr = r["recommendation"], r["replay_result"]
    if rec["origin"] == "source_run":
        lines = [
            "",
            "## Original recommendation",
            f"From source run {_code(rec['source_run_id'])} (recorded): "
            f"{_code(rec['candidate_key'])} ({rec['kind']}), "
            f"**{md_v1.VERDICT_LABELS[rec['status']]}** in the sandbox by the source "
            "investigation and reproduced by this replay. Review it before applying it.",
        ]
        sql = rec["ddl"] or ([rec["query_sql"]] if rec["query_sql"] else [])
        lines += ["```sql", *sql, "```"]
        m = rec["primary_measurement"]
        if m:
            lines.append(
                f"Primary parameter set {_code(m['param_set'])} (source run): speed-up "
                f"{_x(m['speedup'])} (interval {_x(m['ci_low'])}{DASH}{_x(m['ci_high'])}; "
                f"{_label(m['provenance'], m['evidence_id'])})."
            )
        return lines
    lines = ["", "## Recommendation", "This replay makes no recommendation of its own."]
    src = rr["source_recommendation"]
    if src:
        lines.append(
            f"The source investigation's recommendation {_code(src['candidate_key'])} "
            f"({md_v1.VERDICT_LABELS.get(src['status'], src['status'])}, recorded) is shown "
            "for reference and is not confirmed by this replay."
        )
    return lines


def _comparison(r: dict[str, Any]) -> list[str]:
    lines = md_v1._replay(r)
    if lines:
        lines[1] = "## Comparison with the original"
    return lines


def _measurement(r: dict[str, Any]) -> list[str]:
    if not r["rounds"]:
        return []
    lines = [
        "",
        "## Replay measurement",
        "These are the replay's own sandbox measurements: a single re-measurement, not a "
        "verification.",
    ]
    for rnd in r["rounds"]:
        lines += md_v1._round(rnd)
    return lines


def render_markdown(r: dict[str, Any]) -> str:
    if r.get("schema_version") not in SUPPORTED_SCHEMAS:
        raise ValueError(f"report-md@2 renders report schema 2, not {r.get('schema_version')}")
    if "replay_result" not in r:
        lines = [*md_v1._header(r), *md_v1._query(r), *md_v1._problem(r), *md_v1._hypotheses(r)]
        if r["rounds"]:
            lines += ["", "## Optimizations, approvals and benchmarks"]
            for rnd in r["rounds"]:
                lines += md_v1._round(rnd)
        lines += [*md_v1._recommendation(r), *md_v1._replay(r), *_footer(r), ""]
        return "\n".join(lines)
    lines = [*_header(r), *md_v1._query(r)]
    if r["problem"]["evidence"] or r["problem"]["materiality"]:
        lines += md_v1._problem(r)
    if r["hypotheses"]:
        lines += md_v1._hypotheses(r)
    lines += [*_measurement(r), *_result(r)]
    lines += [*_recommendation(r), *_comparison(r), *_footer(r), ""]
    return "\n".join(lines)
