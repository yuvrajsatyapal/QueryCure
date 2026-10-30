"""Released report builders and Markdown renderers (REPLAY_ENGINE §7, ADR-0015).

Released versions are frozen: a change in output bytes means a new version, never an edit.
Retiring a version needs a DECISIONS.md entry; replay then skips its rebuild check
(`verified_stored_only` with a warning) instead of failing.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from querycure.reports.builders import v1 as builder_v1
from querycure.reports.builders import v2 as builder_v2
from querycure.reports.inputs import ReportInputs
from querycure.reports.renderers import md_v1, md_v2

Builder = Callable[..., dict[str, Any]]
Renderer = Callable[[dict[str, Any]], str]

BUILDERS: dict[str, Builder] = {
    builder_v1.BUILDER_VERSION: builder_v1.build_report,
    builder_v2.BUILDER_VERSION: builder_v2.build_report,
}
RENDERERS: dict[str, Renderer] = {
    md_v1.MD_RENDERER_VERSION: md_v1.render_markdown,
    md_v2.MD_RENDERER_VERSION: md_v2.render_markdown,
}
# None retired yet (D10: keep all versions).
RETIRED_BUILDERS: frozenset[str] = frozenset()
RETIRED_RENDERERS: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ReportVersions:
    """One sealing contract: a builder, the renderer released with it, and the schema it emits."""

    builder: str
    renderer: str
    schema_version: int


class UnsupportedReportVersionError(ValueError):
    """A report version that cannot seal: unknown, retired, or not released together."""


CONTRACTS: dict[str, ReportVersions] = {
    builder_v1.BUILDER_VERSION: ReportVersions(
        builder_v1.BUILDER_VERSION, md_v1.MD_RENDERER_VERSION, builder_v1.REPORT_SCHEMA_VERSION
    ),
    builder_v2.BUILDER_VERSION: ReportVersions(
        builder_v2.BUILDER_VERSION, md_v2.MD_RENDERER_VERSION, builder_v2.REPORT_SCHEMA_VERSION
    ),
}
# Replays created before the source snapshot keep the contract they were created under
# (REPLAY_OUTCOME_AUDIT §18.4).
LEGACY_REPORT_VERSIONS = CONTRACTS[builder_v1.BUILDER_VERSION]

# ADR-0032 activation: every new report is report-builder@2 / report-md@2 / schema 2.
CURRENT_BUILDER = builder_v2.BUILDER_VERSION
CURRENT_RENDERER = md_v2.MD_RENDERER_VERSION
CURRENT_SCHEMA_VERSION = builder_v2.REPORT_SCHEMA_VERSION


def current_versions() -> ReportVersions:
    return ReportVersions(CURRENT_BUILDER, CURRENT_RENDERER, CURRENT_SCHEMA_VERSION)


def check_versions(versions: ReportVersions) -> ReportVersions:
    """The contract to seal with, or an error; never a substitute (no silent downgrade)."""
    if versions.builder not in BUILDERS or versions.builder in RETIRED_BUILDERS:
        raise UnsupportedReportVersionError(
            f"report builder {versions.builder!r} is not available for sealing"
        )
    if versions.renderer not in RENDERERS or versions.renderer in RETIRED_RENDERERS:
        raise UnsupportedReportVersionError(
            f"report renderer {versions.renderer!r} is not available for sealing"
        )
    released = CONTRACTS.get(versions.builder)
    if released != versions:
        raise UnsupportedReportVersionError(
            f"{versions.builder} seals only with {released}, not {versions}"
        )
    return versions


def build(
    version: str, inputs: ReportInputs, *, finalized_at: str, cutoff_seq: int, events_digest: str
) -> dict[str, Any]:
    return BUILDERS[version](
        inputs, finalized_at=finalized_at, cutoff_seq=cutoff_seq, events_digest=events_digest
    )
