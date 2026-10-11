from typing import Annotated

from fastapi import APIRouter, Path, Response

from querycure.api.deps import ConnDep, CurrentUser
from querycure.core.errors import NotFoundError
from querycure.db.repositories.artifacts import owned_by
from querycure.replay.artifact_store import get_artifact

router = APIRouter(tags=["artifacts"])


@router.get("/artifacts/{sha256}", response_class=Response)
async def get_artifact_content(
    sha256: Annotated[str, Path(pattern=r"^[0-9a-f]{64}$")], conn: ConnDep, user: CurrentUser
) -> Response:
    """Exact stored bytes, re-verified against the digest on read."""
    if not await owned_by(conn, user_id=user.id, sha256=sha256):
        raise NotFoundError("Artifact not found.")
    artifact = await get_artifact(conn, sha256)
    if artifact is None:
        raise NotFoundError("Artifact not found.")
    return Response(content=artifact.content, media_type=artifact.media_type)
