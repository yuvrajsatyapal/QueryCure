import hashlib

from querydoctor.replay.canonical.errors import CanonicalizationError

# qd-events-v1 is the event-log digest stream (REPLAY_ENGINE §5).
# qd-row-v1 hashes result rows, not artifacts, so it is not listed here.
PROFILES = frozenset({"qd-json-v1", "qd-text-v1", "qd-raw-v1", "qd-events-v1"})


def digest(profile: str, canonical_bytes: bytes) -> str:
    """SHA-256(profile ‖ LF ‖ canonical bytes), lowercase hex (REPLAY_ENGINE §2.3)."""
    if profile not in PROFILES:
        raise CanonicalizationError(f"unknown profile {profile!r}")
    return hashlib.sha256(profile.encode("ascii") + b"\n" + canonical_bytes).hexdigest()
