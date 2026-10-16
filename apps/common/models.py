from django.db import models

from .uuids import uuid7


class UUIDModel(models.Model):
    """
    UUIDv7 primary key.

    The contract exposes ids as opaque strings, and sequential integers would leak volume
    and make ids guessable. UUIDv7 is time-ordered, so unlike random UUIDv4 new rows append
    to the right edge of the B-tree index instead of causing random page splits.
    """

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)

    class Meta:
        abstract = True


class OutboxEvent(models.Model):
    """
    Transactional outbox: a domain event persisted in the same transaction as the state
    change that caused it. Delivery happens after commit and can be retried from here, so
    an event is never lost because a broker was down, and never sent for a rolled-back
    change.
    """

    id = models.UUIDField(primary_key=True)  # = the event's own id (idempotency key)
    event_type = models.CharField(max_length=64)
    aggregate_type = models.CharField(max_length=64)
    aggregate_id = models.CharField(max_length=64)
    payload = models.JSONField()
    occurred_at = models.DateTimeField()
    dispatched_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["occurred_at"]
        indexes = [
            # The relay only ever scans undelivered rows; a partial index keeps that scan
            # tiny no matter how much history accumulates.
            models.Index(
                fields=["occurred_at"],
                condition=models.Q(dispatched_at__isnull=True),
                name="common_outbox_pending_idx",
            ),
            models.Index(fields=["aggregate_type", "aggregate_id"], name="common_outbox_agg_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.event_type}({self.aggregate_type}:{self.aggregate_id})"
