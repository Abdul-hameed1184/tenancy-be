"""
Account and session business operations. Views call these; nothing here knows about HTTP
beyond reading client metadata from the request for audit/session records.
"""

import logging
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.agents.models import AgentProfile
from apps.audit.services import Action, record
from apps.common.cache import invalidate_on_commit
from apps.common.events import publish
from apps.common.request import client_ip, user_agent

from . import tokens, verification
from .events import UserRegistered
from .models import AuthSession, User

logger = logging.getLogger(__name__)

SELF_REGISTERABLE_ROLES = {User.Role.LANDLORD, User.Role.AGENT, User.Role.TENANT}


class AuthError(Exception):
    """Credentials or session rejected. The message is safe to show to the client."""

class VerificationError(Exception):
    """Veriy your account before you can login """


class InvalidResetToken(Exception):
    pass


class DuplicateEmail(Exception):
    pass


@dataclass(frozen=True)
class SessionTokens:
    access: str
    refresh: str
    session: AuthSession


# --- Registration & login -----------------------------------------------------------------


def register_user(*, name: str, email: str, password: str, role: str, request=None) -> User:
    if role not in SELF_REGISTERABLE_ROLES:
        raise ValueError("Admins cannot self-register.")
    try:
        with transaction.atomic():
            user = User.objects.create_user(email=email, password=password, name=name, role=role)
            if role == User.Role.AGENT:
                AgentProfile.objects.create(user=user)
                invalidate_on_commit("agents")
            record(Action.USER_REGISTERED, actor=user, entity=user, request=request)
            publish(UserRegistered(user_id=str(user.pk), role=role))
    except IntegrityError as exc:
        # Two concurrent sign-ups with the same email both pass serializer validation; the
        # unique index is what actually decides, and the loser lands here.
        raise DuplicateEmail from exc
    return user


GENERIC_LOGIN_ERROR = "Invalid email or password."


def login(*, email: str, password: str, role: str | None = None, request=None) -> User:
    # `role` (the login tab the user picked) is deliberately ignored: the account's real
    # role is returned in the response and the frontend routes by it.
    # authenticate() runs the password hasher even for unknown emails, so response time
    # doesn't reveal whether an account exists.
    user = authenticate(request, email=email, password=password)
    if user is None:
        record(Action.LOGIN_FAILED, metadata={"email": email.strip().lower()}, request=request)
        raise AuthError(GENERIC_LOGIN_ERROR)

    if not user.is_email_verified:
        # Re-queue a fresh verification email so the user can act immediately.
        resend_verification(user, request)
        raise VerificationError(
            "Please verify your email address before logging in. "
            "We've resent the verification link to your inbox."
        )

    User.objects.filter(pk=user.pk).update(last_login=timezone.now())
    record(Action.LOGIN, actor=user, entity=user, request=request)
    return user


# --- Sessions -------------------------------------------------------------------------------


def start_session(user: User, request=None) -> SessionTokens:
    expires_at = timezone.now() + settings.JWT_REFRESH_TOKEN_LIFETIME
    session = AuthSession(
        user=user,
        expires_at=expires_at,
        ip_address=client_ip(request) if request is not None else None,
        user_agent=user_agent(request) if request is not None else "",
    )
    refresh = tokens.issue_refresh_token(user, session.id, expires_at)
    session.current_jti = refresh.jti
    session.save()
    return SessionTokens(
        access=tokens.issue_access_token(user, session.id), refresh=refresh.token, session=session
    )


def rotate_session(raw_refresh: str, request=None) -> SessionTokens:
    """
    Exchange a refresh token for a new access + refresh pair.

    SELECT ... FOR UPDATE on the session row serialises concurrent refreshes of the same
    session: the first swaps current_jti, the second then sees a mismatch and is treated as
    reuse. Without the lock both could read the old jti and both succeed, leaving two valid
    refresh tokens for one session.
    """
    try:
        claims = tokens.parse_refresh_token(raw_refresh)
    except tokens.InvalidRefreshToken as exc:
        raise AuthError("Your session has expired. Please log in again.") from exc

    reuse_detected = False
    with transaction.atomic():
        session = (
            AuthSession.objects.select_for_update()
            .select_related("user")
            .filter(id=claims.session_id, user_id=claims.user_id)
            .first()
        )
        if session is None or session.revoked_at or session.expires_at <= timezone.now():
            raise AuthError("Your session has expired. Please log in again.")
        if not session.user.is_active:
            raise AuthError("Your session has expired. Please log in again.")

        if claims.jti != session.current_jti:
            _revoke(session, AuthSession.RevokeReason.REUSE_DETECTED)
            record(
                Action.TOKEN_REUSE_DETECTED,
                actor=session.user,
                entity=session,
                request=request,
            )
            reuse_detected = True
        else:
            refresh = tokens.issue_refresh_token(session.user, session.id, session.expires_at)
            session.current_jti = refresh.jti
            session.last_refreshed_at = timezone.now()
            session.save(update_fields=["current_jti", "last_refreshed_at"])

    # Raised outside the atomic block so the revocation above is committed, not rolled back.
    if reuse_detected:
        logger.warning(
            "Refresh token reuse detected; session revoked", extra={"sid": claims.session_id}
        )
        raise AuthError("Your session has expired. Please log in again.")

    return SessionTokens(
        access=tokens.issue_access_token(session.user, session.id),
        refresh=refresh.token,
        session=session,
    )


def logout(user: User, session_id, request=None) -> None:
    with transaction.atomic():
        session = AuthSession.objects.select_for_update().filter(id=session_id, user=user).first()
        if session and session.revoked_at is None:
            _revoke(session, AuthSession.RevokeReason.LOGOUT)
        record(Action.LOGOUT, actor=user, entity=user, request=request)


def revoke_all_sessions(user: User, reason: str) -> int:
    return AuthSession.objects.filter(user=user, revoked_at__isnull=True).update(
        revoked_at=timezone.now(), revoke_reason=reason
    )


def _revoke(session: AuthSession, reason: str) -> None:
    session.revoked_at = timezone.now()
    session.revoke_reason = reason
    session.save(update_fields=["revoked_at", "revoke_reason"])


# --- Password reset -------------------------------------------------------------------------
#
# Tokens come from Django's PasswordResetTokenGenerator: an HMAC over the user's id, password
# hash, last_login and a timestamp. No table is needed, they expire after
# PASSWORD_RESET_TIMEOUT, and they stop working the moment the password changes, which makes
# them single-use. The contract carries one `token`, so uid and token are joined by a dot.


def make_reset_token(user: User) -> str:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    return f"{uid}.{default_token_generator.make_token(user)}"


def request_password_reset(email: str, request=None) -> None:
    """Always succeeds from the caller's point of view (no account enumeration)."""
    user = User.objects.filter(email=User.objects.normalize_email(email), is_active=True).first()
    if user is None or not user.has_usable_password():
        return
    record(Action.PASSWORD_RESET_REQUESTED, actor=None, entity=user, request=request)
    # Queued, not sent inline: response time no longer differs between known and unknown
    # emails, and SMTP failures are retried by the worker.
    from .tasks import send_password_reset_email

    try:
        send_password_reset_email.delay(str(user.pk))
    except Exception:
        logger.exception("Could not queue password reset email", extra={"user_id": str(user.pk)})


def _user_from_reset_token(raw: str) -> User:
    uid, sep, token = raw.partition(".")
    if not sep:
        raise InvalidResetToken
    try:
        pk = force_str(urlsafe_base64_decode(uid))
        user = User.objects.get(pk=pk, is_active=True)
    except (ValueError, TypeError, OverflowError, User.DoesNotExist) as exc:
        raise InvalidResetToken from exc
    if not default_token_generator.check_token(user, token):
        raise InvalidResetToken
    return user


def reset_password(raw_token: str, new_password: str, request=None) -> User:
    user = _user_from_reset_token(raw_token)
    validate_password(new_password, user=user)  # raises Django ValidationError -> 400
    with transaction.atomic():
        user.set_password(new_password)
        user.save(update_fields=["password"])
        # Whoever triggered the reset may be locking out an attacker: end every session.
        revoke_all_sessions(user, AuthSession.RevokeReason.PASSWORD_RESET)
        record(Action.PASSWORD_RESET, actor=user, entity=user, request=request)
    return user


# --- Profile --------------------------------------------------------------------------------

PROFILE_FIELDS = {"name", "phone", "avatar_url"}


def update_profile(user: User, changes: dict, request=None) -> User:
    changes = {k: v for k, v in changes.items() if k in PROFILE_FIELDS}
    if not changes:
        return user
    with transaction.atomic():
        for field, value in changes.items():
            setattr(user, field, value)
        user.save(update_fields=list(changes))
        if user.is_agent:
            invalidate_on_commit("agents")  # name and phone appear on public agent cards
        record(
            Action.PROFILE_UPDATED,
            actor=user,
            entity=user,
            metadata={"fields": sorted(changes)},
            request=request,
        )
    return user


# --- Email verification ---------------------------------------------------------------------


def verify_email(raw_token: str, request=None) -> User:
    """Mark the address as verified. Idempotent: re-using a valid link changes nothing."""
    user = verification.user_from_token(raw_token)  # raises InvalidVerificationToken
    if user.is_email_verified:
        return user
    from .tasks import send_welcome_email

    with transaction.atomic():
        updated = User.objects.filter(pk=user.pk, email_verified_at__isnull=True).update(
            email_verified_at=timezone.now()
        )
        if updated:
            if user.role == User.Role.AGENT:
                # Temporary: email verification currently also verifies agent profiles.
                profile_updated = AgentProfile.objects.filter(user=user).exclude(
                    verification_status=AgentProfile.VerificationStatus.VERIFIED
                ).update(verification_status=AgentProfile.VerificationStatus.VERIFIED)
                if profile_updated:
                    invalidate_on_commit("agents")
            record(Action.EMAIL_VERIFIED, actor=user, entity=user, request=request)
            transaction.on_commit(lambda: _queue(send_welcome_email, user.pk), robust=True)
    user.refresh_from_db()
    return user


def resend_verification(user: User | None, request=None) -> None:
    """
    Queue a fresh verification email. Silently does nothing for unknown, inactive or
    already-verified accounts, so the endpoint can't be used to probe which emails exist.
    """
    if user is None or not user.is_active or user.is_email_verified:
        return
    from .tasks import send_verification_email

    _queue(send_verification_email, user.pk)


def _queue(task, user_id) -> None:
    try:
        task.delay(str(user_id))
    except Exception:
        # Broker unreachable: the user can press "resend" once it's back.
        logger.exception("Could not queue account email", extra={"task": task.name})
