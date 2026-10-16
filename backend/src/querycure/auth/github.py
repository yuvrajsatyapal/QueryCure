"""GitHub OAuth (authorization-code flow with state and PKCE; ADR-0013, T5.1).

Only the numeric GitHub user id (the stable subject) and the login (display name) are kept.
The access token is used for one `GET /user` and then discarded: QueryCure asks for no scopes
beyond public profile data and never stores provider tokens.
"""

from urllib.parse import urlencode

import httpx

from querycure.auth.oauth import OAuthError, OAuthIdentity, challenge

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"  # noqa: S105 - an endpoint, not a secret
USER_URL = "https://api.github.com/user"
TIMEOUT_SECONDS = 10.0


def authorize_url(*, client_id: str, redirect_uri: str, state: str, verifier: str) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "read:user",
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
        user_response = await http.get(
            USER_URL,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=TIMEOUT_SECONDS,
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
    return OAuthIdentity(subject=str(user_id), display_name=login[:100])
