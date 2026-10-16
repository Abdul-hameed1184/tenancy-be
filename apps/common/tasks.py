# """
# Outbox delivery tasks.

#     publish() --(on_commit)--> dispatch_event.delay(id) ---> handlers
#                                      ^
#     relay_pending_events (Beat, 30s) |  re-enqueues rows still pending, e.g. because the
#                                      |  broker was down at commit time or a worker died

# Every path ends in events.dispatch(), which locks the row with SKIP LOCKED and marks it
# dispatched, so concurrent or repeated deliveries of one event run its handlers once.
# """

# import datetime
# import logging

# from celery import shared_task
# from django.utils import timezone

# from . import events
# from .models import OutboxEvent

# logger = logging.getLogger(__name__)

# RELAY_GRACE = datetime.timedelta(seconds=30)
# RELAY_BATCH = 500
# MAX_ATTEMPTS = 25  # beyond this a row needs a human; it stays visible as pending
# PURGE_AFTER = datetime.timedelta(days=30)


# class HandlerFailed(Exception):
#     pass


# @shared_task(
#     bind=True,
#     autoretry_for=(HandlerFailed,),
#     retry_backoff=True,  # 1s, 2s, 4s, ... with jitter, so retries don't stampede
#     retry_backoff_max=300,
#     retry_jitter=True,
#     max_retries=8,
#     acks_late=True,
# )
# def dispatch_event(self, event_id: str) -> str:
#     outcome = events.dispatch(event_id)
#     if outcome == events.FAILED:
#         raise HandlerFailed(f"Handlers failed for event {event_id}")
#     return outcome


# @shared_task
# def relay_pending_events() -> int:
#     cutoff = timezone.now() - RELAY_GRACE
#     pending = list(
#         OutboxEvent.objects.filter(
#             dispatched_at__isnull=True, occurred_at__lt=cutoff, attempts__lt=MAX_ATTEMPTS
#         )
#         .order_by("occurred_at")
#         .values_list("id", flat=True)[:RELAY_BATCH]
#     )
#     for event_id in pending:
#         dispatch_event.delay(str(event_id))
#     if pending:
#         logger.info("Relayed pending outbox events", extra={"count": len(pending)})
#     return len(pending)


# @shared_task
# def purge_dispatched_events() -> int:
#     deleted, _ = OutboxEvent.objects.filter(dispatched_at__lt=timezone.now() - PURGE_AFTER).delete()
#     return deleted

"""
Outbox delivery functions.

publish() --(on_commit)--> dispatch_event(event_id) --> handlers

relay_pending_events() periodically retries pending events.
purge_dispatched_events() removes old successfully dispatched events.

All execution is synchronous. The database outbox remains the
source of truth for events that have not been dispatched.
"""

import datetime
import logging

from django.utils import timezone

from . import events
from .models import OutboxEvent

logger = logging.getLogger(__name__)

RELAY_GRACE = datetime.timedelta(seconds=30)
RELAY_BATCH = 500
MAX_ATTEMPTS = 25
PURGE_AFTER = datetime.timedelta(days=30)


def dispatch_event(event_id: str) -> str:
    """
    Dispatch one event through the existing event dispatcher.

    Failed events remain eligible for retry through the relay,
    provided events.dispatch() leaves them pending.
    """
    try:
        outcome = events.dispatch(event_id)

        if outcome == events.FAILED:
            logger.warning(
                "Outbox event handlers failed",
                extra={"event_id": str(event_id)},
            )

        return outcome

    except Exception:
        logger.exception(
            "Unexpected error dispatching outbox event",
            extra={"event_id": str(event_id)},
        )
        raise


def relay_pending_events() -> int:
    """
    Retry pending events older than the relay grace period.

    This function is synchronous. Failures for individual events
    do not prevent the remaining events in the batch from running.
    """
    cutoff = timezone.now() - RELAY_GRACE

    pending_ids = list(
        OutboxEvent.objects.filter(
            dispatched_at__isnull=True,
            occurred_at__lt=cutoff,
            attempts__lt=MAX_ATTEMPTS,
        )
        .order_by("occurred_at")
        .values_list("id", flat=True)[:RELAY_BATCH]
    )

    processed = 0

    for event_id in pending_ids:
        try:
            dispatch_event(str(event_id))
            processed += 1
        except Exception:
            logger.exception(
                "Failed to relay outbox event",
                extra={"event_id": str(event_id)},
            )

    if pending_ids:
        logger.info(
            "Processed pending outbox events",
            extra={
                "count": len(pending_ids),
                "successful_calls": processed,
            },
        )

    return processed


def purge_dispatched_events() -> int:
    """
    Delete successfully dispatched events older than 30 days.
    """
    cutoff = timezone.now() - PURGE_AFTER

    deleted, _ = OutboxEvent.objects.filter(
        dispatched_at__lt=cutoff,
    ).delete()

    logger.info(
        "Purged old dispatched outbox events",
        extra={"deleted": deleted},
    )

    return deleted
