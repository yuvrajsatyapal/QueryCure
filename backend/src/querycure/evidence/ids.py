import hashlib
import uuid

ID_HEX_CHARS = 12


def evidence_id(run_id: uuid.UUID, kind: str, artifact_sha256: str | None, locator: str) -> str:
    """`ev_` + 12 hex of sha256(run_id|kind|artifact_sha|locator) (DATABASE_DESIGN §4 evidence).

    Deterministic, so re-running a node after a crash inserts nothing new.
    """
    material = f"{run_id}|{kind}|{artifact_sha256 or ''}|{locator}"
    return "ev_" + hashlib.sha256(material.encode()).hexdigest()[:ID_HEX_CHARS]


def keyed_id(prefix: str, *parts: object) -> str:
    """Deterministic `fd_…` / `hy_…` keys for findings and hypotheses."""
    material = "|".join(str(p) for p in parts)
    return f"{prefix}_" + hashlib.sha256(material.encode()).hexdigest()[:ID_HEX_CHARS]
