"""In-memory EngineHooks and config builders for engine tests (no metadata DB needed)."""

import threading
import uuid
from dataclasses import dataclass, field
from typing import Any

from querycure.benchmark.engine import ApprovedExperiment, BlockRecord, sql_digest
from querycure.domain.benchmark import (
    CandidateArm,
    EnvironmentFingerprint,
    ExperimentConfig,
    ParamSetSpec,
    RuleVerdict,
)


@dataclass
class MemoryHooks:
    records: list[BlockRecord] = field(default_factory=list)
    states: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    env: EnvironmentFingerprint | None = None
    cancel: threading.Event = field(default_factory=threading.Event)
    cancel_after_blocks: int | None = None

    def existing(self) -> list[BlockRecord]:
        return list(self.records)

    def persist(self, record: BlockRecord) -> None:
        assert record.key not in {r.key for r in self.records}, "duplicate block row"
        self.records.append(record)
        measured = sum(1 for r in self.records if r.phase == "measure")
        if self.cancel_after_blocks is not None and measured >= self.cancel_after_blocks:
            self.cancel.set()

    def progress(self, state: str, **details: Any) -> None:
        self.states.append((state, details))

    def environment(self, env: EnvironmentFingerprint, env_digest: str) -> None:
        self.env = env

    def cancelled(self) -> bool:
        return self.cancel.is_set()


def arm(
    key: str, kind: str, ddl: list[str] | None = None, query: str | None = None
) -> CandidateArm:
    return CandidateArm(
        arm=key,
        candidate_id=None,
        kind=kind,
        ddl=ddl or [],
        query=query,  # type: ignore[arg-type]
    )


def config(
    workload: str,
    query: str,
    candidates: list[CandidateArm],
    param_sets: list[tuple[str, list[Any]]],
    **overrides: Any,
) -> ExperimentConfig:
    body: dict[str, Any] = {
        "experiment_id": uuid.uuid4(),
        "workload_id": workload,
        "baseline_query": query,
        "candidates": candidates,
        "param_sets": [ParamSetSpec(name=n, values=v) for n, v in param_sets],
        "seed": 42,
        "warmup_runs": 5,
        "measured_runs": 30,
    }
    body.update(overrides)
    return ExperimentConfig.model_validate(body)


def approve_all(cfg: ExperimentConfig) -> ApprovedExperiment:
    return ApprovedExperiment(
        approval_request_id=str(uuid.uuid4()),
        approved_sql={c.arm: sql_digest(c) for c in cfg.candidates},
    )


def assert_verified_or_noisy(verdict: RuleVerdict) -> None:
    """Positive cases on shared hardware (ROADMAP Phase 3 acceptance #2).

    On the local Docker Desktop profile a bare `SELECT 1` round trip already has a robust CV
    of 0.26-0.28 (measured 2026-10-12), and other processes load the host, so the sample-
    quality gate may legitimately stop a real improvement at `inconclusive`. That is the only
    tolerated deviation: never `rejected`, never any other gate or reason.
    """
    if verdict.verdict == "verified":
        return
    assert verdict.verdict == "inconclusive", verdict
    assert verdict.gate == 4, verdict
    assert verdict.reasons[0].code == "insufficient_evidence", verdict
