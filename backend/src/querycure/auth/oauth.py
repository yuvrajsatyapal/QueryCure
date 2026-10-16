"""Pieces shared by the OAuth providers: the failure type, the identity both reduce to, and the
state / PKCE helpers (RFC 7636, S256)."""

import base64
import hashlib
import secrets
from dataclasses import dataclass


class OAuthError(Exception):
    """A failed exchange. `code` is a stable reason for the redirect; never a provider body."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class OAuthIdentity:
    subject: str  # the provider's stable id: display names and logins can change, this cannot
    display_name: str


def new_state() -> str:
    return secrets.token_urlsafe(32)


def new_verifier() -> str:
    return secrets.token_urlsafe(48)


def challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode()).digest()
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")
