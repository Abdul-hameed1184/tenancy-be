import datetime

import pytest
from channels.db import database_sync_to_async
from channels.testing import WebsocketCommunicator
from django.core import mail
from django.utils import timezone

from apps.accounts import realtime
from apps.accounts import services as account_services
from apps.inspections import services as inspection_services
from apps.notifications import services
from apps.notifications.models import Notification
from apps.notifications.tasks import send_notification_email
from apps.payments import tasks as rent_tasks
from tests.factories import (
    AgentFactory,
    AssignmentFactory,
    InspectionFactory,
    PropertyFactory,
    TenancyFactory,
    ThreadFactory,
    UserFactory,
)

API = "/api/v1/notifications"


def _notify(user, key="k1", type="new_message"):
    return services.notify(
        recipient_id=user.pk, type=type, title="Hi", message="Hello", dedupe_key=key
    )


# --- Creation & idempotency -----------------------------------------------------------------


@pytest.mark.django_db
def test_same_dedupe_key_creates_one_notification():
    user = UserFactory()
    first, created = _notify(user)
    again, created_again = _notify(user)
    assert created and not created_again and first.pk == again.pk
    assert Notification.objects.count() == 1


@pytest.mark.django_db
def test_message_creates_notification_for_other_participants_only(
    api_client, authenticate, django_capture_on_commit_callbacks
):
    a, b = UserFactory(), UserFactory()
    thread = ThreadFactory(members=[a, b])
    authenticate(api_client, a)
    with django_capture_on_commit_callbacks(execute=True):
        api_client.post(f"/api/v1/threads/{thread.id}/messages", {"body": "Hey"}, format="json")
    assert list(Notification.objects.values_list("recipient_id", "type")) == [(b.id, "new_message")]


@pytest.mark.django_db
def test_inspection_confirmation_notifies_and_emails_tenant(django_capture_on_commit_callbacks):
    insp = InspectionFactory()
    with django_capture_on_commit_callbacks(execute=True):
        inspection_services.apply_transition(insp=insp, action="confirm", actor=insp.agent)
    note = Notification.objects.get(type="inspection_confirmed")
    assert note.recipient_id == insp.tenant_id
    note.refresh_from_db()
    assert note.emailed_at is not None
    assert [m.to for m in mail.outbox] == [[insp.tenant.email]]


@pytest.mark.django_db
def test_cancellation_notifies_the_other_party(django_capture_on_commit_callbacks):
    insp = InspectionFactory()
    with django_capture_on_commit_callbacks(execute=True):
        inspection_services.apply_transition(insp=insp, action="cancel", actor=insp.tenant)
    assert Notification.objects.get(type="inspection_cancelled").recipient_id == insp.agent_id


@pytest.mark.django_db
def test_new_message_is_not_emailed(django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        _notify(UserFactory())
    assert mail.outbox == []


@pytest.mark.django_db
def test_notification_email_is_sent_at_most_once():
    note, _ = _notify(UserFactory(), type="payment_reminder")
    assert send_notification_email.apply(args=[str(note.pk)]).get() == "sent"
    assert send_notification_email.apply(args=[str(note.pk)]).get() == "already-sent"
    assert len(mail.outbox) == 1
    assert len(mail.outbox[0].alternatives) == 1
    assert "Hi" in mail.outbox[0].alternatives[0].content
    assert "Hello" in mail.outbox[0].body


# --- REST -----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_feed_is_private_newest_first_and_filterable(api_client, authenticate):
    me, other = UserFactory(), UserFactory()
    old, _ = _notify(me, "a")
    new, _ = _notify(me, "b")
    _notify(other, "c")
    Notification.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - datetime.timedelta(hours=1), is_read=True
    )
    authenticate(api_client, me)
    body = api_client.get(API).json()
    assert [n["id"] for n in body] == [str(new.id), str(old.id)]
    assert set(body[0]) == {"id", "type", "title", "message", "data", "isRead", "createdAt"}
    assert [n["id"] for n in api_client.get(API, {"unread": "true"}).json()] == [str(new.id)]


@pytest.mark.django_db
def test_mark_read_and_read_all(api_client, authenticate):
    me = UserFactory()
    first, _ = _notify(me, "a")
    _notify(me, "b")
    authenticate(api_client, me)
    assert api_client.post(f"{API}/{first.id}/read").json()["isRead"] is True
    assert api_client.post(f"{API}/read-all").json() == {"updated": 1}
    assert api_client.get(API, {"unread": "true"}).json() == []


@pytest.mark.django_db
def test_cannot_read_someone_elses_notification(api_client, authenticate):
    theirs, _ = _notify(UserFactory())
    authenticate(api_client, UserFactory())
    assert api_client.post(f"{API}/{theirs.id}/read").status_code == 404
    theirs.refresh_from_db()
    assert theirs.is_read is False


# --- WebSocket delivery ---------------------------------------------------------------------


def _ticket(user):
    issued = account_services.start_session(user)
    user.auth_session_id = issued.session.id
    return realtime.issue_ticket(user)


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_notification_is_pushed_to_the_recipients_socket():
    user = await database_sync_to_async(UserFactory)()
    ticket = await database_sync_to_async(_ticket)(user)
    from config.asgi import application

    ws = WebsocketCommunicator(
        application,
        f"/ws/notifications/?ticket={ticket}",
        headers=[(b"origin", b"http://localhost:5173")],
    )
    connected, _ = await ws.connect()
    assert connected

    await database_sync_to_async(_notify)(user, "push-1")

    frame = await ws.receive_json_from(timeout=3)
    assert frame["type"] == "notification.created"
    assert frame["notification"]["title"] == "Hi"
    await ws.disconnect()


@pytest.mark.asyncio
@pytest.mark.django_db(transaction=True)
async def test_anonymous_notification_socket_is_refused():
    from config.asgi import application

    ws = WebsocketCommunicator(
        application, "/ws/notifications/", headers=[(b"origin", b"http://localhost:5173")]
    )
    connected, code = await ws.connect()
    assert not connected and code == 4401


# --- Scheduled rent jobs (Celery Beat) ------------------------------------------------------


@pytest.fixture
def rent_setup(db):
    agent = AgentFactory()
    prop = PropertyFactory()
    AssignmentFactory(property=prop, agent=agent)
    today = rent_tasks.business_today()
    return {
        "agent": agent,
        "due_soon": TenancyFactory(
            property=prop,
            lease_start=today - datetime.timedelta(days=360),
            next_due_date=today + datetime.timedelta(days=3),
        ),
        "far_off": TenancyFactory(
            lease_start=today - datetime.timedelta(days=100),
            next_due_date=today + datetime.timedelta(days=60),
        ),
        "overdue": TenancyFactory(
            property=prop,
            lease_start=today - datetime.timedelta(days=400),
            next_due_date=today - datetime.timedelta(days=2),
        ),
    }


def test_due_reminders_target_tenant_and_agent_once(rent_setup):
    assert rent_tasks.send_rent_due_reminders() == 2  # tenant + agent of the due-soon tenancy
    assert rent_tasks.send_rent_due_reminders() == 0  # idempotent: re-run sends nothing
    recipients = set(
        Notification.objects.filter(type="payment_reminder").values_list("recipient_id", flat=True)
    )
    assert recipients == {rent_setup["due_soon"].tenant_id, rent_setup["agent"].id}


def test_overdue_sweep_notifies_tenant_agent_and_landlord_once(rent_setup):
    overdue = rent_setup["overdue"]
    assert rent_tasks.flag_overdue_rent() == 3
    assert rent_tasks.flag_overdue_rent() == 0
    recipients = set(
        Notification.objects.filter(type="payment_overdue").values_list("recipient_id", flat=True)
    )
    assert recipients == {overdue.tenant_id, rent_setup["agent"].id, overdue.property.landlord_id}


def test_new_due_date_gets_a_new_reminder(rent_setup):
    rent_tasks.send_rent_due_reminders()
    tenancy = rent_setup["due_soon"]
    tenancy.next_due_date += datetime.timedelta(days=1)  # e.g. a new period
    tenancy.save()
    assert rent_tasks.send_rent_due_reminders() == 2


@pytest.mark.django_db
def test_cleanup_removes_only_stale_sessions():
    from apps.accounts.models import AuthSession
    from apps.accounts.tasks import cleanup_auth_sessions

    user = UserFactory()
    live = account_services.start_session(user).session
    stale = account_services.start_session(user).session
    AuthSession.objects.filter(pk=stale.pk).update(
        expires_at=timezone.now() - datetime.timedelta(days=2)
    )
    assert cleanup_auth_sessions() == 1
    assert AuthSession.objects.filter(pk=live.pk).exists()


@pytest.mark.django_db
def test_registration_queues_verification_email(api_client, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        api_client.post(
            "/api/v1/auth/register",
            {"role": "tenant", "name": "Ada", "email": "ada@example.com",
             "password": "Tr1cky-Passphrase!"},
            format="json",
        )  # fmt: skip
    assert [m.subject for m in mail.outbox] == ["Verify your PLEET email address"]


def test_beat_schedule_is_registered():
    from django.conf import settings

    tasks = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert tasks == {
        "apps.common.tasks.relay_pending_events",
        "apps.payments.tasks.send_rent_due_reminders",
        "apps.payments.tasks.flag_overdue_rent",
        "apps.accounts.tasks.cleanup_auth_sessions",
        "apps.common.tasks.purge_dispatched_events",
    }
    from config.celery import app

    app.loader.import_default_modules()
    assert tasks <= set(app.tasks)  # every scheduled name resolves to a real task
