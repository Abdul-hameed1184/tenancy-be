"""
JWT minting and parsing. simplejwt does the cryptography; this module only decides which
claims go into each token.

Access token:   {token_type: access,  user_id, sid, jti, exp, iss}
Refresh token:  {token_type: refresh, user_id, sid, jti, exp, iss}
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from django.utils import timezone
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


@dataclass(frozen=True)
class IssuedRefresh:
    token: str
    jti: str


@dataclass(frozen=True)
class RefreshClaims:
    session_id: str
    jti: str
    user_id: str


class InvalidRefreshToken(Exception):
    pass


def issue_access_token(user, session_id) -> str:
    token = AccessToken.for_user(user)
    token["sid"] = str(session_id)
    return str(token)


def issue_refresh_token(user, session_id, expires_at: datetime) -> IssuedRefresh:
    token = RefreshToken.for_user(user)
    token["sid"] = str(session_id)
    # Bound by the session's absolute expiry, not a fresh full lifetime from "now".
    token.set_exp(lifetime=max(expires_at - timezone.now(), timedelta(0)))
    return IssuedRefresh(token=str(token), jti=token["jti"])


def parse_refresh_token(raw: str) -> RefreshClaims:
    try:
        token = RefreshToken(raw)  # verifies signature, expiry and token_type
    except TokenError as exc:
        raise InvalidRefreshToken(str(exc)) from exc
    try:
        return RefreshClaims(
            session_id=token["sid"], jti=token["jti"], user_id=str(token["user_id"])
        )
    except KeyError as exc:
        raise InvalidRefreshToken("Refresh token is missing required claims.") from exc
