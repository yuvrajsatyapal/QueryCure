"""Profile `qc-raw-v1`: user-submitted text kept byte-for-byte (SQL, DDL uploads). FROZEN."""

from querycure.replay.canonical.errors import CanonicalizationError

PROFILE = "qc-raw-v1"
_BOM = b"\xef\xbb\xbf"


def canonical_raw(data: bytes) -> bytes:
    if data.startswith(_BOM):
        raise CanonicalizationError("byte order mark is not allowed")
    try:
        data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CanonicalizationError("input is not valid UTF-8") from exc
    return data
