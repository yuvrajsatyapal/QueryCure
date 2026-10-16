"""Measurement fixtures: deterministic Mode C agent evals without re-benchmarking (R19).

Why: a Mode C eval replays recorded model answers, but the Benchmark Auditor's prompt (and
later Optimization Engineer rounds) embed the experiment's measurements. A fresh benchmark
measures new numbers, so those prompts never match the recording, and the replay can only end
`DIVERGED` (ADR-0022 §10). Agent decisions and live performance are two different things to
test, so they are separated:

- **Record mode** measures for real in the sandbox and, beside the model recording, captures
  every replicate the engine produced (config, environment fingerprint, raw blocks, result) as
  a fixture relabelled `provenance = "prerecorded"` at every layer.
- **Fixture mode** feeds those exact blocks and results back through the same persistence
  hooks instead of running the engine. Nothing executes in the sandbox for the experiment,
  so the run is benchmark-free, and every prompt that embeds measurements is byte-identical
  to the recorded one. Exact prompt matching then applies to the whole run.
- **Live mode** (the default for the worker and for `--measurements live`) is unchanged.

Safety rails, so a fixture can never quietly stand in for something else:
- every arm's SQL digest is checked against the approval, as the engine does;
- the run's experiment config must equal the recorded one (any drift in candidates, param
  sets, seed or ids is a mismatch, never a substitution);
- the replication verdicts are recomputed with the frozen rules and must equal the recorded
  ones;
- a mismatch is recorded on the source object and the eval reports it as a failure, even if
  the graph turned the error into an `inconclusive` candidate.
- blocks, evidence and results written from a fixture carry `prerecorded`, which the report
  and UI label, and which the verdict engine never mixes with measured samples.
"""

import dataclasses
import hashlib
import uuid
from collections.abc import Callable
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from querycure.benchmark.engine import (
    ApprovedExperiment,
    BlockRecord,
    EngineHooks,
    EngineOptions,
    ReplicatedRun,
    State,
    run_replicated,
    sql_digest,
)
from querycure.benchmark.replication import (
    Replicate,
    assess_all,
    eligible_arms,
    replicate_config,
)
from querycure.core.errors import QueryCureError
from querycure.domain.benchmark import (
    EnvironmentFingerprint,
    ExperimentConfig,
    ExperimentResult,
    ReplicationResult,
)
from querycure.replay.canonical import canonical_json
from querycure.sandbox.provisioner import SandboxProvisioner

MEASUREMENT_FIXTURE_SCHEMA_VERSION = 1

# Same signature as benchmark.engine.run_replicated (the node's measurement seam).
MeasureFn = Callable[..., ReplicatedRun]


class MeasurementFixtureMismatchError(QueryCureError):
    code = "MEASUREMENT_FIXTURE_MISMATCH"
    status = 500


class RecordedReplicate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    config: ExperimentConfig
    environment: EnvironmentFingerprint
    env_digest: str
    blocks: list[dict[str, Any]]
    result: ExperimentResult


class RecordedRound(BaseModel):
    """One `run_experiment` call: the approved experiment, any replicates, and the replication
    verdict the engine computed from the live measurements."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    replicates: list[RecordedReplicate]
    replication: ReplicationResult | None


class MeasurementFixture(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    provenance: Literal["prerecorded"] = "prerecorded"
    case_id: str
    model: str
    recorded_on: str  # the record run's date, written once by record mode
    source_note: str
    rounds: list[RecordedRound]

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not self.rounds:
            raise ValueError("a measurement fixture needs at least one round")
        for round_ in self.rounds:
            if not round_.replicates:
                raise ValueError("a recorded round needs at least one experiment")
            for rep in round_.replicates:
                if rep.result.provenance != "prerecorded":
                    raise ValueError("fixture results must be labelled prerecorded")
                if rep.result.experiment_id != rep.config.experiment_id:
                    raise ValueError("fixture result belongs to another experiment")
        return self

    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self.model_dump(mode="json"))).hexdigest()


def _block_dict(record: BlockRecord) -> dict[str, Any]:
    return dataclasses.asdict(record)


class _CapturingHooks:
    """Passes every call through and keeps what the engine produced."""

    def __init__(self, inner: EngineHooks, sink: dict[str, Any]) -> None:
        self._inner = inner
        self._sink = sink

    def existing(self) -> list[BlockRecord]:
        return self._inner.existing()

    def persist(self, record: BlockRecord) -> None:
        self._sink.setdefault("blocks", []).append(_block_dict(record))
        self._inner.persist(record)

    def progress(self, state: State, **details: Any) -> None:
        self._inner.progress(state, **details)

    def environment(self, env: EnvironmentFingerprint, env_digest: str) -> None:
        self._sink["environment"], self._sink["env_digest"] = env, env_digest
        self._inner.environment(env, env_digest)

    def cancelled(self) -> bool:
        return self._inner.cancelled()


class CapturingMeasure:
    """Record mode: measure for real, and keep the replicates for a fixture.

    The run being recorded already receives the relabelled (`prerecorded`) results and
    blocks: result digests, and so evidence IDs and prompts, include the provenance, and the
    model must be recorded on exactly the evidence the fixture replay will show it. The
    engine still scores (and replicates) on the live measurements, as in any run.
    """

    provenance: Literal["prerecorded"] = "prerecorded"

    def __init__(self) -> None:
        # One entry per round: (captured experiments, replication verdict).
        self.rounds: list[tuple[list[dict[str, Any]], ReplicationResult | None]] = []
        self.resumed = False

    def __call__(
        self,
        config: ExperimentConfig,
        approved: ApprovedExperiment,
        *,
        provisioner: SandboxProvisioner,
        hooks_for: Callable[[ExperimentConfig, int], EngineHooks],
        options: EngineOptions | None = None,
        on_result: Callable[[ExperimentConfig, int, ExperimentResult], None] | None = None,
    ) -> ReplicatedRun:
        captured: list[dict[str, Any]] = []

        def capture_hooks(cfg: ExperimentConfig, index: int) -> EngineHooks:
            sink: dict[str, Any] = {"config": cfg}
            captured.append(sink)
            hooks = hooks_for(cfg, index)
            if hooks.existing():
                self.resumed = True  # a resumed experiment would yield a partial fixture
            return _CapturingHooks(hooks, sink)

        def capture_result(cfg: ExperimentConfig, index: int, result: ExperimentResult) -> None:
            relabelled = result.model_copy(update={"provenance": "prerecorded"})
            captured[index]["result"] = relabelled
            if on_result is not None:
                on_result(cfg, index, relabelled)

        run = run_replicated(
            config,
            approved,
            provisioner=provisioner,
            hooks_for=capture_hooks,
            options=options,
            on_result=capture_result,
        )
        self.rounds.append((captured, run.replication))
        return run

    def fixture(
        self, *, case_id: str, model: str, recorded_on: str, source_note: str
    ) -> MeasurementFixture | None:
        """None when nothing complete was measured (no experiment, or a resumed one)."""
        if not self.rounds or self.resumed:
            return None
        sinks = [sink for captured, _ in self.rounds for sink in captured]
        if not sinks or any({"environment", "result"} - sink.keys() for sink in sinks):
            return None
        return MeasurementFixture(
            case_id=case_id,
            model=model,
            recorded_on=recorded_on,
            source_note=source_note,
            rounds=[
                RecordedRound(
                    replicates=[
                        RecordedReplicate(
                            config=sink["config"],
                            environment=sink["environment"],
                            env_digest=sink["env_digest"],
                            blocks=sink.get("blocks", []),
                            result=sink["result"],
                        )
                        for sink in captured
                    ],
                    replication=replication,
                )
                for captured, replication in self.rounds
            ],
        )


def _rebind(rec: RecordedReplicate, ids: dict[str, uuid.UUID | None]) -> RecordedReplicate:
    config = rec.config.model_copy(
        update={
            "candidates": [
                c.model_copy(update={"candidate_id": ids[c.arm]}) for c in rec.config.candidates
            ]
        }
    )
    blocks = [
        {**b, "candidate_id": str(ids[b["arm"]]) if b.get("candidate_id") else None}
        for b in rec.blocks
    ]
    return rec.model_copy(update={"config": config, "blocks": blocks})


class FixtureMeasure:
    """Fixture mode: the recorded replicates instead of the engine (no sandbox DDL or query).

    A mismatch raises `MeasurementFixtureMismatchError` (the graph records the experiment as
    failed) and is also kept in `mismatch`, which the eval reports as a failure.
    """

    provenance: Literal["prerecorded"] = "prerecorded"

    def __init__(self, fixture: MeasurementFixture) -> None:
        self.fixture = fixture
        self.mismatch: str | None = None
        self.calls = 0

    def unused_rounds(self) -> int:
        return len(self.fixture.rounds) - self.calls

    def _fail(self, detail: str) -> MeasurementFixtureMismatchError:
        self.mismatch = self.mismatch or detail
        return MeasurementFixtureMismatchError(
            f"The measurement fixture does not match this run ({detail}); re-record the case."
        )

    def __call__(
        self,
        config: ExperimentConfig,
        approved: ApprovedExperiment,
        *,
        provisioner: SandboxProvisioner | None = None,
        hooks_for: Callable[[ExperimentConfig, int], EngineHooks],
        options: EngineOptions | None = None,
        on_result: Callable[[ExperimentConfig, int, ExperimentResult], None] | None = None,
    ) -> ReplicatedRun:
        self.calls += 1
        if self.calls > len(self.fixture.rounds):
            raise self._fail(
                f"the run measured round {self.calls}; the fixture holds {len(self.fixture.rounds)}"
            )
        recorded_round = self.fixture.rounds[self.calls - 1]
        done: list[Replicate] = []
        # Candidate row ids are generated per run; arms are matched by their deterministic key
        # (and below by the approved SQL digest), never by id.
        ids = {c.arm: c.candidate_id for c in config.candidates}
        for index, recorded in enumerate(recorded_round.replicates):
            if any(c.arm not in ids for c in recorded.config.candidates):
                raise self._fail(f"experiment {index} measured arms this run did not approve")
            rec = _rebind(recorded, ids)
            expected = (
                config
                if index == 0
                else replicate_config(config, index, [c.arm for c in rec.config.candidates])
            )
            if canonical_json(expected.model_dump(mode="json")) != canonical_json(
                rec.config.model_dump(mode="json")
            ):
                raise self._fail(f"experiment {index} config differs from the recorded one")
            for arm in rec.config.candidates:
                if approved.approved_sql.get(arm.arm) != sql_digest(arm):
                    raise self._fail(f"{arm.arm} is not the approved SQL")
            hooks = hooks_for(rec.config, index)
            hooks.progress("measuring", prerecorded=True)
            hooks.environment(rec.environment, rec.env_digest)
            for block in rec.blocks:
                hooks.persist(BlockRecord(**block))
            hooks.progress("scoring", prerecorded=True)
            if on_result is not None:
                on_result(rec.config, index, rec.result)
            done.append(Replicate(config=rec.config, result=rec.result))
        # The replication verdict was computed from the live measurements when the case was
        # recorded. The frozen rules never count prerecorded evidence as a replicate, so it is
        # not recomputed from the relabelled results; instead it must still follow from the
        # stored results under those rules (checked on copies relabelled as measured, for
        # this comparison only), and the recorded verdict is what the run receives.
        replication = recorded_round.replication
        as_measured = [
            Replicate(
                config=r.config, result=r.result.model_copy(update={"provenance": "measured"})
            )
            for r in done
        ]
        check = assess_all(as_measured) if eligible_arms(as_measured[0].result) else None
        if (check is None) != (replication is None) or (
            check is not None
            and replication is not None
            and canonical_json(check.model_dump(mode="json"))
            != canonical_json(replication.model_dump(mode="json"))
        ):
            raise self._fail("the recorded replication verdicts do not follow from its results")
        return ReplicatedRun(replicates=done, replication=replication)
