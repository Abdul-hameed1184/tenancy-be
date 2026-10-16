import threading

import pytest
from django.db import IntegrityError, connection

from apps.common.models import OutboxEvent
from apps.maintenance import services
from apps.maintenance.models import MaintenanceRequest
from tests.factories import (
    AgentFactory,
    AssignmentFactory,
    LandlordFactory,
    MaintenanceFactory,
    PropertyFactory,
    TenancyFactory,
)

API = "/api/v1/maintenance-requests"
KEYS = {
    "id", "propertyId", "tenantId", "issueType", "description", "priority", "status",
    "reportedAt",
}  # fmt: skip


@pytest.fixture
def setup(db):
    landlord, agent = LandlordFactory(), AgentFactory()
    prop = PropertyFactory(landlord=landlord)
    AssignmentFactory(property=prop, agent=agent)
    tenancy = TenancyFactory(property=prop)
    return {"landlord": landlord, "agent": agent, "property": prop, "tenant": tenancy.tenant}


def report_body(prop, **overrides):
    body = {
        "propertyId": str(prop.id),
        "tenantId": "spoofed",
        "issueType": "Electrical",
        "description": "Sockets in the bedroom don't work.",
        "priority": "high",
    }
    body.update(overrides)
    return body


# --- Create ---------------------------------------------------------------------------------


@pytest.mark.django_db
def test_tenant_reports_issue_with_defaults(api_client, authenticate, setup):
    authenticate(api_client, setup["tenant"])
    response = api_client.post(API, report_body(setup["property"]), format="json")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == KEYS
    assert body["status"] == "reported"
    assert body["tenantId"] == str(setup["tenant"].id)
    assert OutboxEvent.objects.filter(event_type="MaintenanceCreated").exists()


@pytest.mark.django_db
def test_tenant_cannot_report_for_a_property_they_dont_rent(api_client, authenticate, setup):
    authenticate(api_client, setup["tenant"])
    response = api_client.post(API, report_body(PropertyFactory()), format="json")
    assert response.status_code == 400
    assert "propertyId" in response.json()["errors"]


@pytest.mark.django_db
@pytest.mark.parametrize("role", ["agent", "landlord"])
def test_only_tenants_create(api_client, authenticate, setup, role):
    authenticate(api_client, setup[role])
    assert api_client.post(API, report_body(setup["property"]), format="json").status_code == 403


# --- Scope ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_each_role_sees_only_its_scope(api_client, authenticate, setup):
    mine = MaintenanceFactory(property=setup["property"], tenant=setup["tenant"])
    MaintenanceFactory()  # someone else's property entirely
    for who in ("landlord", "agent", "tenant"):
        authenticate(api_client, setup[who])
        assert [r["id"] for r in api_client.get(API).json()] == [str(mine.id)], who


@pytest.mark.django_db
def test_list_sorted_newest_first_and_filters_narrow(api_client, authenticate, setup):
    old = MaintenanceFactory(property=setup["property"], tenant=setup["tenant"])
    new = MaintenanceFactory(property=setup["property"], tenant=setup["tenant"])
    MaintenanceRequest.objects.filter(pk=old.pk).update(status="in_progress")
    authenticate(api_client, setup["agent"])
    assert [r["id"] for r in api_client.get(API).json()] == [str(new.id), str(old.id)]
    in_progress = api_client.get(API, {"status": "in_progress"}).json()
    assert [r["id"] for r in in_progress] == [str(old.id)]
    forged = api_client.get(API, {"agentId": str(AgentFactory().id)}).json()
    assert forged == []


@pytest.mark.django_db
def test_detail_outside_scope_is_404(api_client, authenticate, setup):
    other = MaintenanceFactory()
    authenticate(api_client, setup["tenant"])
    assert api_client.get(f"{API}/{other.id}").status_code == 404


# --- Status transitions ---------------------------------------------------------------------


@pytest.mark.django_db
def test_agent_walks_the_workflow_forward(api_client, authenticate, setup):
    req = MaintenanceFactory(property=setup["property"], tenant=setup["tenant"])
    authenticate(api_client, setup["agent"])

    first = api_client.patch(f"{API}/{req.id}", {"status": "in_progress"}, format="json")
    second = api_client.patch(f"{API}/{req.id}", {"status": "completed"}, format="json")

    assert first.json()["status"] == "in_progress"
    assert second.json()["status"] == "completed"
    req.refresh_from_db()
    assert req.completed_at is not None
    assert OutboxEvent.objects.filter(event_type="MaintenanceStatusChanged").count() == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("current", "target"),
    [
        ("reported", "completed"),  # skipping a step
        ("in_progress", "reported"),  # going backwards
        ("in_progress", "in_progress"),  # no-op
        ("completed", "in_progress"),  # reopening
    ],
)
def test_illegal_transitions_are_409(api_client, authenticate, setup, current, target):
    req = MaintenanceFactory(property=setup["property"], tenant=setup["tenant"])
    fields = {"status": current}
    if current == "completed":
        from django.utils import timezone

        fields["completed_at"] = timezone.now()
    MaintenanceRequest.objects.filter(pk=req.pk).update(**fields)
    authenticate(api_client, setup["agent"])
    response = api_client.patch(f"{API}/{req.id}", {"status": target}, format="json")
    assert response.status_code == 409
    req.refresh_from_db()
    assert req.status == current


@pytest.mark.django_db
def test_only_the_managing_agent_may_update(api_client, authenticate, setup):
    req = MaintenanceFactory(property=setup["property"], tenant=setup["tenant"])
    authenticate(api_client, AgentFactory())  # not managing this property
    response = api_client.patch(f"{API}/{req.id}", {"status": "in_progress"}, format="json")
    assert response.status_code == 404
    for role in ("tenant", "landlord"):
        authenticate(api_client, setup[role])
        response = api_client.patch(f"{API}/{req.id}", {"status": "in_progress"}, format="json")
        assert response.status_code == 403


@pytest.mark.django_db
def test_completed_at_must_match_status_in_database():
    with pytest.raises(IntegrityError):
        MaintenanceFactory(status="completed")  # no completed_at


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_transitions_apply_once():
    agent = AgentFactory()
    prop = PropertyFactory()
    AssignmentFactory(property=prop, agent=agent)
    req = MaintenanceFactory(property=prop)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def worker():
        try:
            barrier.wait()
            services.change_status(req=req, to="in_progress", actor=agent)
            outcomes.append("ok")
        except Exception as exc:
            outcomes.append(type(exc).__name__)
        finally:
            connection.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(outcomes) == ["Conflict", "ok"]
    assert OutboxEvent.objects.filter(event_type="MaintenanceStatusChanged").count() == 1


@pytest.mark.django_db
def test_anonymous_is_401(api_client):
    assert api_client.get(API).status_code == 401
