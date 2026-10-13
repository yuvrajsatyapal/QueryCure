"""report-builder@1 (REPLAY_ENGINE §7): persisted records → report JSON. Released; frozen.

A pure function of `ReportInputs` plus the finalization values (`finalized_at`, cutoff,
events digest). It reads no clock and no database, sorts every collection by a stable key, and
emits every field of report schema 1, so a rebuild from the same records is byte-identical.

Every quantitative value in the report sits in an object that names its provenance
(`measured`, `prerecorded`, `derived`, `recorded`, `configured`) and, for measurements, the
evidence ID and the artifact digest + JSON pointer it came from.
"""

import uuid
from typing import Any

from querycure.domain.investigation import Evidence
from querycure.evidence.ids import evidence_id
from querycure.reports.inputs import ReportInputs

BUILDER_VERSION = "report-builder@1"
REPORT_SCHEMA_VERSION = 1
VERIFIED = ("verified", "verified_with_noise_warning")

HEADLINES = {
    "verified_recommendation": (
        "A candidate change was verified in an isolated sandbox: faster, with the same result "
        "rows, on every tested parameter set."
    ),
    "unverified_recommendations": (
        "Hypotheses or candidate changes were produced, but none was verified by measurement."
    ),
    "no_action_needed": (
        "No optimization appears worth making for this query, based on the cited evidence."
    ),
    "inconclusive": "The investigation could not reach a verified conclusion.",
}
NOISE_HEADLINE = (
    "A candidate change was verified with a noise warning: individual measurements were noisy, "
    "and the speed-up was confirmed only by agreement across three independent sandbox "
    "experiments."
)
REASON_TEXT = {
    "insufficient_evidence": "too few samples, or measurements too noisy to decide",
    "effect_not_significant": "the measured speed-up is smaller than the required effect",
    "unstable_execution": "too many executions timed out or failed",
    "nondeterministic_order": "the query's own results varied between executions",
    "result_too_large": "the result was too large to compare completely",
    "replicates_disagree": "independent re-measurements did not agree",
    "regression": "the candidate made at least one parameter set slower",
    "result_mismatch": "the candidate returned different rows than the original query",
    "no_improvement": "the candidate was not faster",
    "ddl_failed": "the change could not be applied in the sandbox",
    "constraint_violation": "the change exceeded the configured size or build-time limits",
    "not_measured": "the candidate was not measured",
    "audit_downgrade": "the Benchmark Auditor found a reason to doubt the result",
    "approval_declined": "a human declined the change",
    "approval_expired": "the approval request expired",
    "experiment_failed": "the sandbox experiment failed",
}


def _ev(e: Evidence) -> dict[str, Any]:
    return {
        "id": e.id,
        "kind": e.kind,
        "summary": e.summary,
        "provenance": e.provenance,
        "artifact_sha256": e.artifact_sha256,
        "locator": e.locator,
    }


def _latency(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "n": summary["n"],
        "median_ns": summary["median_ns"],
        "p95_ns": summary["p95_ns"],
        "robust_cv": summary["robust_cv"],
    }


def _experiment(
    run_id: str, e: dict[str, Any], by_id: dict[str, Evidence], verifications: list[dict[str, Any]]
) -> dict[str, Any]:
    result, sha = e["result"], e["result_sha256"]
    provenance = result["provenance"] if result else None
    measurements, correctness, builds = [], [], []
    if result:
        rid = uuid.UUID(run_id)
        for i, s in enumerate(result["stats"]):
            locator = f"/stats/{s['arm']}/{s['param_set']}"
            eid = evidence_id(rid, "benchmark_metric", sha, locator)
            measurements.append(
                {
                    "arm": s["arm"],
                    "param_set": s["param_set"],
                    "baseline": _latency(s["baseline"]),
                    "candidate": _latency(s["candidate"]),
                    "speedup": s["speedup"],
                    "ci_low": s["ci_low"],
                    "ci_high": s["ci_high"],
                    "provenance": provenance,
                    "evidence_id": eid if eid in by_id else None,
                    "source": {"artifact_sha256": sha, "pointer": f"/stats/{i}"},
                }
            )
        by = {(m["arm"], m["param_set"]): m for m in result["measurements"]}
        for (arm, ps), m in sorted(by.items()):
            if arm == "baseline":
                continue
            base = by.get(("baseline", ps))
            fp, bfp = m["fingerprint"], (base or {}).get("fingerprint")
            eid = evidence_id(rid, "correctness_check", sha, f"/correctness/{arm}/{ps}")
            correctness.append(
                {
                    "arm": arm,
                    "param_set": ps,
                    "same_rows": None
                    if fp is None or bfp is None
                    else (fp["rows"], fp["multiset"]) == (bfp["rows"], bfp["multiset"]),
                    "rows": None if fp is None else fp["rows"],
                    "baseline_rows": None if bfp is None else bfp["rows"],
                    "provenance": provenance,
                    "evidence_id": eid if eid in by_id else None,
                }
            )
        builds = [
            {
                "arm": b["arm"],
                "ok": b["ok"],
                "reason": b["reason"],
                "index_size_bytes": b["index_size_bytes"],
                "build_ns": b["build_ns"],
                "provenance": provenance,
            }
            for b in result["builds"]
        ]
    env = e["environment"] or {}
    audits = [
        {
            "arm": v["candidate_key"],
            "engine_verdict": v["engine_verdict"],
            "verdict": v["verdict"],
            "downgraded": v["auditor_downgraded"],
            "auditor_status": v["auditor_status"],
            "prompt_version": v["auditor_prompt_version"],
            "notes": v["auditor_notes"],
            "checks": v["checks"],
            "concerns": v["auditor_concerns"],
        }
        for v in sorted(verifications, key=lambda v: v["candidate_key"])
        if v["experiment_id"] == e["id"]
    ]
    return {
        "id": e["id"],
        "round": e["round"],
        "replicate": e["replicate"],
        "status": e["status"],
        "engine_version": e["engine_version"],
        "row_profile": e["row_profile"],
        "seed": e["seed"],
        "provenance": provenance,
        "result_sha256": sha,
        "error_code": (e["error"] or {}).get("code"),
        "environment": {
            "digest": e["environment_digest"],
            "pg_version": env.get("pg_version"),
            "cpu_arch": env.get("cpu_arch"),
            "cpu_model": env.get("cpu_model"),
            "cpu_count": env.get("cpu_count"),
            "memory_bytes": env.get("memory_bytes"),
            "os": env.get("os"),
            "container_runtime": env.get("container_runtime"),
            "sandbox_image_digest": env.get("sandbox_image_digest"),
            "workload_id": env.get("workload_id"),
            "workload_data_digest": env.get("workload_data_digest"),
            "provenance": "recorded" if env else None,
        },
        "config": None
        if e["config"] is None
        else {
            "measured_runs": e["config"]["measured_runs"],
            "warmup_runs": e["config"]["warmup_runs"],
            "block_size": e["config"]["block_size"],
            "min_effect": e["config"]["min_effect"],
            "max_regression": e["config"]["max_regression"],
            "max_cv": e["config"]["max_cv"],
            "provenance": "configured",
        },
        "builds": builds,
        "verdicts": [] if not result else result["verdicts"],
        "tournament": [] if not result else result["tournament"],
        "winner": None if not result else result["winner"],
        "measurements": measurements,
        "correctness": correctness,
        "replication": e["replication"],
        "audit": audits,
    }


def _winner(rounds: list[dict[str, Any]]) -> dict[str, Any] | None:
    for rnd in rounds:
        status = {c["key"]: c["status"] for c in rnd["candidates"]}
        exp = rnd["experiment"]
        if exp is None:
            continue
        order = [a for a in (exp["winner"], (exp["replication"] or {}).get("winner")) if a]
        order += [t["arm"] for t in exp["tournament"]]
        for arm in order:
            if status.get(arm) in VERIFIED:
                chosen: dict[str, Any] = next(c for c in rnd["candidates"] if c["key"] == arm)
                return {**chosen, "round": rnd["round"]}
    return None


def build_report(
    inputs: ReportInputs, *, finalized_at: str, cutoff_seq: int, events_digest: str
) -> dict[str, Any]:
    run_id = inputs.run["id"]
    conclusion = inputs.conclusion or {}
    final_status = conclusion.get("final_status")
    outcome = conclusion.get("outcome")
    stop_reason = conclusion.get("stop_reason")
    by_id = {e.id: e for e in inputs.evidence}

    hypotheses = [h.model_dump() for h in sorted(inputs.hypotheses, key=lambda h: h.rank)]
    findings = [{"key": k, **f.model_dump()} for k, f in sorted(inputs.findings)]
    materiality = conclusion.get("materiality")
    cited = sorted(
        {i for f in findings for i in f["evidence_ids"]}
        | {i for h in hypotheses for i in h["supporting_evidence"] + h["contradicting_evidence"]}
        | set((materiality or {}).get("evidence_ids", []))
        | set(conclusion.get("no_action_evidence") or [])
    )
    problem = sorted(
        {e.id for e in inputs.evidence if e.kind == "plan_summary"}
        | {i for i in cited if i in by_id and by_id[i].kind in ("plan_node", "plan_summary")}
    )

    approvals = {a["round"]: a for a in inputs.approvals}
    experiments = [
        _experiment(run_id, e, by_id, inputs.verifications)
        for e in sorted(inputs.experiments, key=lambda e: (e["round"], e["replicate"], e["id"]))
    ]
    rounds: list[dict[str, Any]] = []
    for rnd in sorted({c.round for c in inputs.candidates} | {e["round"] for e in experiments}):
        primary = [x for x in experiments if x["round"] == rnd and x["replicate"] == 0]
        approval = approvals.get(rnd)
        rounds.append(
            {
                "round": rnd,
                "approval": approval,
                "candidates": [
                    {
                        "key": c.key,
                        "kind": c.kind,
                        "ddl": list(c.ddl),
                        "query_sql": c.query_sql,
                        "sql_sha256": c.sql_sha256,
                        "addresses_hypotheses": list(c.addresses_hypotheses),
                        "expected_benefit": c.expected_benefit,
                        "risks": list(c.risks),
                        "status": c.status,
                        "reasons": c.verdict_reasons or [],
                    }
                    for c in sorted(inputs.candidates, key=lambda c: c.key)
                    if c.round == rnd
                ],
                "experiment": primary[0] if primary else None,
                "replicates": [x for x in experiments if x["round"] == rnd and x["replicate"] > 0],
            }
        )

    winner = _winner(rounds)
    provenances = sorted({x["provenance"] for x in experiments if x["provenance"]})
    stub = any((c["model"] or "").startswith("stub/") for c in inputs.llm_calls)
    benchmarked = any(x["status"] == "completed" for x in experiments)
    replay = inputs.run["kind"] == "experiment_replay"

    recommendation: dict[str, Any]
    if winner is not None:
        primary_exp = next(r for r in rounds if r["round"] == winner["round"])["experiment"]
        primary_ps = next(
            (m for m in primary_exp["measurements"] if m["arm"] == winner["key"]), None
        )
        recommendation = {
            "status": winner["status"],
            "candidate_key": winner["key"],
            "kind": winner["kind"],
            "ddl": winner["ddl"],
            "query_sql": winner["query_sql"],
            "primary_measurement": primary_ps,
            "scope": "sandbox",
        }
    else:
        recommendation = {
            "status": "unverified" if hypotheses or inputs.candidates else "none",
            "candidate_key": None,
            "kind": None,
            "ddl": [],
            "query_sql": None,
            "primary_measurement": None,
            "scope": "sandbox" if benchmarked else "none",
        }

    limitations: list[str] = []
    if benchmarked:
        limitations += [
            "Measured in a disposable sandbox copy of the demo workload "
            f"`{inputs.investigation['workload_id']}`, not on your database. No change was "
            "applied to any database you own.",
            "Warm cache, one session, interleaved runs: production concurrency, cache state "
            "and data distribution may change the result.",
            "Only the listed parameter sets were tested; other inputs may behave differently. "
            "A sandbox verification is not a guarantee for every workload.",
        ]
        if any(c.kind == "create_index" for c in inputs.candidates):
            limitations.append(
                "Index write overhead on INSERT/UPDATE was not measured; build time and size "
                "are recorded per candidate."
            )
    else:
        limitations.append("Nothing in this report was benchmarked: hypotheses are unverified.")
    if winner is not None and winner["status"] == "verified_with_noise_warning":
        limitations.append(
            "Noise warning: single experiments were too noisy to decide; the result rests on "
            "three agreeing independent experiments. Treat the size of the effect as uncertain."
        )
    if "prerecorded" in provenances:
        limitations.append(
            "Some measurements are prerecorded demo fixtures, not live measurements."
        )
    if stub:
        limitations.append(
            "Agent output came from the offline stub model (canned text for tests); it is not "
            "a diagnosis."
        )
    if any(v["auditor_status"] == "deterministic_only" for v in inputs.verifications):
        limitations.append(
            "The auditor's narrative review was unavailable for at least one experiment; "
            "only its deterministic checks ran."
        )
    if replay:
        limitations.append(
            "This run re-measured an earlier experiment: agreement means consistency in this "
            "pair of runs, not portability."
        )

    reasons = sorted(
        {r["code"] for rnd in rounds for c in rnd["candidates"] for r in c["reasons"]}
        | {
            r["code"]
            for rnd in rounds
            if rnd["experiment"]
            for v in rnd["experiment"]["verdicts"]
            for r in v["reasons"]
        }
    )
    if outcome == "verified_recommendation":
        next_steps = [
            "Review the exact SQL and test it on a staging copy of your own data and workload.",
            "Re-run this experiment (experiment replay) to check the result is reproducible.",
        ]
    elif outcome == "inconclusive":
        next_steps = [
            "Re-run on a quieter host or with more samples; inconclusive is not a rejection."
        ] + [f"Why: {REASON_TEXT[r]}." for r in reasons if r in REASON_TEXT]
    elif outcome == "unverified_recommendations":
        next_steps = ["Benchmark the candidates in the sandbox (Mode C) before acting on them."]
    elif outcome == "no_action_needed":
        next_steps = ["No change recommended; revisit if the data or workload changes."]
    else:
        next_steps = ["The run stopped early; start a new run to complete the investigation."]

    missing = []
    if inputs.query_sql is None:
        missing.append({"section": "query", "reason": "no query was provided"})
    if not hypotheses:
        missing.append({"section": "hypotheses", "reason": "no hypotheses were produced"})
    if not benchmarked:
        missing.append(
            {
                "section": "benchmark",
                "reason": "no experiment completed" if experiments else "not benchmarked",
            }
        )
    if inputs.conclusion is None:
        missing.append({"section": "conclusion", "reason": "no recorded conclusion"})

    headline = HEADLINES.get(outcome or "", "The run ended before reaching a conclusion.")
    if winner is not None and winner["status"] == "verified_with_noise_warning":
        headline = NOISE_HEADLINE

    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "builder_version": BUILDER_VERSION,
        "run": inputs.run,
        "investigation": inputs.investigation,
        "finalized_at": finalized_at,
        "events": {"cutoff_seq": cutoff_seq, "digest": events_digest, "profile": "qc-events-v1"},
        "final_status": final_status,
        "outcome": outcome,
        "stop_reason": stop_reason,
        "partial": stop_reason is not None or final_status != "completed",
        "headline": headline,
        "summary": conclusion.get("synthesis_summary") or "",
        "query": {
            "sql": inputs.query_sql,
            "sha256": inputs.query_sha256,
            "param_sets": inputs.param_sets,
        },
        "problem": {
            "evidence": [_ev(by_id[i]) for i in problem],
            "materiality": materiality,
        },
        "hypotheses": hypotheses,
        "findings": findings,
        "evidence": [_ev(by_id[i]) for i in cited if i in by_id],
        "rounds": rounds,
        "recommendation": recommendation,
        "limitations": limitations,
        "next_steps": next_steps,
        "provenance": {
            "measurements": provenances,
            "stub_model": stub,
            "llm": inputs.llm_calls,
        },
        "replay": None
        if not replay
        else {"replay_of": inputs.replay_of, "comparison": inputs.comparison},
        "missing": missing,
        "errors": inputs.errors,
        "usage": conclusion.get("usage"),
    }
