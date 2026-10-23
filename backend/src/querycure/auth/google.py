"""Google sign-in (OpenID Connect authorization-code flow with state and PKCE; ADR-0013).

Only the `sub` claim (Google's stable, never-reused account id) and the display name are kept.
The scope is `openid profile`: no email address is requested or stored, except while access
is restricted (ADR-0031), when `email` is added and only an address Google marks verified
counts. The access token is used
for one userinfo call over TLS and then discarded; provider tokens are never stored. The profile
comes from the userinfo endpoint rather than from an unverified ID token.
"""

from urllib.parse import urlencode

import httpx

from querycure.auth.oauth import OAuthError, OAuthIdentity, challenge

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a secret
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
TIMEOUT_SECONDS = 10.0
FALLBACK_NAME = "Google user"


def authorize_url(
    *, client_id: str, redirect_uri: str, state: str, verifier: str, with_email: bool = False
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": "openid email profile" if with_email else "openid profile",
            "state": state,
            "code_challenge": challenge(verifier),
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


async def exchange(
    http: httpx.AsyncClient,
    *,
    client_id: str,
    client_secret: str,
    redirect_uri: str,
    code: str,
    verifier: str,
    with_email: bool = False,
) -> OAuthIdentity:
    try:
        token_response = await http.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
            },
            headers={"Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
        body = token_response.json() if token_response.status_code == 200 else {}
        token = body.get("access_token") if isinstance(body, dict) else None
        if not isinstance(token, str) or not token:
            raise OAuthError("token_exchange_failed")
        profile_response = await http.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise OAuthError("provider_unreachable") from exc
    if profile_response.status_code != 200:
        raise OAuthError("profile_unavailable")
    profile = profile_response.json()
    subject = profile.get("sub") if isinstance(profile, dict) else None
    if not isinstance(subject, str) or not subject:
        raise OAuthError("profile_unavailable")
    name = profile.get("name")
    display = name.strip()[:100] if isinstance(name, str) and name.strip() else FALLBACK_NAME
    emails: frozenset[str] = frozenset()
    email = profile.get("email")
    # `is True`: a missing or string "true" claim must not count as verified.
    if with_email and isinstance(email, str) and profile.get("email_verified") is True:
        emails = frozenset({email.strip().lower()})
    return OAuthIdentity(subject=subject, display_name=display, verified_emails=emails)
