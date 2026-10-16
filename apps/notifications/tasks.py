import logging

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.common.mail import send_templated_email

from .models import Notification

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=6,
)
def send_notification_email(self, notification_id: str) -> str:
    """
    Email a notification at most once.

    The row is locked (SKIP LOCKED: a concurrent duplicate simply backs off) and
    emailed_at is checked and set inside the same transaction. A retry after a successful
    send, or a redelivered message after a worker crash, finds emailed_at set and does
    nothing.
    """
    with transaction.atomic():
        notification = (
            Notification.objects.select_for_update(skip_locked=True)
            .select_related("recipient")
            .filter(pk=notification_id)
            .first()
        )
        if notification is None:
            return "skipped"
        if notification.emailed_at is not None:
            return "already-sent"
        send_templated_email(
            subject=f"PLEET: {notification.title}",
            template="emails/notification",
            context={
                "name": notification.recipient.name,
                "title": notification.title,
                "message": notification.message,
                "action_url": settings.FRONTEND_URL,
                "frontend_url": settings.FRONTEND_URL,
            },
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient=notification.recipient.email,
        )
        notification.emailed_at = timezone.now()
        notification.save(update_fields=["emailed_at"])
    return "sent"
