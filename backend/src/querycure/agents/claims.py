"""Deterministic grounding of AI-written prose against recorded evidence (ADR-0026), `claims@1`.

Frozen on 2026-10-18: new runs use `claims@2` (agents/claims_v2.py, ADR-0028), which reuses these
rules on attributed contexts. Do not change behaviour here; add a new checker version instead.

Citations prove that a claim points at evidence; they do not prove the claim agrees with it.
This module checks the claim kinds that the 2026-10-17 audit found contradicting evidence,
sentence by sentence, and removes the sentences it cannot support:

- speed-up figures and ranges: must equal a measured point estimate or confidence bound
  (to the precision stated), a range must equal one stored interval, and nothing is
  quantified before a benchmark exists; percentages must derive from a measured speed-up;
- latencies in ms: must match a recorded timing;
- scan types: an index-only scan is impossible for `SELECT *` unless a plan shows one; a
  scan type asserted as fact must appear in a recorded plan (proposals may name others);
- verification status: nothing is "verified" before a benchmark, and a named candidate's
  stated status must match its recorded verdict;
- recommended actions (after benchmarking): must map to a verified candidate;
- statistics: "never analyzed" contradicts present planner statistics, reset usage counters
  are not evidence, and staleness stated as fact needs evidence of staleness.

Nothing here calls a model or decides a verdict. Removal is the only action: it never
rewrites a sentence or adds text, so the remaining prose is still the model's own words.
`mode="hypothesis"` tolerates claims a hypothesis may legitimately propose (an unobserved
scan type, possibly stale statistics) but never contradicted ones.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from sqlglot import exp

from querycure.core.errors import QueryCureError
from querycure.domain.investigation import Evidence
from querycure.sql.parser import parse_single

CHECKER_VERSION = "claims@1"
Mode = Literal["fact", "hypothesis"]
VERIFIED = frozenset({"verified", "verified_with_noise_warning"})
MAX_SQL_BYTES = 100_000

_DASHES = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212]")
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[`])")
_NUM = r"(\d+(?:\.\d+)?)"
_TIMES = r"(?:x|\u00d7)(?![a-z0-9])"
_RANGE = re.compile(rf"{_NUM}\s*(?:{_TIMES})?\s*(?:-|to)\s*{_NUM}\s*{_TIMES}", re.I)
_MULT = re.compile(rf"{_NUM}\s*{_TIMES}|{_NUM}\s+times\s+(?:faster|quicker|slower)", re.I)
_PERCENT = re.compile(
    rf"{_NUM}\s*%\s*(?:faster|quicker|slower|less time|lower latency|speed-?up|"
    r"reduction|improvement|decrease)",
    re.I,
)
_MS = re.compile(rf"{_NUM}\s*(?:ms|milliseconds?)\b", re.I)
_HEDGE = re.compile(
    r"\b(would|could|might|may|can|should|expected|expect|likely|allow|allows|allowing|"
    r"enable|enables|enabling|let|lets|permit|permits|if|instead|replace|replaces|avoid|"
    r"avoids|avoiding|without|potential|potentially|propos\w*|candidate|hypothes\w*|"
    r"switch|switches|support|supports|turn|turns|become|becomes)\b",
    re.I,
)
_SCAN_TYPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("index only scan", re.compile(r"\bindex[- ]only(?:[- ](?:ordered[- ])?scans?)?\b", re.I)),
    ("bitmap heap scan", re.compile(r"\bbitmap[- ]heap[- ]scans?\b", re.I)),
    ("bitmap index scan", re.compile(r"\bbitmap[- ]index[- ]scans?\b", re.I)),
    ("index scan", re.compile(r"\bindex[- ]scans?\b", re.I)),
    ("seq scan", re.compile(r"\b(?:seq|sequential|full[- ]table)[- ]scans?\b", re.I)),
)
_COUNTER = re.compile(
    r"\b(?:\d[\d,]*|zero|no)\s+(?:seq(?:uential)?|index)[- ]scans\b"
    r"|\bnever had an? (?:index|seq(?:uential)?)[- ]scans?\b"
    r"|\bzero scans\b|\bnever (?:been )?(?:scanned|vacuumed)\b",
    re.I,
)
_NEVER_ANALYZED = re.compile(
    r"\bnever\s+(?:been\s+|was\s+)?analy[sz]ed\b|\bnot\s+(?:yet\s+|ever\s+)?been\s+analy[sz]ed\b"
    r"|\bno\s+(?:recorded\s+|prior\s+)?analy[sz]e\b|\blast analy[sz]ed never\b"
    r"|\b(?:statistics|stats)\s+(?:are\s+|is\s+)?(?:missing|absent)\b",
    re.I,
)
_STALE = re.compile(
    r"\b(?:stale|outdated|out-of-date|out of date|obsolete)\s+(?:table\s+|planner\s+|column\s+)?"
    r"stat(?:istic)?s\b|\bstat(?:istic)?s\s+(?:are|is|appear|seem|look|may be|might be|"
    r"could be)\s+(?:\w+\s+)?(?:stale|outdated|out-of-date|out of date)\b",
    re.I,
)
_ARM = re.compile(r"\boc_[0-9a-f]{12}\b")
_ASSERT_VERIFIED = re.compile(
    r"\b(?:is|was|were|are|been|got)\s+(?:\w+\s+)?(?:verified|confirmed|proven|validated)\b"
    r"|\bverified\s+(?:speed-?ups?|improvements?|gains?|recommendations?|results?|"
    r"(?:to\s+)?(?:be\s+)?faster)\b",
    re.I,
)
_NOT_VERIFIED = re.compile(
    r"\b(?:inconclusive|not verified|unverified|rejected|remained|remains|did not|didn't|"
    r"does not|failed|no demonstrated|no measurable|no benefit|no improvement|not faster|"
    r"regress\w*|slower|declined)\b",
    re.I,
)
_ANALYZE_ACTION = re.compile(
    r"(?<!EXPLAIN )\bANALYZE\b|(?i:\bre-?analy[sz]\w*|\b(?:run|running|re-?run|refresh|"
    r"refreshing|update|updating|collect|collecting|gather|gathering)\s+(?:the\s+)?"
    r"(?:table\s+|planner\s+|column\s+)?statistics\b)"
)
_INDEX_ACTION = re.compile(
    r"\bCREATE\s+(?:UNIQUE\s+)?INDEX\b|\b(?:create|creates|created|creating|add|adds|adding|"
    r"build|builds|building)\s+(?:a|an|the)?\s*(?:[\w()-]+\s+){0,4}?indexe?s?\b",
    re.I,
)
_EXT_STATS_ACTION = re.compile(r"\bCREATE\s+STATISTICS\b|\bextended statistics\b", re.I)
_REWRITE_ACTION = re.compile(r"\brewrit(?:e|es|ing|ten)\b", re.I)
_DDL_COLUMNS = re.compile(r"\bON\s+[\w.\"]+\s*(?:USING\s+\w+\s*)?\((.*)\)", re.I | re.S)


@dataclass(frozen=True)
class StatsSupport:
    """What the recorded table statistics can support. All False: no table statistics."""

    tables_known: bool = False  # some table_stat evidence exists
    planner_stats_absent: bool = False  # a table has no planner statistics at all
    stale: bool = False  # recorded counters show statistics behind the data
    freshness_known: bool = False  # live counters were available to judge freshness
    counters_live: bool = False  # usage counters are real, not reset by cloning


@dataclass(frozen=True)
class ActionRef:
    arm: str
    kind: str
    columns: frozenset[str]
    verified: bool


@dataclass(frozen=True)
class ClaimContext:
    plan_node_types: frozenset[str] = frozenset()
    star_projection: bool | None = None
    stats: StatsSupport = field(default_factory=StatsSupport)
    benchmarked: bool = False
    speedups: tuple[float, ...] = ()  # point estimates and CI bounds
    intervals: tuple[tuple[float, float], ...] = ()
    ratios: tuple[float, ...] = ()  # plan estimate-error ratios ("12x underestimate")
    latencies_ms: tuple[float, ...] = ()
    actions: tuple[ActionRef, ...] = ()  # judged only when non-empty (after benchmarking)
    verdicts: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Filtered:
    text: str
    removed: list[str]
    problems: list[str]


def _normalize(text: str) -> str:
    return _DASHES.sub("-", text)


# Relative slack for figures a model rounds or truncates (62.568 ms -> "62 ms", 270.81 -> "270x").
SPEEDUP_SLACK = 0.02
LATENCY_SLACK = 0.03
RATIO_SLACK = 0.05
APPROX_SLACK = 0.10  # the text itself says the figure is approximate
_APPROX = re.compile(r"(?:\u2248|~|\babout|\baround|\broughly|\bapproximately|\bnearly)\s*$", re.I)
_ESTIMATE = re.compile(r"\b(?:over|under|mis)-?estimat|\bestimat\w* error", re.I)
ESTIMATE_WINDOW = 40  # characters around a ratio that may name it an estimate error


def _tolerance(token: str) -> float:
    decimals = len(token.split(".")[1]) if "." in token else 0
    return 0.5 * 10.0**-decimals + 1e-9


def _matches(token: str, values: Sequence[float], slack: float = 0.0) -> bool:
    x, tol = float(token), _tolerance(token)
    return any(abs(v - x) <= max(tol, slack * abs(v)) for v in values)


def _approximate(s: str, start: int) -> bool:
    return bool(_APPROX.search(s[max(0, start - 16) : start]))


def _label(sentence: str) -> str:
    return sentence if len(sentence) <= 80 else sentence[:79] + "\u2026"


def _numbers(s: str, ctx: ClaimContext) -> list[str]:
    problems: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _RANGE.finditer(s):
        spans.append(m.span())
        lo, hi = m.group(1), m.group(2)
        ok = ctx.benchmarked and any(
            abs(a - float(lo)) <= _tolerance(lo) and abs(b - float(hi)) <= _tolerance(hi)
            for a, b in ctx.intervals
        )
        if not ok:
            problems.append(
                f"speed-up range {lo}-{hi}x matches no measured confidence interval"
                if ctx.benchmarked
                else f"speed-up range {lo}-{hi}x stated before anything was benchmarked"
            )
    for m in _MULT.finditer(s):
        if any(a <= m.start() < b for a, b in spans):
            continue
        token = m.group(1) or m.group(2)
        slack = APPROX_SLACK if _approximate(s, m.start()) else 0.0
        around = s[max(0, m.start() - ESTIMATE_WINDOW) : m.end() + ESTIMATE_WINDOW]
        if _ESTIMATE.search(around) and not re.search(r"\b(?:faster|quicker|slower|speed)", around):
            # "433x overestimate": a plan estimate-error ratio, never a speed-up.
            if ctx.ratios and not _matches(token, ctx.ratios, max(slack, RATIO_SLACK)):
                problems.append(f"estimate error {token}x matches no plan node")
            continue
        if not ctx.benchmarked:
            problems.append(f"speed-up {token}x stated before anything was benchmarked")
        elif not _matches(token, ctx.speedups, max(slack, SPEEDUP_SLACK)):
            problems.append(f"speed-up {token}x matches no measured value")
    for m in _PERCENT.finditer(s):
        token = m.group(1)
        derived = [p for v in ctx.speedups if v > 0 for p in (100 * (1 - 1 / v), 100 * (v - 1))]
        slack = APPROX_SLACK if _approximate(s, m.start()) else SPEEDUP_SLACK
        if not ctx.benchmarked or not _matches(token, derived, slack):
            problems.append(f"improvement of {token}% does not derive from a measured speed-up")
    for m in _MS.finditer(s):
        slack = APPROX_SLACK if _approximate(s, m.start()) else LATENCY_SLACK
        if not _matches(m.group(1), ctx.latencies_ms, slack):
            problems.append(f"latency {m.group(1)} ms matches no recorded timing")
    return problems


def _scans(s: str, ctx: ClaimContext, mode: Mode) -> list[str]:
    problems: list[str] = []
    rest = _COUNTER.sub(" ", s)
    hedged = bool(_HEDGE.search(rest))
    for name, pattern in _SCAN_TYPES:
        if not pattern.search(rest):
            continue
        rest = pattern.sub(" ", rest)
        if name in ctx.plan_node_types:
            continue
        if name == "index only scan" and ctx.star_projection:
            problems.append(
                "an index-only scan is impossible for SELECT * and no recorded plan shows one"
            )
        elif not hedged and mode == "fact" and ctx.plan_node_types:
            problems.append(f"no recorded plan contains a {name}")
    return problems


def _statistics(s: str, ctx: ClaimContext, mode: Mode) -> list[str]:
    stats = ctx.stats
    problems: list[str] = []
    if not stats.tables_known:
        return problems
    if _COUNTER.search(s) and not stats.counters_live:
        problems.append(
            "usage counters (scan counts) were reset by sandbox cloning and are not evidence"
        )
    if _NEVER_ANALYZED.search(s) and not stats.planner_stats_absent:
        problems.append("planner statistics are present, so the table has been analyzed")
    stale = _STALE.search(s)
    if stale and not (stats.stale or stats.planner_stats_absent):
        # Only hedging of the staleness itself counts ("may be stale"), not of a consequence.
        hedged = bool(re.search(r"\b(?:may|might|could)\b", stale.group(0), re.I))
        if stats.freshness_known or (mode == "fact" and not hedged):
            problems.append("no recorded statistic shows the statistics are stale")
    return problems


def _verification(s: str, ctx: ClaimContext) -> list[str]:
    problems: list[str] = []
    arms = list(dict.fromkeys(_ARM.findall(s)))
    asserted = bool(_ASSERT_VERIFIED.search(s))
    if asserted and not ctx.benchmarked:
        return ["claims a verification although nothing was benchmarked"]
    denied = bool(_NOT_VERIFIED.search(s))
    for arm in arms:
        verdict = ctx.verdicts.get(arm)
        if verdict is None:
            continue
        if asserted and not denied and verdict not in VERIFIED:
            problems.append(f"{arm} is described as verified but its verdict is {verdict}")
        if denied and not asserted and verdict in VERIFIED:
            problems.append(f"{arm} is described as not verified but its verdict is {verdict}")
    return problems


def _mentioned_columns(s: str, refs: Sequence[ActionRef]) -> frozenset[str]:
    lowered = s.lower()
    known = {c for r in refs for c in r.columns}
    return frozenset(c for c in known if re.search(rf"\b{re.escape(c)}\b", lowered))


def _actions(s: str, ctx: ClaimContext) -> list[str]:
    if not ctx.actions or _NOT_VERIFIED.search(s):
        return []
    problems: list[str] = []
    wanted: list[tuple[str, str]] = []
    if _ANALYZE_ACTION.search(s):
        wanted.append(("analyze_statistics", "ANALYZE"))
    if _EXT_STATS_ACTION.search(s):
        wanted.append(("extended_statistics", "extended statistics"))
    elif _INDEX_ACTION.search(s):
        wanted.append(("create_index", "the index"))
    if _REWRITE_ACTION.search(s):
        wanted.append(("query_rewrite", "the rewrite"))
    for kind, label in wanted:
        refs = [r for r in ctx.actions if r.kind == kind]
        if kind == "create_index":
            named = _mentioned_columns(s, refs)
            subset = [r for r in refs if r.columns and r.columns <= named]
            if named and subset:
                best = max(len(r.columns) for r in subset)
                refs = [r for r in subset if len(r.columns) == best]
            elif named:
                refs = []
        if not any(r.verified for r in refs):
            problems.append(f"recommends {label}, which was not verified by the benchmark")
    return problems


def check_sentence(sentence: str, ctx: ClaimContext, *, mode: Mode = "fact") -> list[str]:
    s = _normalize(sentence)
    return [
        *_numbers(s, ctx),
        *_scans(s, ctx, mode),
        *_statistics(s, ctx, mode),
        *_verification(s, ctx),
        *_actions(s, ctx),
    ]


def sentences(text: str) -> list[str]:
    return [p for p in _SENTENCE.split(text.strip()) if p.strip()]


def filter_text(text: str, ctx: ClaimContext, *, mode: Mode = "fact") -> Filtered:
    """Keeps the sentences that pass every check, in order, joined by single spaces."""
    kept: list[str] = []
    removed: list[str] = []
    problems: list[str] = []
    for sentence in sentences(text):
        found = check_sentence(sentence, ctx, mode=mode)
        if found:
            removed.append(sentence)
            problems += [f'"{_label(sentence)}": {p}' for p in found]
        else:
            kept.append(sentence)
    return Filtered(text=" ".join(kept), removed=removed, problems=problems)


def star_projection(sql: str | None) -> bool | None:
    """True if the query projects `*` (or `t.*`); None when unknown."""
    if sql is None:
        return None
    try:
        tree = parse_single(sql, max_bytes=MAX_SQL_BYTES)
    except QueryCureError:
        return None
    selects = [tree] if isinstance(tree, exp.Select) else list(tree.find_all(exp.Select))
    if not selects:
        return None
    for select in selects:
        for projection in select.expressions:
            if isinstance(projection, exp.Star) or (
                isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
            ):
                return True
    return False


def index_columns(ddl: str) -> frozenset[str]:
    """Leading column names of a CREATE INDEX column list, lower-cased; expressions skipped."""
    match = _DDL_COLUMNS.search(ddl)
    if match is None:
        return frozenset()
    out = set()
    for part in match.group(1).split(","):
        token = part.strip().split()[0] if part.strip() else ""
        token = token.strip('"')
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", token):
            out.add(token.lower())
    return frozenset(out)


def _numbers_in(data: Mapping[str, object], keys: Sequence[str]) -> list[float]:
    return [float(v) for k in keys if isinstance(v := data.get(k), int | float)]


def _stats_support(table_stats: Sequence[Evidence]) -> StatsSupport:
    # Evidence recorded before ADR-0026 carries no classification: nothing is judged then.
    classified = [e.data for e in table_stats if "planner_stats" in e.data]
    if not classified:
        return StatsSupport()
    freshness = [d.get("freshness") for d in classified]
    return StatsSupport(
        tables_known=True,
        planner_stats_absent=any(d.get("planner_stats") != "present" for d in classified),
        stale=any(f == "stale" for f in freshness),
        freshness_known=all(f in ("stale", "not_stale", "never_analyzed") for f in freshness),
        counters_live=all(d.get("counters") == "live" for d in classified),
    )


def claim_context(
    evidence: Sequence[Evidence],
    *,
    query_sql: str | None,
    actions: Sequence[ActionRef] = (),
    verdicts: Mapping[str, str] | None = None,
) -> ClaimContext:
    """Everything the checks compare against, from recorded evidence only."""
    node_types: set[str] = set()
    ratios: list[float] = []
    latencies: list[float] = []
    speedups: list[float] = []
    intervals: list[tuple[float, float]] = []
    for e in evidence:
        latencies += [
            float(v) for k, v in e.data.items() if k.endswith("_ms") and isinstance(v, int | float)
        ]
        if e.kind == "plan_node" and isinstance(t := e.data.get("node_type"), str):
            node_types.add(t.lower().removeprefix("parallel "))
            ratios += _numbers_in(e.data, ("estimate_error_ratio",))
        if e.kind == "benchmark_metric":
            speedups += _numbers_in(e.data, ("speedup", "ci_low", "ci_high"))
            lo, hi = e.data.get("ci_low"), e.data.get("ci_high")
            if isinstance(lo, int | float) and isinstance(hi, int | float):
                intervals.append((float(lo), float(hi)))
    return ClaimContext(
        plan_node_types=frozenset(node_types),
        star_projection=star_projection(query_sql),
        stats=_stats_support([e for e in evidence if e.kind == "table_stat"]),
        benchmarked=bool(speedups),
        speedups=tuple(speedups),
        intervals=tuple(intervals),
        ratios=tuple(ratios),
        latencies_ms=tuple(latencies),
        actions=tuple(actions),
        verdicts=dict(verdicts or {}),
    )


def action_refs(candidates: Sequence[Any]) -> list[ActionRef]:
    """From OptimizationCandidate-like records (key, kind, ddl, status)."""
    return [
        ActionRef(
            arm=c.key,
            kind=c.kind,
            columns=frozenset().union(*(index_columns(d) for d in c.ddl)) if c.ddl else frozenset(),
            verified=c.status in VERIFIED,
        )
        for c in candidates
    ]
