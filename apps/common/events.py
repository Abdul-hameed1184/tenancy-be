"""
Lightweight domain events.

    Service (inside transaction.atomic)
        publish(AgentAssigned(...))
            -> INSERT outbox row          (same transaction as the state change)
            -> on_commit(dispatch)        (runs only if the transaction commits)
    dispatch(event_id)
        -> run subscribed handlers, mark the row dispatched (or record the error)

After commit, the event id is handed to Celery (apps.common.tasks.dispatch_event). If the
broker is unreachable at that moment, the row simply stays pending and the periodic relay
re-enqueues it. Introducing Kafka would mean changing _enqueue() and the relay; services
and handlers stay the same.

Handlers may run more than once (retries, relay), so they must be idempotent. The event id
is the natural idempotency key.
"""

import dataclasses
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from datetime import datetime
from typing import ClassVar

from django.db import connection, transaction
from django.utils import timezone

from .uuids import uuid7
from .models import OutboxEvent

logger = logging.getLogger(__name__)

DISPATCHED, SKIPPED, FAILED = "dispatched", "skipped", "failed"


@dataclasses.dataclass(frozen=True, kw_only=True)
class DomainEvent:
    name: ClassVar[str]
    aggregate_type: ClassVar[str]

    event_id: uuid.UUID = dataclasses.field(default_factory=uuid7)
    occurred_at: datetime = dataclasses.field(default_factory=timezone.now)

    @property
    def aggregate_id(self) -> str:
        raise NotImplementedError

    def payload(self) -> dict:
        data = dataclasses.asdict(self)
        data.pop("event_id")
        data.pop("occurred_at")
        return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in data.items()}


Handler = Callable[[DomainEvent], None]
_registry: dict[str, type[DomainEvent]] = {}
_handlers: dict[str, list[Handler]] = defaultdict(list)


def event(cls: type[DomainEvent]) -> type[DomainEvent]:
    """Class decorator: register an event type so stored rows can be rebuilt into objects."""
    if cls.name in _registry and _registry[cls.name] is not cls:
        raise ValueError(f"Duplicate event name {cls.name!r}")
    _registry[cls.name] = cls
    return cls


def subscribe(event_cls: type[DomainEvent]):
    def decorator(handler: Handler) -> Handler:
        if handler not in _handlers[event_cls.name]:
            _handlers[event_cls.name].append(handler)
        return handler

    return decorator


def unsubscribe(event_cls: type[DomainEvent], handler: Handler) -> None:
    if handler in _handlers[event_cls.name]:
        _handlers[event_cls.name].remove(handler)


def publish(evt: DomainEvent) -> None:
    if not connection.in_atomic_block:
        # Without a surrounding transaction the outbox row could commit while the state
        # change fails (or vice versa), which is the exact bug the outbox exists to prevent.
        raise RuntimeError("publish() must be called inside transaction.atomic().")
    OutboxEvent.objects.create(
        id=evt.event_id,
        event_type=evt.name,
        aggregate_type=evt.aggregate_type,
        aggregate_id=evt.aggregate_id,
        payload=evt.payload(),
        occurred_at=evt.occurred_at,
    )
    event_id = str(evt.event_id)
    transaction.on_commit(lambda: _enqueue(event_id), robust=True)


def _enqueue(event_id: str) -> None:
    from .tasks import dispatch_event

    try:
        dispatch_event.delay(event_id)
    except Exception:
        # Broker down (e.g. mid Redis failover). The outbox row is committed and pending;
        # relay_pending_events will pick it up. The user's request is unaffected.
        logger.warning("Could not enqueue event; relay will retry", exc_info=True)


def dispatch(event_id) -> str:
    """Deliver one stored event to its handlers: DISPATCHED, SKIPPED or FAILED."""
    with transaction.atomic():
        # SKIP LOCKED: if another worker/relay is already delivering this row, back off
        # instead of delivering it twice concurrently.
        row = (
            OutboxEvent.objects.select_for_update(skip_locked=True)
            .filter(id=event_id, dispatched_at__isnull=True)
            .first()
        )
        if row is None:
            return SKIPPED  # already delivered, or another worker holds it right now
        evt = _rebuild(row)
        row.attempts += 1
        try:
            # Savepoint: a handler that fails mid-write rolls back only its own writes, and
            # the outer transaction can still record the failure on the outbox row.
            with transaction.atomic():
                for handler in list(_handlers[row.event_type]):
                    handler(evt)
        except Exception as exc:
            logger.exception("Event handler failed", extra={"event": row.event_type})
            row.last_error = f"{type(exc).__name__}: {exc}"[:2000]
            row.save(update_fields=["attempts", "last_error"])
            return FAILED
        row.dispatched_at = timezone.now()
        row.last_error = ""
        row.save(update_fields=["attempts", "last_error", "dispatched_at"])
        return DISPATCHED


def _rebuild(row: OutboxEvent) -> DomainEvent:
    cls = _registry[row.event_type]
    fields = {f.name for f in dataclasses.fields(cls)}
    data = {k: v for k, v in row.payload.items() if k in fields}
    return cls(event_id=row.id, occurred_at=row.occurred_at, **data)
