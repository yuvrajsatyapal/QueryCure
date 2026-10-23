"""GitHub OAuth (authorization-code flow with state and PKCE; ADR-0013, T5.1).

Only the numeric GitHub user id (the stable subject) and the login (display name) are kept.
The access token is used for one `GET /user` and then discarded: QueryCure asks for no scopes
beyond public profile data and never stores provider tokens. While access is restricted
(ADR-0031), `user:email` is added and `GET /user/emails` is read; only verified addresses count.
"""

from urllib.parse import urlencode

import httpx

from querycure.auth.oauth import OAuthError, OAuthIdentity, challenge

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105 - an endpoint, not a secret
USER_URL = "https://api.github.com/user"
EMAILS_URL = "https://api.github.com/user/emails"
TIMEOUT_SECONDS = 10.0


def authorize_url(
    *, client_id: str, redirect_uri: str, state: str, verifier: str, with_email: bool = False
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user user:email" if with_email else "read:user",
            "state": state,
            "code_challenge": challenge(verifier),
            "code_challenge_method": "S256",
            "allow_signup": "true",
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
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        user_response = await http.get(USER_URL, headers=headers, timeout=TIMEOUT_SECONDS)
        emails_response = (
            await http.get(EMAILS_URL, headers=headers, timeout=TIMEOUT_SECONDS)
            if with_email
            else None
        )
    except httpx.HTTPError as exc:
        raise OAuthError("provider_unreachable") from exc
    if user_response.status_code != 200:
        raise OAuthError("profile_unavailable")
    profile = user_response.json()
    user_id, login = profile.get("id"), profile.get("login")
    if not isinstance(user_id, int) or not isinstance(login, str):
        raise OAuthError("profile_unavailable")
    # numeric id as the subject: logins can be renamed, ids cannot
    return OAuthIdentity(
        subject=str(user_id),
        display_name=login[:100],
        verified_emails=_verified(emails_response),
    )


def _verified(response: httpx.Response | None) -> frozenset[str]:
    """Any verified address, not only the primary: an invited work address is often secondary.
    An unreadable list yields no addresses, which a restricted deployment then refuses."""
    if response is None or response.status_code != 200:
        return frozenset()
    entries = response.json()
    if not isinstance(entries, list):
        return frozenset()
    return frozenset(
        entry["email"].strip().lower()
        for entry in entries
        if isinstance(entry, dict)
        and isinstance(entry.get("email"), str)
        and entry.get("verified") is True
    )
