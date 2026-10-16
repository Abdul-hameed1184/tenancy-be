import datetime

import pytest
from django.utils import timezone

from apps.common.models import OutboxEvent
from apps.messaging.models import Message, MessageThread
from tests.factories import AssignmentFactory, TenancyFactory, ThreadFactory, UserFactory

pytestmark = pytest.mark.django_db
API = "/api/v1/threads"


@pytest.fixture
def pair():
    a, b = UserFactory(role="tenant"), UserFactory(role="agent")
    return a, b, ThreadFactory(members=[a, b])


def test_threads_list_shape_participants_and_sort(
    api_client, authenticate, pair, django_assert_num_queries
):
    a, b, older = pair
    newer = ThreadFactory(members=[a, UserFactory()])
    MessageThread.objects.filter(pk=older.pk).update(
        last_message_at=timezone.now() - datetime.timedelta(days=1)
    )
    ThreadFactory(members=[b, UserFactory()])  # a isn't in this one
    authenticate(api_client, a)

    with django_assert_num_queries(2):  # auth + threads with ARRAY_AGG(participants)
        body = api_client.get(API, {"userId": str(a.id)}).json()

    assert [t["id"] for t in body] == [str(newer.id), str(older.id)]
    assert set(body[1]) == {
        "id", "participantIds", "lastMessageAt", "unreadCount"
    }  # no propertyId
    assert set(body[1]["participantIds"]) == {str(a.id), str(b.id)}
    assert body[1]["unreadCount"] == 0


def test_thread_list_reports_unread_messages_per_participant(api_client, authenticate, pair):
    tenant, agent, thread = pair
    Message.objects.create(thread=thread, sender=agent, body="Please check the update.")
    authenticate(api_client, tenant)

    response = api_client.get(API, {"userId": str(tenant.id)})

    assert response.status_code == 200
    assert response.json()[0]["unreadCount"] == 1


def test_thread_list_includes_latest_message_preview(api_client, authenticate, pair):
    tenant, agent, thread = pair
    Message.objects.create(thread=thread, sender=agent, body="First update")
    Message.objects.create(thread=thread, sender=tenant, body="Latest reply")
    authenticate(api_client, tenant)

    response = api_client.get(API, {"userId": str(tenant.id)})

    assert response.json()[0]["lastMessagePreview"] == "Latest reply"


def test_marking_thread_read_clears_only_readers_unread_count(api_client, authenticate, pair):
    tenant, agent, thread = pair
    Message.objects.create(thread=thread, sender=agent, body="Unread for tenant.")
    authenticate(api_client, tenant)

    assert api_client.post(f"{API}/{thread.id}/read").status_code == 204
    tenant_threads = api_client.get(API, {"userId": str(tenant.id)}).json()
    assert tenant_threads[0]["unreadCount"] == 0

    authenticate(api_client, agent)
    agent_threads = api_client.get(API, {"userId": str(agent.id)}).json()
    assert agent_threads[0]["unreadCount"] == 0


def test_non_participant_cannot_mark_thread_read(api_client, authenticate, pair):
    _, _, thread = pair
    authenticate(api_client, UserFactory())

    assert api_client.post(f"{API}/{thread.id}/read").status_code == 404


def test_user_id_must_be_self(api_client, authenticate, pair):
    a, b, _ = pair
    authenticate(api_client, a)
    assert api_client.get(API, {"userId": str(b.id)}).status_code == 403
    assert api_client.get(API).status_code == 200  # omitted: defaults to self


def test_tenant_initializes_thread_with_assigned_agent_idempotently(api_client, authenticate):
    assignment = AssignmentFactory()
    tenancy = TenancyFactory(property=assignment.property)
    authenticate(api_client, tenancy.tenant)

    first = api_client.post(f"{API}/initialize")
    second = api_client.post(f"{API}/initialize")

    assert first.status_code == second.status_code == 204
    threads = MessageThread.objects.filter(contact_pair__isnull=False)
    assert threads.count() == 1
    assert set(threads.get().participants.values_list("pk", flat=True)) == {
        tenancy.tenant_id,
        assignment.agent_id,
    }
    assert threads.get().property_id == assignment.property_id


def test_agent_initializes_threads_with_every_current_tenant(api_client, authenticate):
    assignment_a = AssignmentFactory()
    assignment_b = AssignmentFactory(agent=assignment_a.agent)
    tenancy_a = TenancyFactory(property=assignment_a.property)
    tenancy_b = TenancyFactory(property=assignment_b.property)
    authenticate(api_client, assignment_a.agent)

    response = api_client.post(f"{API}/initialize")

    assert response.status_code == 204
    agent_tenant_threads = [
        thread
        for thread in MessageThread.objects.filter(contact_pair__isnull=False)
        if thread.participants.filter(pk__in=[tenancy_a.tenant_id, tenancy_b.tenant_id]).exists()
    ]
    assert len(agent_tenant_threads) == 2
    assert {
        frozenset(thread.participants.values_list("pk", flat=True))
        for thread in agent_tenant_threads
    } == {
        frozenset((assignment_a.agent_id, tenancy_a.tenant_id)),
        frozenset((assignment_a.agent_id, tenancy_b.tenant_id)),
    }


def test_send_and_read_messages(api_client, authenticate, pair, django_capture_on_commit_callbacks):
    a, b, thread = pair
    authenticate(api_client, a)
    before = MessageThread.objects.get(pk=thread.pk).last_message_at

    with django_capture_on_commit_callbacks(execute=True):
        sent = api_client.post(
            f"{API}/{thread.id}/messages",
            {"senderId": str(a.id), "body": "  Hello!  "},
            format="json",
        )

    assert sent.status_code == 201
    msg = sent.json()
    assert set(msg) == {"id", "threadId", "senderId", "body", "sentAt"}
    assert msg["body"] == "Hello!" and msg["senderId"] == str(a.id)
    assert MessageThread.objects.get(pk=thread.pk).last_message_at > before
    event = OutboxEvent.objects.get(event_type="MessageSent")
    assert event.payload["recipient_ids"] == [str(b.id)]

    authenticate(api_client, b)
    api_client.post(
        f"{API}/{thread.id}/messages", {"senderId": str(b.id), "body": "Hi"}, format="json"
    )
    history = api_client.get(f"{API}/{thread.id}/messages").json()
    assert [m["body"] for m in history] == ["Hello!", "Hi"]  # sentAt ascending


def test_sender_id_must_match_token(api_client, authenticate, pair):
    a, b, thread = pair
    authenticate(api_client, a)
    response = api_client.post(
        f"{API}/{thread.id}/messages", {"senderId": str(b.id), "body": "spoof"}, format="json"
    )
    assert response.status_code == 403
    assert not Message.objects.exists()


def test_non_participants_get_404_for_read_and_write(api_client, authenticate, pair):
    _, _, thread = pair
    outsider = UserFactory()
    authenticate(api_client, outsider)
    assert api_client.get(f"{API}/{thread.id}/messages").status_code == 404
    response = api_client.post(
        f"{API}/{thread.id}/messages", {"senderId": str(outsider.id), "body": "x"}, format="json"
    )
    assert response.status_code == 404


@pytest.mark.parametrize("body", ["", "   ", "x" * 5001], ids=["empty", "blank", "too-long"])
def test_message_body_validation(api_client, authenticate, pair, body):
    a, _, thread = pair
    authenticate(api_client, a)
    response = api_client.post(f"{API}/{thread.id}/messages", {"body": body}, format="json")
    assert response.status_code == 400


def test_last_message_at_never_moves_backwards(pair):
    from apps.messaging import services

    a, _, thread = pair
    future = timezone.now() + datetime.timedelta(hours=1)
    MessageThread.objects.filter(pk=thread.pk).update(last_message_at=future)
    services.send_message(thread_id=thread.pk, sender=a, body="late commit")
    assert MessageThread.objects.get(pk=thread.pk).last_message_at == future


def test_anonymous_is_401(api_client):
    assert api_client.get(API).status_code == 401
