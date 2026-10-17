"""Deterministic checks on the Optimization Engineer's proposals (AGENT_SYSTEM §2, SECURITY §6).

The model proposes; this module disposes. A candidate survives only if it addresses known
hypotheses, passes the sandbox DDL allowlist / SELECT validator for its kind, and is not a
repeat of a candidate already proposed in this run (same SQL digest). More than half removed
triggers the agent runner's single retry with the problems listed, like uncited claims.
"""

import uuid
from collections.abc import Collection, Mapping

from querycure.agents.citations import CitationReport
from querycure.agents.claims import ClaimContext, filter_text
from querycure.agents.outputs import CandidateDraft, CandidateSet
from querycure.benchmark.engine import sql_digest
from querycure.core.errors import QueryCureError
from querycure.domain.benchmark import CandidateArm
from querycure.domain.optimization import CandidateCost, OptimizationCandidate
from querycure.evidence.ids import keyed_id
from querycure.evidence.sanitize import clean_text
from querycure.sql.ddl_allowlist import validate_candidate


def arm_of(draft: CandidateDraft, key: str = "oc_000000000000") -> CandidateArm:
    return CandidateArm(
        arm=key,
        candidate_id=None,
        kind=draft.kind,
        ddl=[s.strip().rstrip(";").strip() for s in draft.ddl],
        query=draft.query.strip() if draft.query else None,
        write_overhead=draft.write_overhead,
    )


def judge_candidates(
    output: CandidateSet,
    *,
    baseline: str,
    hypothesis_keys: Collection[str],
    seen_digests: Collection[str],
    max_candidates: int,
    claims: ClaimContext | None = None,
) -> tuple[CandidateSet, CitationReport]:
    kept: list[CandidateDraft] = []
    problems: list[str] = []
    claim_problems: list[str] = []

    def ground(text: str) -> str:
        # Prose only: the SQL decides what is measured, the benchmark decides the verdict.
        if claims is None or not text:
            return text
        out = filter_text(text, claims)
        claim_problems.extend(out.problems)
        return out.text

    removed = 0
    digests = set(seen_digests)
    for index, draft in enumerate(output.candidates):
        label = f"candidate {index + 1} ({draft.kind})"
        valid_keys = [k for k in dict.fromkeys(draft.addresses_hypotheses) if k in hypothesis_keys]
        unknown = [k for k in draft.addresses_hypotheses if k not in hypothesis_keys]
        if unknown:
            problems.append(
                f"{label} addresses unknown hypotheses: "
                + ", ".join(clean_text(k, 20) for k in unknown[:4])
            )
        if not valid_keys:
            problems.append(f"{label} must address at least one listed hypothesis key")
            removed += 1
            continue
        arm = arm_of(draft)
        try:
            validate_candidate(kind=arm.kind, ddl=arm.ddl, query=arm.query, baseline=baseline)
        except QueryCureError as exc:
            problems.append(
                f"{label} rejected by the sandbox policy: {clean_text(exc.message, 200)}"
            )
            removed += 1
            continue
        digest = sql_digest(arm)
        if digest in digests:
            problems.append(f"{label} repeats a candidate already proposed in this run")
            removed += 1
            continue
        if len(kept) >= max_candidates:
            problems.append(f"{label} dropped: at most {max_candidates} candidates per round")
            continue
        digests.add(digest)
        kept.append(
            draft.model_copy(
                update={
                    "addresses_hypotheses": valid_keys,
                    "ddl": arm.ddl,
                    "query": arm.query,
                    "expected_benefit": ground(clean_text(draft.expected_benefit, 500)),
                    "risks": [g for r in draft.risks if (g := ground(clean_text(r, 200)))],
                }
            )
        )
    summary = ground(output.summary)
    report = CitationReport(
        total=len(output.candidates),
        removed=removed,
        stripped_ids=0,
        problems=problems,
        claim_problems=claim_problems,
    )
    return output.model_copy(update={"candidates": kept, "summary": summary}), report


def to_candidates(
    run_id: uuid.UUID, round: int, output: CandidateSet
) -> list[OptimizationCandidate]:
    """Keys depend on run, round and position only, so a reused output maps to the same rows."""
    result: list[OptimizationCandidate] = []
    for index, draft in enumerate(output.candidates):
        key = keyed_id("oc", run_id, round, index)
        arm = arm_of(draft, key)
        result.append(
            OptimizationCandidate(
                key=key,
                round=round,
                kind=draft.kind,
                addresses_hypotheses=draft.addresses_hypotheses,
                ddl=arm.ddl,
                query_sql=arm.query,
                sql_sha256=sql_digest(arm),
                rollback_sql=None,  # sandbox clones are dropped; production rollout is Phase 4
                expected_benefit=draft.expected_benefit or "Not stated.",
                risks=draft.risks,
                estimated_cost=CandidateCost(write_overhead=draft.write_overhead),
            )
        )
    return result


def candidate_arm(candidate: OptimizationCandidate) -> CandidateArm:
    return CandidateArm(
        arm=candidate.key,
        candidate_id=candidate.id,
        kind=candidate.kind,
        ddl=list(candidate.ddl),
        query=candidate.query_sql,
        write_overhead=candidate.estimated_cost.write_overhead,
    )


def rejection_lines(
    candidates: list[OptimizationCandidate], verdicts: Mapping[str, list[dict[str, str]]]
) -> list[str]:
    """Earlier rounds' verdicts, fed back to the next round (BENCHMARK_ENGINE §8)."""
    lines = []
    for c in candidates:
        reasons = verdicts.get(c.key) or c.verdict_reasons or []
        codes = ", ".join(f"{r.get('code')}: {r.get('detail', '')}" for r in reasons) or "none"
        change = " ; ".join(c.ddl) if c.ddl else (c.query_sql or "")
        lines.append(f"- {c.key} [{c.kind}] status={c.status} reasons={codes} sql={change}")
    return lines
