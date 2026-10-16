import datetime
import threading

import pytest
from django.db import IntegrityError, connection, transaction
from django.utils import timezone

from apps.common.models import OutboxEvent
from apps.payments import services
from apps.payments.models import AppendOnlyError, PaymentEntry
from tests.factories import (
    AgentFactory,
    AssignmentFactory,
    LandlordFactory,
    PaymentFactory,
    PropertyFactory,
    TenancyFactory,
    UserFactory,
)

API = "/api/v1"
ENTRY_KEYS = {
    "id", "tenancyId", "amount", "dueDate", "paidDate", "method", "loggedByAgentId",
    "loggedAt", "status",
}  # fmt: skip


@pytest.fixture
def managed_tenancy(db):
    agent = AgentFactory()
    prop = PropertyFactory()
    AssignmentFactory(property=prop, agent=agent)
    tenancy = TenancyFactory(
        property=prop,
        lease_start=datetime.date(2025, 10, 1),
        next_due_date=datetime.date(2026, 10, 1),
    )
    return tenancy, agent


def paid_body(**overrides):
    body = {
        "amount": 5_000_000,
        "dueDate": "2026-10-01T00:00:00.000Z",  # exactly what the frontend dialog sends
        "paidDate": "2026-09-28T14:03:11.000Z",
        "method": "bank_transfer",
        "status": "paid",
        "loggedByAgentId": "spoofed",
    }
    body.update(overrides)
    return body


def url(tenancy):
    return f"{API}/tenancies/{tenancy.id}/payments"


# --- Logging --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_agent_logs_paid_payment_and_due_date_advances(
    api_client, authenticate, managed_tenancy, django_capture_on_commit_callbacks
):
    tenancy, agent = managed_tenancy
    authenticate(api_client, agent)

    with django_capture_on_commit_callbacks(execute=True):
        response = api_client.post(url(tenancy), paid_body(), format="json")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == ENTRY_KEYS  # empty note omitted
    assert body["loggedByAgentId"] == str(agent.id)  # not the spoofed body value
    assert body["dueDate"] == "2026-10-01T00:00:00.000Z"
    assert body["paidDate"] == "2026-09-28T00:00:00.000Z"
    tenancy.refresh_from_db()
    assert tenancy.next_due_date == datetime.date(2027, 10, 1)
    assert set(OutboxEvent.objects.values_list("event_type", flat=True)) == {
        "PaymentCreated",
        "PaymentPaid",
    }


@pytest.mark.django_db
def test_due_entry_does_not_move_next_due_date(api_client, authenticate, managed_tenancy):
    tenancy, agent = managed_tenancy
    authenticate(api_client, agent)
    response = api_client.post(
        url(tenancy), paid_body(status="due", paidDate=None, note="Reminder sent"), format="json"
    )
    assert response.status_code == 201
    assert response.json()["paidDate"] is None and response.json()["note"] == "Reminder sent"
    tenancy.refresh_from_db()
    assert tenancy.next_due_date == datetime.date(2026, 10, 1)


@pytest.mark.django_db
def test_late_back_payment_never_moves_next_due_date_backwards(
    api_client, authenticate, managed_tenancy
):
    tenancy, agent = managed_tenancy
    authenticate(api_client, agent)
    # Paying the 2024 period now: dueDate + 1y = 2025-10-01, earlier than the current
    # 2026-10-01, so the next due date stays put.
    api_client.post(url(tenancy), paid_body(dueDate="2024-10-01"), format="json")
    tenancy.refresh_from_db()
    assert tenancy.next_due_date == datetime.date(2026, 10, 1)


def test_leap_day_rolls_to_28_february():
    assert services.add_one_year(datetime.date(2028, 2, 29)) == datetime.date(2029, 2, 28)


@pytest.mark.django_db
def test_second_paid_entry_for_same_period_is_409(api_client, authenticate, managed_tenancy):
    tenancy, agent = managed_tenancy
    authenticate(api_client, agent)
    assert api_client.post(url(tenancy), paid_body(), format="json").status_code == 201
    duplicate = api_client.post(url(tenancy), paid_body(), format="json")
    assert duplicate.status_code == 409
    assert duplicate.json() == {"message": "This due date has already been paid."}


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"paidDate": None}, "paidDate"),  # paid needs a paid date
        ({"status": "due"}, "paidDate"),  # only paid entries have one
        ({"amount": 0}, "amount"),
        ({"method": "crypto"}, "method"),
        ({"dueDate": "next tuesday"}, "dueDate"),
    ],
)
def test_validation(api_client, authenticate, managed_tenancy, overrides, field):
    tenancy, agent = managed_tenancy
    authenticate(api_client, agent)
    response = api_client.post(url(tenancy), paid_body(**overrides), format="json")
    assert response.status_code == 400
    assert field in response.json()["errors"]


# --- Who can log / read ---------------------------------------------------------------------


@pytest.mark.django_db
def test_unrelated_agent_gets_404(api_client, authenticate, managed_tenancy):
    tenancy, _ = managed_tenancy
    authenticate(api_client, AgentFactory())
    assert api_client.post(url(tenancy), paid_body(), format="json").status_code == 404


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["landlord", "tenant"])
def test_only_agents_log(api_client, authenticate, managed_tenancy, role):
    tenancy, _ = managed_tenancy
    user = tenancy.property.landlord if role == "landlord" else tenancy.tenant
    authenticate(api_client, user)
    assert api_client.post(url(tenancy), paid_body(), format="json").status_code == 403


@pytest.mark.django_db
def test_agent_replaced_mid_request_is_refused(managed_tenancy):
    """The service re-checks management under the row lock, not just at the view."""
    tenancy, agent = managed_tenancy
    assignment = agent.agent_assignments.get()
    assignment.active, assignment.unassigned_at = False, timezone.now()
    assignment.save()
    with pytest.raises(services.NotManagingAgent):
        services.log_payment(
            tenancy=tenancy,
            agent=agent,
            data={"amount": 1, "due_date": datetime.date(2026, 10, 1), "method": "cash",
                  "status": "due"},
        )  # fmt: skip


@pytest.mark.django_db
def test_history_sorted_by_due_date_for_every_reader(api_client, authenticate, managed_tenancy):
    tenancy, agent = managed_tenancy
    late = PaymentFactory(tenancy=tenancy, due_date=datetime.date(2025, 10, 1))
    early = PaymentFactory(tenancy=tenancy, due_date=datetime.date(2024, 10, 1))
    expected = [str(early.id), str(late.id)]
    for reader in (agent, tenancy.property.landlord, tenancy.tenant):
        authenticate(api_client, reader)
        assert [e["id"] for e in api_client.get(url(tenancy)).json()] == expected


@pytest.mark.django_db
def test_other_tenant_and_landlord_cannot_read(api_client, authenticate, managed_tenancy):
    tenancy, _ = managed_tenancy
    for outsider in (UserFactory(role="tenant"), LandlordFactory()):
        authenticate(api_client, outsider)
        assert api_client.get(url(tenancy)).status_code == 404


@pytest.mark.django_db
def test_tenancy_detail_embeds_sorted_payment_history(api_client, authenticate, managed_tenancy):
    tenancy, agent = managed_tenancy
    PaymentFactory(tenancy=tenancy, due_date=datetime.date(2025, 10, 1))
    PaymentFactory(tenancy=tenancy, due_date=datetime.date(2024, 10, 1))
    authenticate(api_client, agent)
    history = api_client.get(f"{API}/tenancies/{tenancy.id}").json()["paymentHistory"]
    assert [h["dueDate"][:10] for h in history] == ["2024-10-01", "2025-10-01"]


# --- Append-only ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_model_refuses_update_and_delete():
    entry = PaymentFactory()
    entry.amount = 1
    with pytest.raises(AppendOnlyError):
        entry.save()
    with pytest.raises(AppendOnlyError):
        entry.delete()
    with pytest.raises(AppendOnlyError):
        PaymentEntry.objects.filter(pk=entry.pk).update(amount=1)
    with pytest.raises(AppendOnlyError):
        PaymentEntry.objects.filter(pk=entry.pk).delete()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE payments_paymententry SET amount = 1 WHERE id = %s",
        "DELETE FROM payments_paymententry WHERE id = %s",
    ],
)
def test_database_trigger_refuses_raw_sql(sql):
    entry = PaymentFactory()
    # SQLSTATE restrict_violation (class 23) surfaces as IntegrityError.
    with (
        pytest.raises(IntegrityError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(sql, [entry.pk])


@pytest.mark.django_db
def test_database_rejects_paid_without_paid_date():
    with pytest.raises(IntegrityError):
        PaymentFactory(paid_date=None)


# --- Concurrency ----------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_duplicate_paid_payment_records_exactly_one():
    agent = AgentFactory()
    prop = PropertyFactory()
    AssignmentFactory(property=prop, agent=agent)
    tenancy = TenancyFactory(
        property=prop,
        lease_start=datetime.date(2025, 10, 1),
        next_due_date=datetime.date(2026, 10, 1),
    )
    data = {
        "amount": 5_000_000,
        "due_date": datetime.date(2026, 10, 1),
        "paid_date": datetime.date(2026, 9, 30),
        "method": "card",
        "status": "paid",
    }
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker():
        try:
            barrier.wait()
            services.log_payment(tenancy=tenancy, agent=agent, data=dict(data))
            outcomes.append("created")
        except Exception as exc:
            outcomes.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["Conflict", "created"]
    assert PaymentEntry.objects.filter(tenancy=tenancy, status="paid").count() == 1
    tenancy.refresh_from_db()
    assert tenancy.next_due_date == datetime.date(2027, 10, 1)  # advanced exactly once
