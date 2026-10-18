"""Evidence-specific claim grounding, `claims@2` (ADR-0028). Supersedes `claims@1` for new runs.

`claims@1` (agents/claims.py, frozen) checks a sentence against every figure the run
recorded, pooled. A speed-up measured for candidate A, on param set X, in experiment E,
therefore also "supports" a sentence about candidate B, param set Y or another experiment.
`claims@2` binds claims to the subjects they name before checking them:

1. A sentence is split into clauses ("…, while …", "…; …", "…, although …"), and each clause
   is resolved to its subjects deterministically:
   - candidate arms, by ID (`oc_…`) or by the action they name (ANALYZE, a rewrite, extended
     statistics, or an index narrowed by its columns and by "composite"/"single-column");
   - param sets, by name;
   - the plan it describes: baseline ("the current plan") or candidate ("with the index").

   A clause naming no subject inherits the sentence's subjects. With no subject at all, the
   pooled check of `claims@1` applies, so unattributed prose behaves as before.
2. The `claims@1` rules then run on a context narrowed to those subjects. The narrowed context
   holds their measurements only: speed-ups, intervals, medians, the replication range of
   their own arm, and their own plans' scan types.
3. New typed claims are extracted and checked:
   - alternative speed-up wordings ("4.7-fold", "a factor of 4.7", "a speed-up of 4.7");
   - percentage reductions, which must equal 1 - 1/speed-up and can never exceed 100%;
   - absolute savings (baseline - candidate);
   - latency transitions ("from 3.62 ms to 0.77 ms"), which must be one measurement;
   - guaranteed improvements;
   - the stated status of a named subject (verified, rejected, inconclusive, or verified
     cleanly when the verdict carries a noise warning);
   - advice against a verified change;
   - estimate direction and accuracy, and "fresh" statistics.

The `claims@1` action rule, which treats any mention of a change as a recommendation, applies
only to clauses that recommend something, so descriptive sentences about an unverified
candidate's measured figures survive. Nothing here calls a model or decides a verdict, and
removal is still the only action.
"""

import dataclasses
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from querycure.agents import claims as v1
from querycure.agents.claims import (
    VERIFIED,
    ActionRef,
    Filtered,
    Mode,
    action_refs,
    index_columns,
    sentences,
    star_projection,
)
from querycure.domain.benchmark import BASELINE_ARM
from querycure.domain.investigation import Evidence

__all__ = [
    "CHECKER_VERSION",
    "VERIFIED",
    "ActionRef",
    "ClaimContext",
    "Filtered",
    "Measurement",
    "Mode",
    "TypedClaim",
    "action_refs",
    "check_sentence",
    "claim_context",
    "extract_claims",
    "filter_text",
    "index_columns",
    "plan_node_types",
    "star_projection",
]

CHECKER_VERSION = "claims@2"
_NUM = r"(?<![\d.])(\d+(?:\.\d+)?)(?!\.?\d)"
_APPROX = r"(?:(?:about|around|roughly|approximately|nearly)\s+|~\s*|≈\s*)?"
_CLAUSE = re.compile(
    r";\s+|,\s+(?=(?:while|whereas|but|although|though|yet|however)\b)"
    r"|\s+(?=(?:while|whereas)\s)",
    re.I,
)
_FOLD = re.compile(
    rf"{_NUM}[- ]fold\b|\bfactor of\s+{_APPROX}{_NUM}"
    rf"|\bspeed-?up\s+(?:of|was|is|reached|=|:)\s*{_APPROX}{_NUM}(?!\s*(?:%|ms\b|x|\xd7|times\b))",
    re.I,
)
_PCT_BY = re.compile(
    rf"\b(reduc\w*|cut\w*|lower\w*|decreas\w*|drop\w*|shr[iu]nk\w*|improv\w*|speed\w*\s+up)"
    rf"\s+(?:[\w-]+\s+){{0,4}}?by\s+{_APPROX}{_NUM}\s*%",
    re.I,
)
_PCT_WORD = re.compile(
    rf"{_NUM}\s*%\s*(faster|quicker|speed-?up|improvement|reduction|decrease|less time|"
    r"lower latency|shorter)",
    re.I,
)
_REDUCTION = re.compile(r"reduc|cut|lower|decreas|drop|shr[iu]nk|less|shorter", re.I)
_SAVING = re.compile(
    rf"(?:\bsav(?:e|es|ed|ing)|\bshav\w*)\s+{_APPROX}{_NUM}\s*(?:ms|milliseconds?)\b"
    rf"|{_NUM}\s*(?:ms|milliseconds?)\s+(?:faster|less|quicker|shorter|saved)\b"
    rf"|\bby\s+{_APPROX}{_NUM}\s*(?:ms|milliseconds?)\b",
    re.I,
)
_TRANSITION = re.compile(
    rf"\bfrom\s+{_APPROX}{_NUM}\s*(?:ms|milliseconds?)?\s+(?:down\s+)?to\s+{_APPROX}{_NUM}\s*"
    rf"(?:ms|milliseconds?)\b|{_NUM}\s*(?:ms|milliseconds?)\s*(?:->|to)\s*{_APPROX}{_NUM}\s*"
    r"(?:ms|milliseconds?)\b",
    re.I,
)
_APPROX_BEFORE = re.compile(r"(?:≈|~|\babout|\baround|\broughly|\bapproximately|\bnearly)\s*$")
_GUARANTEE = re.compile(
    r"\bguarantee[sd]?\b|\bwill always\b|\balways\s+(?:be\s+)?(?:faster|quicker)\b"
    r"|\bcertain(?:ly)?\s+(?:to\s+)?(?:be\s+)?(?:faster|improve)|\bwill definitely\b"
    r"|\bwithout (?:any )?risk\b|\brisk-free\b",
    re.I,
)
_GUARANTEE_DENIED = re.compile(
    r"\b(?:no|not|cannot|can't|never|nor|without|does not|doesn't|isn't)\b[^.;]{0,30}"
    r"\bguarantee|\bnot guaranteed\b",
    re.I,
)
_SAYS_VERIFIED = re.compile(
    r"\b(?:is|was|were|are|been|got)\s+(?:\w+\s+)?(?:verified|confirmed|proven|validated)\b"
    r"|\bverified\s+(?:speed-?ups?|improvements?|gains?|recommendations?|results?|faster)\b",
    re.I,
)
_SAYS_REJECTED = re.compile(
    r"\b(?:is|was|were|are|been|got)\s+(?:\w+\s+)?rejected\b|\bfailed (?:the )?correctness\b"
    r"|\breturn(?:s|ed)? different (?:rows|results)\b",
    re.I,
)
_SAYS_INCONCLUSIVE = re.compile(
    r"\binconclusive\b|\bcould not be (?:verified|confirmed)\b|\bnot (?:statistically )?"
    r"significant\b|\bunverified\b",
    re.I,
)
_ONLY = re.compile(r"\bonly\b|\bjust\b|\balone\b", re.I)
_CLEAN = re.compile(
    r"\bcleanly\b|\bwithout (?:any )?(?:noise|caveats?|warnings?)\b|\bno noise\b"
    r"|\bfully verified\b|\bunambiguously\b",
    re.I,
)
_RECOMMENDS = re.compile(
    r"^\s*(?:create|add|build|run|apply|use|consider|rewrite|replace|adopt|implement|deploy)\b"
    r"|\b(?:recommend\w*|should|suggest\w*|advis\w*|worth|best option|the fix|fix(?:es)? the|"
    r"resolves?|resolving|solution|propose\w*|must)\b",
    re.I,
)
_ADVISES_AGAINST = re.compile(
    r"\b(?:do not|don't|should not|shouldn't|must not|never|avoid)\s+(?:\w+\s+){0,3}?"
    r"(?:create|creating|add|adding|build|building|run|running|apply|applying|use|using|"
    r"rewrit\w+|deploy\w*)\b"
    r"|\bnot (?:recommended|worth|advisable)\b|\badvise against\b|\brecommend against\b",
    re.I,
)
_ALL = re.compile(
    r"\ball (?:the )?(?!other\b|remaining\b)(?:\w+ )?(?:candidates|arms|options|changes)\b"
    r"|\bboth candidates\b",
    re.I,
)
_INDEX_NOUN = re.compile(
    r"\bindex(?:es)?\b(?![- ]?(?:only|scans?|cond\w*|names?|usage|lookups?))", re.I
)
_EXISTING_INDEX = re.compile(r"\b(?:existing|primary[- ]key|pkey|unique)\s+(?:\w+\s+)?index", re.I)
_COMPOSITE = re.compile(r"\b(?:composite|multi-?column|two-column|covering|compound)\b", re.I)
_SINGLE = re.compile(r"\b(?:single|one)[- ]column\b", re.I)
_BASELINE_PLAN = re.compile(
    r"\b(?:baseline|current|original|existing|unoptimi[sz]ed|old)\s+(?:query\s+)?plan\b"
    r"|\bwithout (?:the|any|an) (?:new )?index\b|\bthe baseline\b",
    re.I,
)
_CANDIDATE_PLAN = re.compile(
    r"\b(?:optimi[sz]ed|candidate|new|resulting|improved)\s+(?:query\s+)?plan\b"
    r"|\bwith (?:the|this|that|a|an) (?:new |composite |proposed )?index\b",
    re.I,
)
_DIRECTION = re.compile(r"\b(under|over)-?estimat\w*", re.I)
_ACCURATE_ESTIMATES = re.compile(
    r"\b(?:row |cardinality |planner )?estimates?\s+(?:are|were|is|was)\s+(?:\w+\s+)?"
    r"(?:accurate|correct|good|close|reasonable|fine|right)\b",
    re.I,
)
_FRESH_STATS = re.compile(
    r"\bstat(?:istic)?s\s+(?:are|is|appear|seem|look)\s+(?:\w+\s+)?"
    r"(?:up[- ]to[- ]date|fresh|current|accurate)\b"
    r"|\b(?:fresh|up[- ]to[- ]date|current|accurate)\s+(?:table\s+|planner\s+)?stat(?:istic)?s\b",
    re.I,
)
_SPEED_WORD = re.compile(r"\b(?:faster|quicker|slower|speed)", re.I)
INACCURATE_RATIO = 10.0  # an estimate off by 10x or more is not "accurate"


@dataclass(frozen=True)
class Measurement:
    """One stored speed-up, attributable to exactly one arm, param set and experiment."""

    arm: str
    param_set: str
    experiment: str  # result artifact digest; "replication" for an arm's replicated range
    speedup: float | None
    ci_low: float | None
    ci_high: float | None
    baseline_ms: float | None
    candidate_ms: float | None


@dataclass(frozen=True)
class ClaimContext(v1.ClaimContext):
    measurements: tuple[Measurement, ...] = ()
    candidate_plans: Mapping[str, frozenset[str]] = field(default_factory=dict)
    plan_latencies_ms: tuple[float, ...] = ()  # recorded timings that are not benchmark medians
    estimate_directions: frozenset[str] = frozenset()
    max_estimate_ratio: float | None = None
    param_sets: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypedClaim:
    """A quantitative statement extracted from one clause, before it is checked."""

    kind: str  # speedup | percent | saving | transition
    values: tuple[float, ...]
    text: str
    approximate: bool = False
    reduction: bool = False


@dataclass(frozen=True)
class _Subjects:
    arms: frozenset[str] = frozenset()
    param_sets: frozenset[str] = frozenset()
    plan: str | None = None  # "baseline" | "candidate" | None

    def __bool__(self) -> bool:
        return bool(self.arms or self.param_sets)


def _norm(text: str) -> str:
    return v1._normalize(text).replace("→", "->")


def _clauses(sentence: str) -> list[str]:
    return [c for c in _CLAUSE.split(sentence) if c and c.strip()]


def _index_arms(clause: str, ctx: ClaimContext) -> set[str]:
    refs = [r for r in ctx.actions if r.kind == "create_index"]
    mentioned = [m for m in _INDEX_NOUN.finditer(clause)]
    if not mentioned or (
        all(_EXISTING_INDEX.search(clause[max(0, m.start() - 30) : m.end()]) for m in mentioned)
    ):
        return set()
    if _COMPOSITE.search(clause):
        refs = [r for r in refs if len(r.columns) >= 2]
    elif _SINGLE.search(clause):
        refs = [r for r in refs if len(r.columns) == 1]
    named = v1._mentioned_columns(clause, refs)
    if named:
        subset = [r for r in refs if r.columns and r.columns <= named]
        if subset:
            best = max(len(r.columns) for r in subset)
            refs = [r for r in subset if len(r.columns) == best]
    return {r.arm for r in refs}


def _subjects(clause: str, ctx: ClaimContext) -> _Subjects:
    arms = set(v1._ARM.findall(clause))
    if ctx.actions:
        if v1._ANALYZE_ACTION.search(clause):
            arms |= {r.arm for r in ctx.actions if r.kind == "analyze_statistics"}
        if v1._EXT_STATS_ACTION.search(clause):
            arms |= {r.arm for r in ctx.actions if r.kind == "extended_statistics"}
        elif _INDEX_NOUN.search(clause):
            arms |= _index_arms(clause, ctx)
        if v1._REWRITE_ACTION.search(clause):
            arms |= {r.arm for r in ctx.actions if r.kind == "query_rewrite"}
        if _ALL.search(clause):
            arms |= {r.arm for r in ctx.actions}
    lowered = clause.lower()
    params = {
        p
        for p in ctx.param_sets
        if re.search(rf"\b{re.escape(p.lower())}\b", lowered)
        or re.search(rf"\b{re.escape(p.lower().replace('_', ' '))}\b", lowered)
    }
    plan = None
    if _BASELINE_PLAN.search(clause):
        plan = "baseline"
    elif _CANDIDATE_PLAN.search(clause) or arms:
        plan = "candidate"
    return _Subjects(arms=frozenset(arms), param_sets=frozenset(params), plan=plan)


def _selected(ctx: ClaimContext, subjects: _Subjects) -> list[Measurement]:
    out = list(ctx.measurements)
    if subjects.arms:
        out = [m for m in out if m.arm in subjects.arms]
    if subjects.param_sets:
        # A replicated range belongs to the arm's primary param set, which a clause may not name.
        out = [
            m for m in out if m.param_set in subjects.param_sets or m.experiment == "replication"
        ]
    return out


def _savings(measurements: Sequence[Measurement]) -> list[float]:
    return [
        m.baseline_ms - m.candidate_ms
        for m in measurements
        if m.baseline_ms is not None and m.candidate_ms is not None
    ]


def _narrow(ctx: ClaimContext, subjects: _Subjects, clause: str) -> ClaimContext:
    # The baseline's own measured plan is baseline evidence like its EXPLAIN.
    plan_types = ctx.plan_node_types | ctx.candidate_plans.get(BASELINE_ARM, frozenset())
    if subjects.plan != "baseline" and ctx.candidate_plans:
        arms = subjects.arms or frozenset(ctx.candidate_plans)
        plan_types = plan_types.union(*(ctx.candidate_plans.get(a, frozenset()) for a in arms))
    if not subjects or not ctx.measurements:
        # Nothing to attribute to (no subject named, or no attributed measurements recorded):
        # claims@1's pooled check, with the candidate plans' scan types added when known.
        return dataclasses.replace(ctx, plan_node_types=plan_types)
    chosen = _selected(ctx, subjects)
    speedups = [v for m in chosen for v in (m.speedup, m.ci_low, m.ci_high) if v is not None]
    intervals = [
        (m.ci_low, m.ci_high) for m in chosen if m.ci_low is not None and m.ci_high is not None
    ]
    medians = [v for m in chosen for v in (m.baseline_ms, m.candidate_ms) if v is not None]
    extra = _savings(chosen) if _SAVING.search(clause) else []
    return dataclasses.replace(
        ctx,
        plan_node_types=plan_types,
        speedups=tuple(speedups),
        intervals=tuple(intervals),
        latencies_ms=(*ctx.plan_latencies_ms, *medians, *extra),
    )


def _approximate(clause: str, start: int) -> bool:
    return bool(_APPROX_BEFORE.search(clause[max(0, start - 16) : start]))


def extract_claims(clause: str) -> list[TypedClaim]:
    """The quantitative claims claims@1 does not parse, as typed objects."""
    out: list[TypedClaim] = []
    for m in _FOLD.finditer(clause):
        token = next(g for g in m.groups() if g is not None)
        out.append(
            TypedClaim("speedup", (float(token),), m.group(0), approximate="~" in m.group(0)
                       or bool(re.search(r"about|around|roughly|approximately|nearly",
                                         m.group(0), re.I)))
        )  # fmt: skip
    for m in _PCT_BY.finditer(clause):
        out.append(
            TypedClaim("percent", (float(m.group(2)),), m.group(0),
                       reduction=not m.group(1).lower().startswith(("improv", "speed")))
        )  # fmt: skip
    for m in _PCT_WORD.finditer(clause):
        out.append(
            TypedClaim("percent", (float(m.group(1)),), m.group(0),
                       approximate=_approximate(clause, m.start()),
                       reduction=bool(_REDUCTION.search(m.group(2))))
        )  # fmt: skip
    for m in _SAVING.finditer(clause):
        token = next(g for g in m.groups() if g is not None)
        approx = bool(re.search(r"about|around|roughly|approximately|nearly|~|≈", m.group(0)))
        out.append(TypedClaim("saving", (float(token),), m.group(0), approximate=approx))
    for m in _TRANSITION.finditer(clause):
        values = tuple(float(g) for g in m.groups() if g is not None)
        approx = bool(re.search(r"about|around|roughly|approximately|nearly|~|≈", m.group(0)))
        out.append(TypedClaim("transition", values, m.group(0), approximate=approx))
    return out


def _close(value: float, token: str, target: float, slack: float) -> bool:
    return abs(target - value) <= max(v1._tolerance(token), slack * abs(target))


def _token(value: float) -> str:
    text = f"{value:g}"
    return text


def _typed(claim: TypedClaim, chosen: Sequence[Measurement], ctx: ClaimContext) -> list[str]:
    if not ctx.benchmarked:
        what = {"speedup": "speed-up", "percent": "improvement", "saving": "saving"}
        if claim.kind in what:
            return [f"{what[claim.kind]} in '{claim.text}' stated before anything was benchmarked"]
        return []
    slack = v1.APPROX_SLACK if claim.approximate else v1.SPEEDUP_SLACK
    tokens = [_token(v) for v in claim.values]
    if not ctx.measurements:
        # A context without attribution (built by claims@1 callers): judge speed-ups and
        # percentages against the pooled figures; savings and transitions cannot be judged.
        if claim.kind not in ("speedup", "percent"):
            return []
        values = list(ctx.speedups)
    else:
        values = [v for m in chosen for v in (m.speedup, m.ci_low, m.ci_high) if v is not None]
    if claim.kind == "speedup" and not any(
        _close(claim.values[0], tokens[0], v, slack) for v in values
    ):
        return [f"speed-up in '{claim.text}' matches no measured value of its subject"]
    if claim.kind == "percent":
        value = claim.values[0]
        if claim.reduction and value >= 100:
            return [f"'{claim.text}': a latency reduction of {tokens[0]}% is impossible"]
        speedups = [v for v in values if v > 0]
        reductions = [100 * (1 - 1 / v) for v in speedups]
        allowed = (
            reductions if claim.reduction else [*reductions, *(100 * (v - 1) for v in speedups)]
        )
        if not any(_close(value, tokens[0], p, slack) for p in allowed):
            kind = "reduction (1 - 1/speed-up)" if claim.reduction else "improvement"
            return [f"'{claim.text}' is no measured {kind} of its subject"]
    if claim.kind == "saving":
        slack = v1.APPROX_SLACK if claim.approximate else v1.LATENCY_SLACK
        if not any(_close(claim.values[0], tokens[0], s, slack) for s in _savings(chosen)):
            return [f"saving in '{claim.text}' is no measured baseline-candidate difference"]
    if claim.kind == "transition" and len(claim.values) == 2:
        slack = v1.APPROX_SLACK if claim.approximate else v1.LATENCY_SLACK
        before, after = claim.values
        if not any(
            m.baseline_ms is not None
            and m.candidate_ms is not None
            and _close(before, tokens[0], m.baseline_ms, slack)
            and _close(after, tokens[1], m.candidate_ms, slack)
            for m in chosen
        ):
            return [f"'{claim.text}' is not one measurement's baseline and candidate medians"]
    return []


def _category(verdict: str) -> str:
    if verdict in VERIFIED:
        return "verified"
    if verdict in ("rejected", "inconclusive"):
        return verdict
    return "other"


def _status(clause: str, ctx: ClaimContext, subjects: _Subjects) -> list[str]:
    known = {a: ctx.verdicts[a] for a in subjects.arms if a in ctx.verdicts}
    if not known:
        return []
    said = [
        name
        for name, pattern in (
            ("verified", _SAYS_VERIFIED),
            ("rejected", _SAYS_REJECTED),
            ("inconclusive", _SAYS_INCONCLUSIVE),
        )
        if pattern.search(clause)
    ]
    problems: list[str] = []
    if len(said) == 1:
        claimed = said[0]
        wrong = {a: v for a, v in known.items() if _category(v) != claimed}
        right = len(known) - len(wrong)
        if wrong and not (_ONLY.search(clause) and right):
            problems += [
                f"{a} is described as {claimed} but its verdict is {v}"
                for a, v in sorted(wrong.items())
            ]
    if _CLEAN.search(clause):
        problems += [
            f"{a} carries a noise warning and cannot be described as cleanly verified"
            for a, v in sorted(known.items())
            if v == "verified_with_noise_warning"
        ]
    return problems


def _advice(clause: str, ctx: ClaimContext, subjects: _Subjects) -> list[str]:
    if not ctx.actions or not _ADVISES_AGAINST.search(clause):
        return []
    verified = {r.arm for r in ctx.actions if r.verified}
    return [
        f"advises against {a}, which the benchmark verified"
        for a in sorted(subjects.arms & verified)
    ]


def _plans_and_stats(clause: str, ctx: ClaimContext) -> list[str]:
    problems: list[str] = []
    for m in _DIRECTION.finditer(clause):
        if ctx.estimate_directions and m.group(1).lower() not in ctx.estimate_directions:
            problems.append(f"no recorded plan node shows an {m.group(1).lower()}estimate")
    if (
        _ACCURATE_ESTIMATES.search(clause)
        and ctx.max_estimate_ratio is not None
        and ctx.max_estimate_ratio >= INACCURATE_RATIO
    ):
        problems.append(
            f"a recorded plan node's estimate is off by {ctx.max_estimate_ratio:g}x, so the "
            "estimates are not accurate"
        )
    if _FRESH_STATS.search(clause) and ctx.stats.stale:
        problems.append("recorded statistics are stale, so they are not up to date")
    if _GUARANTEE.search(clause) and not _GUARANTEE_DENIED.search(clause):
        problems.append("a sandbox benchmark cannot guarantee an improvement")
    return problems


def _clause_problems(clause: str, ctx: ClaimContext, inherited: _Subjects, mode: Mode) -> list[str]:
    own = _subjects(clause, ctx)
    subjects = _Subjects(
        arms=own.arms or inherited.arms,
        param_sets=own.param_sets or inherited.param_sets,
        plan=own.plan or inherited.plan,
    )
    narrowed = _narrow(ctx, subjects, clause)
    problems: list[str] = []
    numeric = clause
    if v1._ESTIMATE.search(clause) and not _SPEED_WORD.search(clause):
        # The whole clause is about estimates: "Nx" is an estimate-error ratio, wherever the
        # word "estimate" sits (claims@1 looks only 40 characters around the figure).
        for m in v1._MULT.finditer(clause):
            token = m.group(1) or m.group(2)
            if ctx.ratios and not v1._matches(token, ctx.ratios, v1.RATIO_SLACK):
                problems.append(f"estimate error {token}x matches no plan node")
            numeric = numeric[: m.start()] + " " * (m.end() - m.start()) + numeric[m.end() :]
    problems += [
        *v1._numbers(numeric, narrowed),
        *v1._scans(clause, narrowed, mode),
        *v1._statistics(clause, narrowed, mode),
        *v1._verification(clause, narrowed),
    ]
    if _RECOMMENDS.search(clause) and not _ADVISES_AGAINST.search(clause):
        problems += v1._actions(clause, narrowed)
    chosen = _selected(ctx, subjects) if subjects else list(ctx.measurements)
    for claim in extract_claims(clause):
        problems += _typed(claim, chosen, ctx)
    problems += _status(clause, ctx, subjects)
    problems += _advice(clause, ctx, subjects)
    problems += _plans_and_stats(clause, ctx)
    return problems


def check_sentence(sentence: str, ctx: ClaimContext, *, mode: Mode = "fact") -> list[str]:
    s = _norm(sentence)
    inherited = _subjects(s, ctx)
    found: list[str] = []
    for clause in _clauses(s):
        for problem in _clause_problems(clause, ctx, inherited, mode):
            if problem not in found:
                found.append(problem)
    return found


def filter_text(text: str, ctx: ClaimContext, *, mode: Mode = "fact") -> Filtered:
    """claims@1's contract: whole sentences kept or removed, in order, never reworded."""
    kept: list[str] = []
    removed: list[str] = []
    problems: list[str] = []
    for sentence in sentences(text):
        found = check_sentence(sentence, ctx, mode=mode)
        if found:
            removed.append(sentence)
            problems += [f'"{v1._label(sentence)}": {p}' for p in found]
        else:
            kept.append(sentence)
    return Filtered(text=" ".join(kept), removed=removed, problems=problems)


def plan_node_types(nodes: Sequence[str]) -> frozenset[str]:
    """Normalized node types of one plan, as claim_context records the baseline's."""
    return frozenset(t.lower().removeprefix("parallel ") for t in nodes)


def _float(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def claim_context(
    evidence: Sequence[Evidence],
    *,
    query_sql: str | None,
    actions: Sequence[ActionRef] = (),
    verdicts: Mapping[str, str] | None = None,
    candidate_plans: Mapping[str, frozenset[str]] | None = None,
    replication_ranges: Mapping[str, tuple[float, float]] | None = None,
) -> ClaimContext:
    """claims@1's pooled context, plus every figure attributed to its arm, param set and
    experiment, each candidate's own plan, and each replicated arm's reported range."""
    base = v1.claim_context(evidence, query_sql=query_sql, actions=actions, verdicts=verdicts)
    measurements: list[Measurement] = []
    plan_latencies: list[float] = []
    directions: set[str] = set()
    ratios: list[float] = []
    for e in evidence:
        if e.kind == "benchmark_metric":
            arm, ps = e.data.get("arm"), e.data.get("param_set")
            if isinstance(arm, str) and isinstance(ps, str):
                measurements.append(
                    Measurement(
                        arm=arm,
                        param_set=ps,
                        experiment=e.artifact_sha256 or "",
                        speedup=_float(e.data.get("speedup")),
                        ci_low=_float(e.data.get("ci_low")),
                        ci_high=_float(e.data.get("ci_high")),
                        baseline_ms=_float(e.data.get("baseline_median_ms")),
                        candidate_ms=_float(e.data.get("candidate_median_ms")),
                    )
                )
            continue
        plan_latencies += [
            float(v) for k, v in e.data.items() if k.endswith("_ms") and isinstance(v, int | float)
        ]
        if e.kind == "plan_node":
            if isinstance(d := e.data.get("estimate_direction"), str) and d in ("under", "over"):
                directions.add(d)
            if (r := _float(e.data.get("estimate_error_ratio"))) is not None:
                ratios.append(r)
    ranges = dict(replication_ranges or {})
    for arm, (lo, hi) in ranges.items():
        measurements.append(Measurement(arm, "*", "replication", None, lo, hi, None, None))
    pooled = {f.name: getattr(base, f.name) for f in dataclasses.fields(v1.ClaimContext)}
    if ranges:
        pooled["speedups"] = (*base.speedups, *(v for r in ranges.values() for v in r))
        pooled["intervals"] = (*base.intervals, *ranges.values())
        pooled["benchmarked"] = True
    return ClaimContext(
        **pooled,
        measurements=tuple(measurements),
        candidate_plans=dict(candidate_plans or {}),
        plan_latencies_ms=tuple(plan_latencies),
        estimate_directions=frozenset(directions),
        max_estimate_ratio=max(ratios) if ratios else None,
        param_sets=tuple(sorted({m.param_set for m in measurements if m.param_set != "*"})),
    )
