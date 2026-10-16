import datetime
import threading

import pytest
from django.db import connection
from django.utils import timezone

from apps.common.models import OutboxEvent
from apps.inspections import services
from apps.inspections.models import Inspection
from tests.factories import (
    AgentFactory,
    AssignmentFactory,
    InspectionFactory,
    LandlordFactory,
    PropertyFactory,
    TenancyFactory,
    UserFactory,
)

API = "/api/v1/inspections"
KEYS = {
    "id", "propertyId", "tenantId", "agentId", "prospectName", "requestedAt", "scheduledAt",
    "status",
}  # fmt: skip


def future(days=3):
    return (timezone.now() + datetime.timedelta(days=days)).isoformat()


@pytest.fixture
def managed(db):
    agent = AgentFactory()
    prop = PropertyFactory()
    AssignmentFactory(property=prop, agent=agent)
    return prop, agent


def book_body(prop, agent=None, **overrides):
    body = {
        "propertyId": str(prop.id),
        "tenantId": "spoofed",
        "prospectName": "Chidi Okafor",
        "scheduledAt": future(),
    }
    if agent:
        body["agentId"] = str(agent.id)
    body.update(overrides)
    return body


# --- Booking --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_tenant_books_inspection_with_property_agent(api_client, authenticate, managed):
    prop, agent = managed
    tenant = UserFactory(role="tenant")
    authenticate(api_client, tenant)

    response = api_client.post(API, book_body(prop, agent), format="json")

    assert response.status_code == 201
    body = response.json()
    assert set(body) == KEYS
    assert body["status"] == "requested"
    assert body["agentId"] == str(agent.id)
    assert body["tenantId"] == str(tenant.id)
    assert OutboxEvent.objects.filter(event_type="InspectionRequested").exists()


@pytest.mark.django_db
def test_property_without_agent_cannot_be_booked(api_client, authenticate):
    authenticate(api_client, UserFactory(role="tenant"))
    response = api_client.post(API, book_body(PropertyFactory()), format="json")
    assert response.status_code == 400
    assert response.json()["message"] == (
        "Property id: This property has no managing agent and can't be booked."
    )


@pytest.mark.django_db
def test_occupied_property_cannot_be_booked(api_client, authenticate):
    assignment = AssignmentFactory()
    TenancyFactory(property=assignment.property)
    authenticate(api_client, UserFactory(role="tenant"))

    response = api_client.post(API, book_body(assignment.property, assignment.agent), format="json")

    assert response.status_code == 400
    assert "occupied or unavailable" in response.json()["message"]
    assert not Inspection.objects.exists()


@pytest.mark.django_db
def test_stale_agent_id_is_rejected(api_client, authenticate, managed):
    prop, _ = managed
    authenticate(api_client, UserFactory(role="tenant"))
    response = api_client.post(API, book_body(prop, AgentFactory()), format="json")
    assert response.status_code == 400


@pytest.mark.django_db
def test_past_schedule_is_rejected(api_client, authenticate, managed):
    prop, agent = managed
    authenticate(api_client, UserFactory(role="tenant"))
    response = api_client.post(
        API, book_body(prop, agent, scheduledAt=future(days=-1)), format="json"
    )
    assert response.status_code == 400
    assert "scheduledAt" in response.json()["errors"]


@pytest.mark.django_db
def test_only_tenants_book(api_client, authenticate, managed):
    prop, agent = managed
    authenticate(api_client, agent)
    assert api_client.post(API, book_body(prop, agent), format="json").status_code == 403


# --- Scope ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_scope_by_role_and_sort_by_schedule(api_client, authenticate, managed):
    prop, agent = managed
    tenant = UserFactory(role="tenant")
    later = InspectionFactory(property=prop, agent=agent, tenant=tenant, scheduled_at=future(9))
    sooner = InspectionFactory(property=prop, agent=agent, tenant=tenant, scheduled_at=future(1))
    InspectionFactory()  # unrelated

    for user in (agent, tenant, prop.landlord):
        authenticate(api_client, user)
        assert [i["id"] for i in api_client.get(API).json()] == [str(sooner.id), str(later.id)]


@pytest.mark.django_db
def test_forged_filter_narrows_to_nothing(api_client, authenticate):
    mine = InspectionFactory()
    authenticate(api_client, mine.tenant)
    assert api_client.get(API, {"tenantId": str(UserFactory().id)}).json() == []


# --- Transitions ----------------------------------------------------------------------------


@pytest.mark.django_db
def test_agent_confirms_then_completes(api_client, authenticate):
    insp = InspectionFactory()
    authenticate(api_client, insp.agent)
    assert api_client.post(f"{API}/{insp.id}/confirm").json()["status"] == "confirmed"
    assert api_client.post(f"{API}/{insp.id}/complete").json()["status"] == "completed"
    insp.refresh_from_db()
    assert insp.confirmed_at and insp.completed_at
    assert set(OutboxEvent.objects.values_list("event_type", flat=True)) == {
        "InspectionConfirmed",
        "InspectionCompleted",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("who", ["agent", "tenant"])
@pytest.mark.parametrize("start", ["requested", "confirmed"])
def test_agent_or_tenant_cancels_open_inspection(api_client, authenticate, who, start):
    insp = InspectionFactory(status=start)
    actor = getattr(insp, who)
    authenticate(api_client, actor)
    response = api_client.post(f"{API}/{insp.id}/cancel")
    assert response.json()["status"] == "cancelled"
    insp.refresh_from_db()
    assert insp.cancelled_by_id == actor.id and insp.cancelled_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("start", "action"),
    [
        ("requested", "complete"),  # must be confirmed first
        ("confirmed", "confirm"),
        ("completed", "cancel"),
        ("cancelled", "confirm"),
        ("cancelled", "cancel"),
    ],
)
def test_illegal_transitions_are_409(api_client, authenticate, start, action):
    insp = InspectionFactory(status=start, cancelled_at=timezone.now())
    authenticate(api_client, insp.agent)
    response = api_client.post(f"{API}/{insp.id}/{action}")
    assert response.status_code == 409
    insp.refresh_from_db()
    assert insp.status == start


@pytest.mark.django_db
def test_tenant_cannot_confirm_or_complete(api_client, authenticate):
    insp = InspectionFactory()
    authenticate(api_client, insp.tenant)
    assert api_client.post(f"{API}/{insp.id}/confirm").status_code == 403
    assert api_client.post(f"{API}/{insp.id}/complete").status_code == 403


@pytest.mark.django_db
def test_other_agent_cannot_touch_inspection(api_client, authenticate):
    insp = InspectionFactory()
    authenticate(api_client, AgentFactory())
    assert api_client.post(f"{API}/{insp.id}/confirm").status_code == 404


@pytest.mark.django_db
def test_landlord_reads_but_cannot_transition(api_client, authenticate):
    insp = InspectionFactory(property=PropertyFactory(landlord=LandlordFactory()))
    authenticate(api_client, insp.property.landlord)
    assert api_client.get(f"{API}/{insp.id}").status_code == 200
    assert api_client.post(f"{API}/{insp.id}/cancel").status_code == 403


@pytest.mark.django_db(transaction=True)
def test_confirm_and_cancel_racing_only_one_wins():
    insp = InspectionFactory()
    barrier = threading.Barrier(2)
    outcomes: dict[str, str] = {}

    def worker(action, actor):
        try:
            barrier.wait()
            services.apply_transition(insp=insp, action=action, actor=actor)
            outcomes[action] = "ok"
        except Exception as exc:
            outcomes[action] = type(exc).__name__
        finally:
            connection.close()

    threads = [
        threading.Thread(target=worker, args=("confirm", insp.agent)),
        threading.Thread(target=worker, args=("cancel", insp.tenant)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    insp.refresh_from_db()
    # Either order is legal (requested->confirmed->cancelled is allowed), but the final
    # state must be consistent with whichever transitions succeeded.
    if outcomes == {"confirm": "ok", "cancel": "ok"}:
        assert insp.status == "cancelled"
    else:
        assert sorted(outcomes.values()) == ["Conflict", "ok"]
        assert insp.status in {"confirmed", "cancelled"}
    assert Inspection.objects.count() == 1
