"""
Email verification tokens.

A token is the user's id and *current email*, signed with SECRET_KEY and timestamped
(django.core.signing). That makes it:

- stateless: no table, nothing to clean up;
- expiring: rejected after EMAIL_VERIFICATION_TIMEOUT seconds;
- bound to the address: if the email changes, links sent to the old address stop working;
- tamper-proof: editing the uid or email breaks the signature.

Verifying twice is harmless (idempotent), so the token doesn't need to be single-use.
"""

from django.conf import settings
from django.core import signing

from .models import User

_SALT = "pleet.accounts.email-verification"


class InvalidVerificationToken(Exception):
    pass


def make_token(user: User) -> str:
    return signing.dumps({"uid": str(user.pk), "email": user.email}, salt=_SALT, compress=True)


def user_from_token(token: str) -> User:
    try:
        data = signing.loads(token, salt=_SALT, max_age=settings.EMAIL_VERIFICATION_TIMEOUT)
    except signing.BadSignature as exc:  # includes SignatureExpired
        raise InvalidVerificationToken from exc
    user = User.objects.filter(pk=data.get("uid"), is_active=True).first()
    if user is None or user.email != data.get("email"):
        raise InvalidVerificationToken
    return user


def verification_link(user: User) -> str:
    return f"{settings.FRONTEND_URL}/auth/verify-email?token={make_token(user)}"
