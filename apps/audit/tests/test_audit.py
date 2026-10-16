import pytest
from django.db import IntegrityError, connection, transaction

from apps.audit.models import AuditLog
from apps.audit.services import Action, record
from tests.factories import (
    AgentFactory,
    PropertyFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
API = "/api/v1"


def test_secrets_are_scrubbed_from_metadata_at_any_depth():
    entry = record(
        "TEST",
        metadata={
            "password": "hunter2",
            "refresh_token": "abc",
            "nested": {"Authorization": "Bearer x", "ok": 1},
            "fields": ["name"],
        },
    )
    assert entry.metadata == {"nested": {"ok": 1}, "fields": ["name"]}


def test_login_audit_captures_ip_and_user_agent(api_client):
    user = UserFactory(email="ada@example.com")
    api_client.post(
        f"{API}/auth/login",
        {"email": "ada@example.com", "password": "Correct-Horse-9"},
        format="json",
        HTTP_USER_AGENT="pytest-browser/1.0",
        REMOTE_ADDR="203.0.113.7",
    )
    entry = AuditLog.objects.get(action=Action.LOGIN)
    assert entry.actor == user
    assert entry.ip_address == "203.0.113.7" and entry.user_agent == "pytest-browser/1.0"


def test_sensitive_operations_leave_an_audit_trail(api_client, authenticate):
    prop = PropertyFactory()
    agent = AgentFactory()
    authenticate(api_client, prop.landlord)
    api_client.patch(f"{API}/properties/{prop.id}", {"title": "Renamed"}, format="json")
    api_client.put(f"{API}/properties/{prop.id}/agent", {"agentId": str(agent.id)}, format="json")
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {Action.PROPERTY_UPDATED, Action.AGENT_ASSIGNED} <= actions
    assigned = AuditLog.objects.get(action=Action.AGENT_ASSIGNED)
    assert assigned.entity_id == str(prop.id) and assigned.metadata["agent_id"] == str(agent.id)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE audit_auditlog SET action = 'FORGED' WHERE id = %s",
        "DELETE FROM audit_auditlog WHERE id = %s",
    ],
)
def test_trigger_rejects_edits_and_deletes(sql):
    entry = record("TEST", actor=UserFactory())
    with (
        pytest.raises(IntegrityError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(sql, [entry.pk])


def test_trigger_rejects_reassigning_the_actor():
    entry = record("TEST", actor=UserFactory())
    with pytest.raises(IntegrityError), transaction.atomic():
        AuditLog.objects.filter(pk=entry.pk).update(actor=UserFactory())


def test_deleting_a_user_keeps_their_trail_with_actor_nulled():
    user = UserFactory()
    entry = record("TEST", actor=user, metadata={"k": "v"})
    user.delete()  # FK ON DELETE SET NULL: the one UPDATE the trigger allows
    entry.refresh_from_db()
    assert entry.actor_id is None and entry.metadata == {"k": "v"}


def test_audit_admin_is_read_only(admin_client):
    from django.contrib import admin

    from apps.audit.admin import AuditLogAdmin

    model_admin = AuditLogAdmin(AuditLog, admin.site)
    assert not model_admin.has_add_permission(None)
    assert not model_admin.has_change_permission(None)
    assert not model_admin.has_delete_permission(None)
