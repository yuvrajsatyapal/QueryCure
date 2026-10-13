"""Released report builders and Markdown renderers (REPLAY_ENGINE §7, ADR-0015).

Released versions are frozen: a change in output bytes means a new version, never an edit.
Retiring a version needs a DECISIONS.md entry; replay then skips its rebuild check
(`verified_stored_only` with a warning) instead of failing.
"""

from collections.abc import Callable
from typing import Any

from querycure.reports.builders import v1 as builder_v1
from querycure.reports.inputs import ReportInputs
from querycure.reports.renderers import md_v1

Builder = Callable[..., dict[str, Any]]
Renderer = Callable[[dict[str, Any]], str]

BUILDERS: dict[str, Builder] = {builder_v1.BUILDER_VERSION: builder_v1.build_report}
RENDERERS: dict[str, Renderer] = {md_v1.MD_RENDERER_VERSION: md_v1.render_markdown}
# None retired yet (D10: keep all versions).
RETIRED_BUILDERS: frozenset[str] = frozenset()
RETIRED_RENDERERS: frozenset[str] = frozenset()

CURRENT_BUILDER = builder_v1.BUILDER_VERSION
CURRENT_RENDERER = md_v1.MD_RENDERER_VERSION
CURRENT_SCHEMA_VERSION = builder_v1.REPORT_SCHEMA_VERSION


def build(
    version: str, inputs: ReportInputs, *, finalized_at: str, cutoff_seq: int, events_digest: str
) -> dict[str, Any]:
    return BUILDERS[version](
        inputs, finalized_at=finalized_at, cutoff_seq=cutoff_seq, events_digest=events_digest
    )
