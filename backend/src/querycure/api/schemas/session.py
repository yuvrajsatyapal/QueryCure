import uuid

from pydantic import BaseModel

from querycure.core.config import Profile
from querycure.domain.users import User, UserKind


class UserOut(BaseModel):
    id: uuid.UUID
    kind: UserKind
    display_name: str | None

    @classmethod
    def from_user(cls, user: User) -> "UserOut":
        return cls(id=user.id, kind=user.kind, display_name=user.display_name)


class SessionResponse(BaseModel):
    user: UserOut


class Features(BaseModel):
    live_inspection: bool
    sandbox: bool


class MeResponse(BaseModel):
    user: UserOut
    profile: Profile
    features: Features
