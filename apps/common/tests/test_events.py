import dataclasses

import pytest
from django.db import transaction

from apps.common import events
from apps.common.models import OutboxEvent

pytestmark = pytest.mark.django_db


@events.event
@dataclasses.dataclass(frozen=True, kw_only=True)
class SomethingHappened(events.DomainEvent):
    name = "TestSomethingHappened"
    aggregate_type = "thing"

    thing_id: str

    @property
    def aggregate_id(self) -> str:
        return self.thing_id


@pytest.fixture
def received():
    calls: list[events.DomainEvent] = []

    def handler(evt):
        calls.append(evt)

    events.subscribe(SomethingHappened)(handler)
    yield calls
    events.unsubscribe(SomethingHappened, handler)


@pytest.mark.django_db(transaction=True)  # the default test wrapper is itself a transaction
def test_publish_outside_a_transaction_is_refused():
    with pytest.raises(RuntimeError):
        events.publish(SomethingHappened(thing_id="1"))


def test_event_is_stored_then_delivered_after_commit(received, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
        events.publish(SomethingHappened(thing_id="42"))
        assert received == []  # nothing is delivered while the transaction is open

    assert len(received) == 1 and received[0].thing_id == "42"
    row = OutboxEvent.objects.get()
    assert row.dispatched_at is not None and row.attempts == 1


def test_rolled_back_transaction_leaves_no_event(received, django_capture_on_commit_callbacks):
    with (
        django_capture_on_commit_callbacks(execute=True),
        pytest.raises(ZeroDivisionError),
        transaction.atomic(),
    ):
        events.publish(SomethingHappened(thing_id="1"))
        1 / 0  # noqa: B018
    assert received == []
    assert not OutboxEvent.objects.exists()


def test_failed_handler_schedules_a_retry_and_the_retry_delivers(
    django_capture_on_commit_callbacks,
):
    from celery.exceptions import Retry

    from apps.common import tasks

    attempts = []

    def flaky(evt):
        attempts.append(evt)
        if len(attempts) == 1:
            raise ConnectionError("smtp down")

    events.subscribe(SomethingHappened)(flaky)
    try:
        # The request commits normally even though delivery fails afterwards.
        with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
            events.publish(SomethingHappened(thing_id="7"))
        row = OutboxEvent.objects.get()
        assert row.dispatched_at is None
        assert row.attempts == 1 and "smtp down" in row.last_error

        # What the scheduled retry does: run the task again. It now succeeds.
        result = tasks.dispatch_event.apply(args=[str(row.id)])
        assert result.get() == events.DISPATCHED
        row.refresh_from_db()
        assert row.dispatched_at is not None and row.attempts == 2 and row.last_error == ""

        # And a task that fails raises Retry, i.e. Celery reschedules it with backoff.
        attempts.clear()
        with transaction.atomic():
            events.publish(SomethingHappened(thing_id="8"))
        second = OutboxEvent.objects.get(payload__thing_id="8")
        with pytest.raises(Retry):
            tasks.dispatch_event.apply(args=[str(second.id)], throw=True)
    finally:
        events.unsubscribe(SomethingHappened, flaky)


def test_dispatch_task_retry_policy():
    from apps.common import tasks
    from apps.common.tasks import HandlerFailed

    task = tasks.dispatch_event
    assert task.autoretry_for == (HandlerFailed,)
    assert task.retry_backoff is True and task.retry_jitter is True
    assert task.max_retries == 8 and task.acks_late is True


def test_broker_outage_at_commit_leaves_event_for_the_relay(
    received, django_capture_on_commit_callbacks, monkeypatch
):
    from apps.common import tasks

    def broker_down(*args, **kwargs):
        raise ConnectionError("redis unreachable")

    monkeypatch.setattr(tasks.dispatch_event, "delay", broker_down)
    with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
        events.publish(SomethingHappened(thing_id="r1"))
    row = OutboxEvent.objects.get()
    assert row.dispatched_at is None and received == []

    monkeypatch.undo()  # broker is back
    OutboxEvent.objects.filter(pk=row.pk).update(
        occurred_at=row.occurred_at - tasks.RELAY_GRACE * 2
    )
    assert tasks.relay_pending_events() == 1
    row.refresh_from_db()
    assert row.dispatched_at is not None and len(received) == 1


def test_relay_ignores_fresh_and_delivered_events(received, django_capture_on_commit_callbacks):
    from apps.common import tasks

    with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
        events.publish(SomethingHappened(thing_id="done"))
    with transaction.atomic():
        events.publish(SomethingHappened(thing_id="fresh"))  # pending, but within grace
    assert tasks.relay_pending_events() == 0


def test_dispatching_an_already_delivered_event_is_a_noop(
    received, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
        events.publish(SomethingHappened(thing_id="9"))
    assert events.dispatch(OutboxEvent.objects.get().id) == events.SKIPPED
    assert len(received) == 1


def test_payload_round_trips_through_the_outbox(received, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True), transaction.atomic():
        original = SomethingHappened(thing_id="abc")
        events.publish(original)
    rebuilt = received[0]
    assert rebuilt == original  # same id, timestamp and data
