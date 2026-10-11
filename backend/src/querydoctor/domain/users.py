import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class UserKind(StrEnum):
    LOCAL = "local"
    ANONYMOUS = "anonymous"
    OAUTH = "oauth"


class User(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    kind: UserKind
    display_name: str | None = None
