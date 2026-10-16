"""
Query budgets for list endpoints.

Each test creates many rows and pins the number of SQL queries. A serializer that starts
touching a relation per row (an N+1) fails here before it reaches production. Budgets
include the one authentication query (session + user + agent profile, joined).
"""

import pytest
from django.utils import timezone

from apps.notifications import services as notifications
from apps.reports.models import Report
from tests.factories import (
    AgentFactory,
    AssignmentFactory,
    InspectionFactory,
    LandlordFactory,
    MaintenanceFactory,
    PropertyFactory,
    TenancyFactory,
    ThreadFactory,
    UserFactory,
)

pytestmark = pytest.mark.django_db
API = "/api/v1"
ROWS = 12


def test_maintenance_list_budget(api_client, authenticate, django_assert_num_queries):
    agent = AgentFactory()
    for _ in range(ROWS):
        prop = PropertyFactory()
        AssignmentFactory(property=prop, agent=agent)
        MaintenanceFactory(property=prop)
    authenticate(api_client, agent)
    with django_assert_num_queries(2):
        assert len(api_client.get(f"{API}/maintenance-requests").json()) == ROWS


def test_inspection_list_budget(api_client, authenticate, django_assert_num_queries):
    agent = AgentFactory()
    InspectionFactory.create_batch(ROWS, agent=agent)
    authenticate(api_client, agent)
    with django_assert_num_queries(2):
        assert len(api_client.get(f"{API}/inspections").json()) == ROWS


def test_report_list_budget(api_client, authenticate, django_assert_num_queries):
    reporter = UserFactory(role="tenant")
    for _ in range(ROWS):
        Report.objects.create(
            type="listing", target_property=PropertyFactory(), reason="x", reported_by=reporter
        )
    authenticate(api_client, UserFactory(role="admin"))
    with django_assert_num_queries(2):
        assert len(api_client.get(f"{API}/reports").json()) == ROWS


def test_notification_feed_budget(api_client, authenticate, django_assert_num_queries):
    user = UserFactory()
    for i in range(ROWS):
        notifications.notify(
            recipient_id=user.pk, type="new_message", title="t", message="m", dedupe_key=f"k{i}"
        )
    authenticate(api_client, user)
    with django_assert_num_queries(2):
        assert len(api_client.get(f"{API}/notifications").json()) == ROWS


def test_thread_list_budget(api_client, authenticate, django_assert_num_queries):
    me = UserFactory()
    for _ in range(ROWS):
        ThreadFactory(members=[me, UserFactory(), UserFactory()])
    authenticate(api_client, me)
    with django_assert_num_queries(2):
        body = api_client.get(f"{API}/threads").json()
    assert len(body) == ROWS and all(len(t["participantIds"]) == 3 for t in body)


def test_tenancy_list_budget_with_payment_history(
    api_client, authenticate, django_assert_num_queries
):
    from tests.factories import PaymentFactory

    landlord = LandlordFactory()
    for _ in range(ROWS):
        tenancy = TenancyFactory(property=PropertyFactory(landlord=landlord))
        PaymentFactory(tenancy=tenancy)
    authenticate(api_client, landlord)
    with django_assert_num_queries(3):  # auth, tenancies (+joins, +agent), payments IN (...)
        body = api_client.get(f"{API}/tenancies").json()
    assert len(body) == ROWS and all(len(t["paymentHistory"]) == 1 for t in body)


def test_agent_directory_budget(api_client, django_assert_num_queries):
    for _ in range(ROWS):
        agent = AgentFactory()
        AssignmentFactory(agent=agent)
        AssignmentFactory(agent=agent, active=False, unassigned_at=timezone.now())
    with django_assert_num_queries(1):  # anonymous: no auth query; counts via FILTER
        assert len(api_client.get(f"{API}/agents").json()) == ROWS
