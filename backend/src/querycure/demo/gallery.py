"""Public demo gallery (T5.5, DEPLOYMENT §1): prerecorded investigations, honestly labelled.

A demo bundle is a sealed run exported from a deterministic eval replay: real answers
recorded from the pinned free model, measurements recorded live in the local sandbox (via
measurement fixtures, ADR-0024), and the finalized report, manifest and selected artifacts
exactly as stored. Nothing in a bundle is re-run or re-measured when shown.

`verify_bundle` recomputes the profile-tagged SHA-256 of every exported artifact
(`replay.digest`, the frozen REPLAY_ENGINE §2.3 rule) and checks it against the run's
manifest. That proves the exported bytes are consistent with the manifest digest. It is
neither a full report replay (that needs the run's database records, which a bundle does not
ship) nor proof of authenticity (REPLAY_ENGINE §6).
"""

import base64
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from querycure.benchmark.fixtures import PrerecordedExperiment, load_prerecorded
from querycure.replay.digest import digest

BUNDLES_DIR = Path(__file__).parent / "bundles"
FIXTURES_DIR = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "experiments"
# Artifact roles a bundle carries: what the report view, plan explorer and benchmark
# comparison need. Raw agent outputs stay out (the report already quotes what it uses).
EXPORTED_ROLES = frozenset(
    {
        "input.query",
        "input.param_sets",
        "input.plan",
        "input.schema",
        "context.plan",
        "context.schema_snapshot",
        "experiment.config",
        "experiment.result",
        "experiment.replication",
    }
)


class BundleArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    kind: str
    role: str
    profile: Literal["qc-json-v1", "qc-text-v1", "qc-raw-v1"]
    content_b64: str


class BundleSource(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    eval_case: str
    model: str
    recorded_at: str | None  # model answers
    measurements_recorded_on: str | None  # sandbox measurements (Mode C only)
    recording_sha256: str | None
    measurement_fixture_sha256: str | None
    prompt_versions: dict[str, str]
    scoring_version: str


class DemoBundle(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = 1
    provenance: Literal["prerecorded"] = "prerecorded"
    slug: str = Field(pattern=r"^[a-z0-9_-]{3,64}$")
    title: str
    summary: str
    label: str  # shown on every page that displays the bundle
    source: BundleSource
    run_id: str
    outcome: str | None
    manifest_sha256: str
    manifest_b64: str
    report_json_sha256: str
    report_md_sha256: str
    report_json_b64: str
    report_md_b64: str
    artifacts: list[BundleArtifact]

    def report(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(base64.b64decode(self.report_json_b64))
        return value

    def manifest(self) -> dict[str, Any]:
        value: dict[str, Any] = json.loads(base64.b64decode(self.manifest_b64))
        return value


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def _ref(value: str | None) -> str | None:
    return value.removeprefix("sha256:") if isinstance(value, str) else None


def verify_bundle(bundle: DemoBundle) -> list[Check]:
    checks: list[Check] = []
    manifest_bytes = base64.b64decode(bundle.manifest_b64)
    manifest_digest = digest("qc-json-v1", manifest_bytes)
    checks.append(
        Check("manifest", manifest_digest == bundle.manifest_sha256, f"sha256:{manifest_digest}")
    )
    manifest = json.loads(manifest_bytes)
    report = manifest.get("report", {})
    for name, profile, raw, expected, listed in (
        ("report_json", "qc-json-v1", bundle.report_json_b64, bundle.report_json_sha256,
         _ref(report.get("json"))),
        ("report_md", "qc-text-v1", bundle.report_md_b64, bundle.report_md_sha256,
         _ref(report.get("markdown"))),
    ):  # fmt: skip
        actual = digest(profile, base64.b64decode(raw))
        checks.append(
            Check(name, actual == expected == listed, f"sha256:{actual} (manifest: {listed})")
        )
    listed_digests = {_ref(a.get("digest")) for a in manifest.get("artifacts", [])}
    for exp in manifest.get("experiments", []):
        listed_digests |= {_ref(exp.get("config")), _ref(exp.get("result"))}
    for art in bundle.artifacts:
        actual = digest(art.profile, base64.b64decode(art.content_b64))
        ok = actual == art.sha256 and art.sha256 in listed_digests
        checks.append(Check(f"artifact:{art.role}", ok, f"sha256:{actual}"))
    return checks


@cache
def load_bundles(directory: Path = BUNDLES_DIR) -> tuple[DemoBundle, ...]:
    """Every bundle shipped with the package, newest recording first. Refuses anything that
    is not labelled prerecorded (the model validation)."""
    bundles = [
        DemoBundle.model_validate_json(p.read_text()) for p in sorted(directory.glob("*.json"))
    ]
    return tuple(sorted(bundles, key=lambda b: b.slug))


@cache
def load_benchmark_fixtures(directory: Path = FIXTURES_DIR) -> tuple[PrerecordedExperiment, ...]:
    if not directory.exists():
        return ()
    return tuple(load_prerecorded(p) for p in sorted(directory.glob("*.json")))
