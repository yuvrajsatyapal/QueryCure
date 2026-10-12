"""Prerecorded experiment fixtures for the public demo (DEPLOYMENT §1, T3.13).

A fixture is a real local-profile experiment (config, environment fingerprint, result)
relabelled `provenance = "prerecorded"` at every layer, with a human label naming the
hardware and date. The loader refuses anything that is not prerecorded, so the demo can
never present these samples as measured on the viewer's database, and the verdict engine
never mixes them with measured ones.

    python -m querycure.benchmark.fixtures OUT.json --config C.json --environment E.json \
        --result R.json --recorded-on 2026-10-12 --note "local Docker Desktop, sandbox worker"
"""

import argparse
import json
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from querycure.domain.benchmark import EnvironmentFingerprint, ExperimentConfig, ExperimentResult


class PrerecordedExperiment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    provenance: Literal["prerecorded"] = "prerecorded"
    recorded_on: str  # date the experiment ran (from the record, never the clock)
    source_note: str
    label: str
    config: ExperimentConfig
    environment: EnvironmentFingerprint
    result: ExperimentResult

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.result.provenance != "prerecorded":
            raise ValueError("fixture results must be labelled prerecorded")
        if self.result.experiment_id != self.config.experiment_id:
            raise ValueError("fixture result belongs to another experiment")
        return self


def demo_label(environment: EnvironmentFingerprint, recorded_on: str) -> str:
    return (
        f"Prerecorded on {environment.cpu_arch} ({environment.cpu_count} CPUs), "
        f"{environment.os.split()[0]}, {recorded_on} — not your database"
    )


def to_prerecorded(
    config: ExperimentConfig,
    environment: EnvironmentFingerprint,
    result: ExperimentResult,
    *,
    recorded_on: str,
    source_note: str,
) -> PrerecordedExperiment:
    if result.experiment_id != config.experiment_id:
        raise ValueError("result and config describe different experiments")
    return PrerecordedExperiment(
        recorded_on=recorded_on,
        source_note=source_note,
        label=demo_label(environment, recorded_on),
        config=config,
        environment=environment,
        result=result.model_copy(update={"provenance": "prerecorded"}),
    )


def load_prerecorded(path: Path) -> PrerecordedExperiment:
    """Import is where provenance is enforced: measured evidence is refused."""
    return PrerecordedExperiment.model_validate_json(path.read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--environment", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--recorded-on", required=True)
    parser.add_argument("--note", required=True)
    args = parser.parse_args()
    fixture = to_prerecorded(
        ExperimentConfig.model_validate_json(args.config.read_text()),
        EnvironmentFingerprint.model_validate_json(args.environment.read_text()),
        ExperimentResult.model_validate(json.loads(args.result.read_text())),
        recorded_on=args.recorded_on,
        source_note=args.note,
    )
    args.out.write_text(fixture.model_dump_json(indent=1) + "\n")


if __name__ == "__main__":
    main()
