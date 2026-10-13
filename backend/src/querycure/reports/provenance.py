"""Unlabeled-number scan for rendered reports (ROADMAP Phase 4 acceptance #4).

A line of report Markdown that shows a number must also say where the number came from: one
of the renderer's provenance labels. Code spans, fenced code, headings, table separators and
identifiers (evidence/candidate/hypothesis keys, digests, UUIDs) are not quantitative claims
and are ignored.
"""

import re

from querycure.reports.renderers.md_v1 import PROVENANCE_LABELS

_CODE_SPAN = re.compile(r"`[^`]*`")
_IDENTIFIER = re.compile(
    r"\b(?:ev|oc|hy|fd)_[0-9a-f]{12}\b"
    r"|\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    r"|sha256:[0-9a-f]{64}"
)
_DIGIT = re.compile(r"\d")


def unlabeled_numbers(markdown: str) -> list[str]:
    """Lines with a number but no provenance label (empty list = the report passes)."""
    bad: list[str] = []
    fenced = False
    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced or line.startswith("#") or set(line) <= set("|-: "):
            continue
        visible = _IDENTIFIER.sub("", _CODE_SPAN.sub("", line))
        if _DIGIT.search(visible) and not any(label in visible for label in PROVENANCE_LABELS):
            bad.append(raw)
    return bad
