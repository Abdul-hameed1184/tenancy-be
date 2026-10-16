# import logging

# from django.db import transaction
# from django.utils import timezone

# from apps.common.ws import broadcast, user_group

# from .models import EMAIL_TYPES, Notification

# logger = logging.getLogger(__name__)


# def notify(
#     *,
#     recipient_id,
#     type: str,
#     title: str,
#     message: str,
#     dedupe_key: str,
#     data: dict | None = None,
# ) -> tuple[Notification, bool]:
#     """
#     Create a notification once per dedupe_key and schedule delivery after commit.

#     Returns (notification, created). A duplicate cause returns the existing row and
#     triggers no second delivery. get_or_create also survives a concurrent duplicate: the
#     loser's INSERT hits the unique index and it re-reads the winner's row.
#     """
#     notification, created = Notification.objects.get_or_create(
#         dedupe_key=dedupe_key,
#         defaults={
#             "recipient_id": recipient_id,
#             "type": type,
#             "title": title[:150],
#             "message": message[:500],
#             "data": data or {},
#         },
#     )
#     if created:
#         notification_id = notification.pk
#         transaction.on_commit(lambda: deliver(notification_id), robust=True)
#     return notification, created


# def deliver(notification_id) -> None:
#     """Push over WebSocket (best effort) and queue an email when the type warrants one."""
#     from .serializers import NotificationSerializer
#     from .tasks import send_notification_email

#     notification = Notification.objects.filter(pk=notification_id).first()
#     if notification is None:
#         return
#     broadcast(
#         user_group(notification.recipient_id),
#         {"type": "notification.created", "notification": NotificationSerializer(notification).data},
#     )
#     if notification.type in EMAIL_TYPES:
#         try:
#             send_notification_email.delay(str(notification.pk))
#         except Exception:
#             # Broker unreachable: the notification is already stored and visible in-app.
#             logger.warning("Could not queue notification email", exc_info=True)


# def mark_read(user, notification_id) -> int:
#     return Notification.objects.filter(pk=notification_id, recipient=user, is_read=False).update(
#         is_read=True, read_at=timezone.now()
#     )


# def mark_all_read(user) -> int:
#     return Notification.objects.filter(recipient=user, is_read=False).update(
#         is_read=True, read_at=timezone.now()
#     )

import logging

from django.db import transaction
from django.utils import timezone

from apps.common.ws import broadcast, user_group

from .models import EMAIL_TYPES, Notification

logger = logging.getLogger(__name__)


def notify(
    *,
    recipient_id,
    type: str,
    title: str,
    message: str,
    dedupe_key: str,
    data: dict | None = None,
) -> tuple[Notification, bool]:
    """
    Create a notification once per dedupe_key and deliver after commit.

    Returns (notification, created).
    Duplicate notifications do not trigger another delivery.
    """
    notification, created = Notification.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={
            "recipient_id": recipient_id,
            "type": type,
            "title": title[:150],
            "message": message[:500],
            "data": data or {},
        },
    )

    if created:
        notification_id = notification.pk

        transaction.on_commit(
            lambda: deliver(notification_id),
            robust=True,
        )

    return notification, created


def deliver(notification_id) -> None:
    """
    Broadcast the notification over WebSocket and send email
    synchronously when the notification type requires it.
    """
    from .serializers import NotificationSerializer
    from .tasks import send_notification_email

    notification = (
        Notification.objects.filter(pk=notification_id)
        .select_related("recipient")
        .first()
    )

    if notification is None:
        return

    try:
        broadcast(
            user_group(notification.recipient_id),
            {
                "type": "notification.created",
                "notification": NotificationSerializer(notification).data,
            },
        )
    except Exception:
        logger.exception(
            "Could not broadcast notification over WebSocket",
            extra={"notification_id": str(notification.pk)},
        )

    if notification.type in EMAIL_TYPES:
        try:
            send_notification_email(str(notification.pk))
        except Exception:
            logger.exception(
                "Could not send notification email",
                extra={"notification_id": str(notification.pk)},
            )


def mark_read(user, notification_id) -> int:
    return Notification.objects.filter(
        pk=notification_id,
        recipient=user,
        is_read=False,
    ).update(
        is_read=True,
        read_at=timezone.now(),
    )


def mark_all_read(user) -> int:
    return Notification.objects.filter(
        recipient=user,
        is_read=False,
    ).update(
        is_read=True,
        read_at=timezone.now(),
    )
