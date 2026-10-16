import datetime
import logging

from celery import shared_task
from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from apps.common.mail import send_templated_email

from .models import AuthSession, User

logger = logging.getLogger(__name__)

EMAIL_RETRY = {
    "autoretry_for": (Exception,),
    "retry_backoff": True,
    "retry_backoff_max": 600,
    "retry_jitter": True,
    "max_retries": 5,
}


@shared_task(**EMAIL_RETRY)
def send_password_reset_email(user_id: str) -> str:
    """
    The reset token is generated here, in the worker, from the user id alone. No credential
    ever sits in the broker or in task arguments. A retry generates a fresh token, which is
    equally valid: tokens are HMACs of the user's current state, not stored secrets.
    """
    from .services import make_reset_token

    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None or not user.has_usable_password():
        return "skipped"
    link = f"{settings.FRONTEND_URL}/auth/reset-password?token={make_reset_token(user)}"
    send_templated_email(
        subject="Reset your PLEET password",
        template="emails/password_reset",
        context={
            "name": user.name,
            "action_url": link,
            "expires_minutes": settings.PASSWORD_RESET_TIMEOUT // 60,
            "frontend_url": settings.FRONTEND_URL,
        },
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient=user.email,
    )
    return "sent"


@shared_task(**EMAIL_RETRY)
def send_verification_email(user_id: str) -> str:
    """Token generated here in the worker, like reset tokens: no credential in the broker."""
    from .verification import verification_link

    user = User.objects.filter(pk=user_id, is_active=True, email_verified_at__isnull=True).first()
    if user is None:
        return "skipped"  # unknown, deactivated, or verified in the meantime
    hours = settings.EMAIL_VERIFICATION_TIMEOUT // 3600
    send_templated_email(
        subject="Verify your PLEET email address",
        template="emails/verify_email",
        context={
            "name": user.name,
            "role": user.role,
            "action_url": verification_link(user),
            "expires_hours": hours,
            "frontend_url": settings.FRONTEND_URL,
        },
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient=user.email,
    )
    return "sent"


@shared_task(**EMAIL_RETRY)
def send_welcome_email(user_id: str) -> str:
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return "skipped"
    send_templated_email(
        subject="Welcome to PLEET",
        template="emails/welcome",
        context={
            "name": user.name,
            "role": user.role,
            "action_url": settings.FRONTEND_URL,
            "frontend_url": settings.FRONTEND_URL,
        },
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient=user.email,
    )
    return "sent"


@shared_task
def cleanup_auth_sessions() -> int:
    """Daily: drop sessions that expired a day ago or were revoked a month ago."""
    now = timezone.now()
    deleted, _ = AuthSession.objects.filter(
        Q(expires_at__lt=now - datetime.timedelta(days=1))
        | Q(revoked_at__lt=now - datetime.timedelta(days=30))
    ).delete()
    return deleted
