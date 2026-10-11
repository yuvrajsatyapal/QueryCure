"""Profile `qd-text-v1`: text QueryDoctor generates (report Markdown). FROZEN."""

from querydoctor.replay.canonical.errors import CanonicalizationError

PROFILE = "qd-text-v1"


def canonical_text(text: str) -> bytes:
    if text.startswith("﻿"):
        raise CanonicalizationError("byte order mark is not allowed")
    try:
        text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise CanonicalizationError("text contains a lone surrogate") from exc
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n") + "\n"
    return normalized.encode("utf-8")
