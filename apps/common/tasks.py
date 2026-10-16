"""
Outbox delivery tasks.

    publish() --(on_commit)--> dispatch_event.delay(id) ---> handlers
                                     ^
    relay_pending_events (Beat, 30s) |  re-enqueues rows still pending, e.g. because the
                                     |  broker was down at commit time or a worker died

Every path ends in events.dispatch(), which locks the row with SKIP LOCKED and marks it
dispatched, so concurrent or repeated deliveries of one event run its handlers once.
"""

import datetime
import logging

from celery import shared_task
from django.utils import timezone

from . import events
from .models import OutboxEvent

logger = logging.getLogger(__name__)

RELAY_GRACE = datetime.timedelta(seconds=30)
RELAY_BATCH = 500
MAX_ATTEMPTS = 25  # beyond this a row needs a human; it stays visible as pending
PURGE_AFTER = datetime.timedelta(days=30)


class HandlerFailed(Exception):
    pass


@shared_task(
    bind=True,
    autoretry_for=(HandlerFailed,),
    retry_backoff=True,  # 1s, 2s, 4s, ... with jitter, so retries don't stampede
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=8,
    acks_late=True,
)
def dispatch_event(self, event_id: str) -> str:
    outcome = events.dispatch(event_id)
    if outcome == events.FAILED:
        raise HandlerFailed(f"Handlers failed for event {event_id}")
    return outcome


@shared_task
def relay_pending_events() -> int:
    cutoff = timezone.now() - RELAY_GRACE
    pending = list(
        OutboxEvent.objects.filter(
            dispatched_at__isnull=True, occurred_at__lt=cutoff, attempts__lt=MAX_ATTEMPTS
        )
        .order_by("occurred_at")
        .values_list("id", flat=True)[:RELAY_BATCH]
    )
    for event_id in pending:
        dispatch_event.delay(str(event_id))
    if pending:
        logger.info("Relayed pending outbox events", extra={"count": len(pending)})
    return len(pending)


@shared_task
def purge_dispatched_events() -> int:
    deleted, _ = OutboxEvent.objects.filter(dispatched_at__lt=timezone.now() - PURGE_AFTER).delete()
    return deleted
