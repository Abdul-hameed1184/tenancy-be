import pytest
from django.db import IntegrityError

from apps.audit.models import AuditLog
from apps.reports.models import Report
from tests.factories import LandlordFactory, PropertyFactory, UserFactory

pytestmark = pytest.mark.django_db
API = "/api/v1/reports"
KEYS = {"id", "type", "targetId", "reason", "reportedById", "status", "createdAt"}


def file(api_client, type, target_id, **extra):
    body = {"type": type, "targetId": str(target_id), "reason": "Looks fraudulent", **extra}
    return api_client.post(API, body, format="json")


@pytest.mark.parametrize("role", ["landlord", "tenant"])
def test_landlords_and_tenants_file_reports(api_client, authenticate, role):
    reporter = UserFactory(role=role)
    authenticate(api_client, reporter)
    response = file(api_client, "listing", PropertyFactory().id, reportedById="spoofed")
    assert response.status_code == 201
    body = response.json()
    assert set(body) == KEYS
    assert body["status"] == "open" and body["reportedById"] == str(reporter.id)


@pytest.mark.parametrize("role", ["agent", "admin"])
def test_other_roles_cannot_file(api_client, authenticate, role):
    authenticate(api_client, UserFactory(role=role))
    assert file(api_client, "listing", PropertyFactory().id).status_code == 403


def test_user_report_targets_a_real_user_but_not_yourself(api_client, authenticate):
    me = UserFactory(role="tenant")
    authenticate(api_client, me)
    assert file(api_client, "user", UserFactory().id).status_code == 201
    assert file(api_client, "user", me.id).status_code == 400
    assert file(api_client, "listing", me.id).status_code == 400  # a user id isn't a listing


def test_database_enforces_target_matches_type():
    with pytest.raises(IntegrityError):
        Report.objects.create(
            type="listing", target_user=UserFactory(), reason="x", reported_by=UserFactory()
        )


def test_landlord_sees_only_reports_they_filed(api_client, authenticate):
    landlord = LandlordFactory()
    authenticate(api_client, landlord)
    mine = file(api_client, "listing", PropertyFactory().id).json()
    other = UserFactory(role="tenant")
    Report.objects.create(
        type="listing", target_property=PropertyFactory(), reason="x", reported_by=other
    )
    assert [r["id"] for r in api_client.get(API).json()] == [mine["id"]]
    forged = api_client.get(API, {"reportedById": str(other.id)}).json()
    assert forged == []


def test_admin_lists_filters_retrieves_and_resolves(api_client, authenticate):
    tenant = UserFactory(role="tenant")
    report = Report.objects.create(
        type="user", target_user=UserFactory(), reason="Spam", reported_by=tenant
    )
    Report.objects.create(type="listing", target_property=PropertyFactory(), reason="x",
                          reported_by=tenant, status="resolved",
                          resolved_at="2026-01-01T00:00:00Z")  # fmt: skip
    admin = UserFactory(role="admin")
    authenticate(api_client, admin)

    assert len(api_client.get(API).json()) == 2
    assert [r["id"] for r in api_client.get(API, {"status": "open", "type": "user"}).json()] == [
        str(report.id)
    ]
    assert api_client.get(f"{API}/{report.id}").json()["reason"] == "Spam"

    resolved = api_client.post(f"{API}/{report.id}/resolve")
    assert resolved.json()["status"] == "resolved"
    assert api_client.post(f"{API}/{report.id}/resolve").status_code == 409
    assert AuditLog.objects.filter(action="REPORT_RESOLVED", entity_id=str(report.id)).exists()


def test_only_admin_retrieves_or_resolves(api_client, authenticate):
    landlord = LandlordFactory()
    report = Report.objects.create(
        type="listing", target_property=PropertyFactory(), reason="x", reported_by=landlord
    )
    authenticate(api_client, landlord)
    assert api_client.get(f"{API}/{report.id}").status_code == 403
    assert api_client.post(f"{API}/{report.id}/resolve").status_code == 403


def test_tenants_cannot_list(api_client, authenticate):
    authenticate(api_client, UserFactory(role="tenant"))
    assert api_client.get(API).status_code == 403
