"""Restricted trial access (ADR-0031): who may hold a session while RESTRICTED_ACCESS is on.

Admission is decided from the provider-verified email stored at sign-in, on every request, so
removing an address from ACCESS_ALLOWLIST (and restarting) revokes existing sessions too.
"""

from querycure.auth.oauth import OAuthIdentity
from querycure.core.config import Settings
from querycure.core.errors import AccessDeniedError, UnauthenticatedError
from querycure.domain.users import User, UserKind

DENIED = "This trial is limited to approved accounts."


def approved_email(settings: Settings, identity: OAuthIdentity) -> str | None:
    """The first verified address on the list (sorted, so the choice is stable), if any."""
    return min(identity.verified_emails & settings.allowed_emails, default=None)


def admit(settings: Settings, user: User | None) -> User:
    if user is None:
        raise UnauthenticatedError("Sign in to continue.")
    if not settings.restricted_access:
        return user
    if user.kind is not UserKind.OAUTH:
        # Anonymous or local sessions from before the restriction: sign in instead.
        raise UnauthenticatedError("Sign in to continue.")
    if user.email is None or user.email not in settings.allowed_emails:
        raise AccessDeniedError(DENIED)
    return user
